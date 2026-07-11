"""Submit a puffin training run to Amazon SageMaker.

Supports both GPU instances (ml.p4d, ml.g5, ml.g6) and AWS Trainium
(ml.trn1.32xlarge, ml.trn1n.32xlarge). For Trainium, set --instance-type to
a trn1* type — the script picks the Neuron PyTorch container automatically.

Usage:
    # GPU (QLoRA on a single A100):
    python infra/cloud/sagemaker/submit.py --config configs/train.yaml \
        --instance-type ml.g5.2xlarge

    # Trainium (Neuron distributed):
    python infra/cloud/sagemaker/submit.py --config configs/train.yaml \
        --instance-type ml.trn1.32xlarge --neuron

Requires:
    pip install -e ".[aws]"
    AWS credentials (env vars, ~/.aws/credentials, or IAM instance role)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _import_sagemaker():
    try:
        import sagemaker
        from sagemaker.huggingface import HuggingFace

        return sagemaker, HuggingFace
    except ImportError as e:
        raise ImportError(
            "SageMaker submission needs `pip install sagemaker`. "
            "Install puffin-finetune-studio[aws] for the bundled deps."
        ) from e


# AWS Deep Learning Containers — keep these in sync with the SageMaker docs.
# https://github.com/aws/deep-learning-containers/blob/master/available_images.md
DEFAULT_PYTORCH_VERSION = "2.3.0"
DEFAULT_TRANSFORMERS_VERSION = "4.46.0"
DEFAULT_PY_VERSION = "py311"
NEURON_IMAGE_ENV = "AWS_NEURON_SDK_VERSION"


def _is_neuron_instance(instance_type: str) -> bool:
    return instance_type.startswith("ml.trn") or instance_type.startswith("ml.inf2")


def submit(
    train_config: Path,
    *,
    role: str,
    instance_type: str,
    instance_count: int = 1,
    region: str | None = None,
    bucket: str | None = None,
    job_name: str | None = None,
    neuron: bool = False,
    pytorch_version: str = DEFAULT_PYTORCH_VERSION,
    transformers_version: str = DEFAULT_TRANSFORMERS_VERSION,
    py_version: str = DEFAULT_PY_VERSION,
    env_vars: dict[str, str] | None = None,
    dry_run: bool = False,
) -> str:
    sagemaker, HuggingFace = _import_sagemaker()

    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = Path(train_config)
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(f"Train config not found: {cfg_path}")
    relative_cfg = cfg_path.relative_to(repo_root)

    is_neuron = neuron or _is_neuron_instance(instance_type)
    if neuron and not _is_neuron_instance(instance_type):
        print(f"[warn] --neuron set but instance-type {instance_type!r} is not Trainium.",
              file=sys.stderr)

    env_vars = {
        "PYTHONUTF8": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TRANSFORMERS_VERBOSITY": "error",
        **(env_vars or {}),
    }

    # SageMaker writes outputs to /opt/ml/model in-container; we map artifacts there.
    entry_command = (
        "pip install --no-deps -e . && "
        f"python -m llmops.training.train_sft_lora --config {relative_cfg.as_posix()} && "
        "cp -r artifacts/. /opt/ml/model/ || true"
    )

    if not job_name:
        job_name = f"puffin-finetune-{int(time.time())}"

    hf_estimator_kwargs: dict[str, object] = dict(
        entry_point="run_in_container.sh",      # written below
        source_dir=str(repo_root),
        role=role,
        instance_count=instance_count,
        instance_type=instance_type,
        environment=env_vars,
        base_job_name=job_name,
        py_version=py_version,
    )

    # Pick the right image family. SageMaker auto-resolves the container if we
    # set pytorch_version + transformers_version for GPU, or use the Neuron
    # image directly for Trainium.
    if is_neuron:
        # Neuron SDK images are versioned independently. Default to a current
        # pinned tag and let the user override via AWS_NEURON_SDK_VERSION env.
        neuron_image = os.environ.get(
            "PUFFIN_SAGEMAKER_NEURON_IMAGE",
            # As of writing: 763104351884.dkr.ecr.{region}.amazonaws.com/pytorch-training-neuronx:2.1.2-neuronx-py310-sdk2.19.1-ubuntu20.04
            # User should override for the latest. Set image_uri explicitly:
            "",
        )
        if neuron_image:
            hf_estimator_kwargs["image_uri"] = neuron_image
        # Neuron images don't accept transformers_version; rely on image's preinstalled stack.
    else:
        hf_estimator_kwargs["transformers_version"] = transformers_version
        hf_estimator_kwargs["pytorch_version"] = pytorch_version

    # Write the entrypoint shell script (SageMaker invokes this as `bash entry_point`).
    entry_script = repo_root / "run_in_container.sh"
    entry_script.write_text(
        "#!/usr/bin/env bash\nset -euxo pipefail\n" + entry_command + "\n",
        encoding="utf-8",
    )

    if dry_run:
        print(f"[dry-run] Would submit to SageMaker: instance={instance_type}, count={instance_count}, neuron={is_neuron}")
        print(f"[dry-run] command: {entry_command}")
        return job_name

    estimator = HuggingFace(**hf_estimator_kwargs)
    # No S3 inputs needed — the repo is bundled with `source_dir`.
    estimator.fit(wait=False, job_name=job_name)
    print(f"Submitted SageMaker job: {job_name}")
    print(f"AWS console: https://{region or 'us-east-1'}.console.aws.amazon.com/sagemaker/home#/jobs/{job_name}")
    return job_name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Submit puffin training to AWS SageMaker.")
    p.add_argument("--config", required=True, help="Path to configs/train.yaml")
    p.add_argument("--role", default=os.environ.get("SAGEMAKER_EXECUTION_ROLE"),
                   help="SageMaker IAM execution role ARN (or set SAGEMAKER_EXECUTION_ROLE).")
    p.add_argument("--instance-type", required=True,
                   help="ml.g5.2xlarge / ml.p4d.24xlarge / ml.trn1.32xlarge / etc.")
    p.add_argument("--instance-count", type=int, default=1)
    p.add_argument("--region", default=os.environ.get("AWS_REGION"))
    p.add_argument("--bucket", default=None, help="S3 bucket for staging.")
    p.add_argument("--job-name", default=None,
                   help="Override the autogenerated job name.")
    p.add_argument("--neuron", action="store_true",
                   help="Force the Neuron container path. Auto-detected from instance-type.")
    p.add_argument("--pytorch-version", default=DEFAULT_PYTORCH_VERSION)
    p.add_argument("--transformers-version", default=DEFAULT_TRANSFORMERS_VERSION)
    p.add_argument("--py-version", default=DEFAULT_PY_VERSION)
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be submitted, but don't.")
    args = p.parse_args(argv)

    if not args.role:
        print("--role is required (or set SAGEMAKER_EXECUTION_ROLE).", file=sys.stderr)
        return 2

    submit(
        train_config=Path(args.config),
        role=args.role,
        instance_type=args.instance_type,
        instance_count=args.instance_count,
        region=args.region,
        bucket=args.bucket,
        job_name=args.job_name,
        neuron=args.neuron,
        pytorch_version=args.pytorch_version,
        transformers_version=args.transformers_version,
        py_version=args.py_version,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
