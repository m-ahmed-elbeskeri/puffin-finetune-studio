"""AWS provider: S3 storage + SageMaker registry / training / endpoints.

Lazy-imports boto3 and sagemaker.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger
from llmops.common.storage import StorageURI

log = get_logger(__name__)


def _import_boto3():
    try:
        import boto3  # type: ignore

        return boto3
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "boto3 not installed. Install puffin-finetune-studio[aws]."
        ) from exc


def _import_sagemaker():
    try:
        import sagemaker  # type: ignore

        return sagemaker
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "sagemaker not installed. Install puffin-finetune-studio[aws]."
        ) from exc


class S3Storage:
    name = "s3"

    def __init__(self, default_bucket: str | None = None, region: str | None = None) -> None:
        self.default_bucket = default_bucket or os.environ.get("PUFFIN_S3_BUCKET")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _import_boto3().client("s3", region_name=self.region)
        return self._client

    def _split(self, remote_path: str) -> tuple[str, str]:
        u = StorageURI.parse(remote_path)
        if u.scheme == "s3":
            return u.bucket, u.path
        if not self.default_bucket:
            raise ValueError(f"remote_path {remote_path!r} is not s3:// and no default_bucket set")
        return self.default_bucket, remote_path.lstrip("/")

    def upload(self, local_path: str | Path, remote_path: str) -> str:
        bucket, key = self._split(remote_path)
        local = Path(local_path)
        if local.is_dir():
            for f in local.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(local).as_posix()
                    self.client.upload_file(str(f), bucket, f"{key.rstrip('/')}/{rel}")
            return f"s3://{bucket}/{key}"
        self.client.upload_file(str(local), bucket, key)
        return f"s3://{bucket}/{key}"

    def download(self, remote_path: str, local_path: str | Path) -> Path:
        bucket, key = self._split(remote_path)
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)

        objs = self.client.list_objects_v2(Bucket=bucket, Prefix=key).get("Contents", [])
        if not objs:
            raise FileNotFoundError(f"no objects at s3://{bucket}/{key}")
        if len(objs) == 1 and objs[0]["Key"] == key:
            self.client.download_file(bucket, key, str(local))
            return local
        local.mkdir(parents=True, exist_ok=True)
        for o in objs:
            rel = o["Key"][len(key) :].lstrip("/")
            target = local / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(bucket, o["Key"], str(target))
        return local

    def exists(self, remote_path: str) -> bool:
        bucket, key = self._split(remote_path)
        from botocore.exceptions import ClientError  # type: ignore

        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False

    def list(self, prefix: str) -> list[str]:
        bucket, key = self._split(prefix)
        return [
            o["Key"]
            for o in self.client.list_objects_v2(Bucket=bucket, Prefix=key).get("Contents", [])
        ]

    def open_read(self, remote_path: str) -> bytes:
        bucket, key = self._split(remote_path)
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def open_write(self, remote_path: str, data: bytes) -> str:
        bucket, key = self._split(remote_path)
        self.client.put_object(Bucket=bucket, Key=key, Body=data)
        return f"s3://{bucket}/{key}"


class SageMakerRegistry:
    name = "sagemaker"

    def __init__(self, region: str | None = None, role_arn: str | None = None) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.role_arn = role_arn or os.environ.get("AWS_SAGEMAKER_ROLE_ARN")
        self._sm: Any = None

    @property
    def sm(self) -> Any:
        if self._sm is None:
            self._sm = _import_boto3().client("sagemaker", region_name=self.region)
        return self._sm

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        with contextlib.suppress(self.sm.exceptions.ResourceInUse):
            self.sm.create_model_package_group(ModelPackageGroupName=name)

        inference_image = os.environ.get(
            "PUFFIN_SAGEMAKER_INFERENCE_IMAGE",
            "763104351884.dkr.ecr.us-east-1.amazonaws.com/huggingface-pytorch-tgi-inference:2.4.0-tgi2.4.0-gpu-py311-cu124-ubuntu22.04",
        )
        response = self.sm.create_model_package(
            ModelPackageGroupName=name,
            InferenceSpecification={
                "Containers": [
                    {
                        "Image": inference_image,
                        "ModelDataUrl": str(model_path),
                    }
                ],
                "SupportedContentTypes": ["application/json"],
                "SupportedResponseMIMETypes": ["application/json"],
            },
            ModelMetrics=(
                {
                    "ModelQuality": {
                        "Statistics": {
                            "ContentType": "application/json",
                            "S3Uri": str(model_path) + "/metrics.json",
                        }
                    }
                }
                if metrics
                else {}
            ),
            ModelApprovalStatus="PendingManualApproval",
        )
        log.info(
            "registered SageMaker package %s arn=%s",
            name,
            response["ModelPackageArn"],
        )
        return response["ModelPackageArn"]

    def promote(self, name: str, version: str, alias: str) -> None:
        status = "Approved" if alias in {"production", "staging"} else "PendingManualApproval"
        arn = self._find_arn(name, version)
        self.sm.update_model_package(ModelPackageArn=arn, ModelApprovalStatus=status)
        log.info("set model %s v%s status=%s (alias=%s)", name, version, status, alias)

    def _find_arn(self, name: str, version: str) -> str:
        packages = self.sm.list_model_packages(ModelPackageGroupName=name)[
            "ModelPackageSummaryList"
        ]
        for p in packages:
            if str(p["ModelPackageVersion"]) == version:
                return p["ModelPackageArn"]
        raise KeyError(f"no version {version} in SageMaker package group {name}")

    def get_model_uri(self, name: str, alias: str = "production") -> str:
        packages = self.sm.list_model_packages(ModelPackageGroupName=name)[
            "ModelPackageSummaryList"
        ]
        approved = [p for p in packages if p["ModelApprovalStatus"] == "Approved"]
        if not approved:
            raise KeyError(f"no approved versions of {name}")
        return approved[0]["ModelPackageArn"]

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        packages = self.sm.list_model_packages(ModelPackageGroupName=name)[
            "ModelPackageSummaryList"
        ]
        return [
            {
                "version": str(p["ModelPackageVersion"]),
                "arn": p["ModelPackageArn"],
                "status": p["ModelApprovalStatus"],
                "create_time": str(p["CreationTime"]),
            }
            for p in packages
        ]


class SageMakerEndpointDeployment:
    name = "sagemaker_endpoint"

    def __init__(self, region: str | None = None, role_arn: str | None = None) -> None:
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.role_arn = role_arn or os.environ.get("AWS_SAGEMAKER_ROLE_ARN")
        self._sm: Any = None

    @property
    def sm(self) -> Any:
        if self._sm is None:
            self._sm = _import_boto3().client("sagemaker", region_name=self.region)
        return self._sm

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str:
        _import_sagemaker()  # asserts the SDK is installed
        endpoint_name = f"puffin-{environment}"
        with contextlib.suppress(self.sm.exceptions.ResourceInUse):
            self.sm.create_model(
                ModelName=f"{endpoint_name}-{int(__import__('time').time())}",
                PrimaryContainer={"ModelPackageName": model_ref},
                ExecutionRoleArn=self.role_arn,
            )
        return endpoint_name

    def rollback(self, environment: str) -> str:
        log.warning("SageMaker rollback requires UpdateEndpoint with previous EndpointConfig")
        return f"sagemaker-endpoint://{environment}"

    def get_endpoint_url(self, environment: str) -> str:
        return f"https://runtime.sagemaker.{self.region}.amazonaws.com/endpoints/puffin-{environment}/invocations"
