"""Submit a puffin training run to Azure ML.

Wraps `configs/train.yaml` as an AzureML command job. The job runs
`python -m llmops.training.train_sft_lora --config <config>` on the requested
compute and saves outputs to a registered artifact folder.

Usage:
    python infra/cloud/azureml/submit.py \
        --config configs/train.yaml \
        --workspace-name <ws> --resource-group <rg> --subscription <sub> \
        --compute gpu-cluster \
        --instance-type Standard_NC24ads_A100_v4

Requires:
    pip install -e ".[azure]"
    az login   (or a service principal with AZURE_* env vars set)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _import_azureml():
    try:
        from azure.ai.ml import MLClient, command
        from azure.ai.ml.entities import (
            BuildContext,
            CommandJob,
            Environment,
            JobResourceConfiguration,
        )
        from azure.identity import DefaultAzureCredential

        return MLClient, command, CommandJob, JobResourceConfiguration, Environment, BuildContext, DefaultAzureCredential
    except ImportError as e:
        raise ImportError(
            "Azure ML submission needs `pip install azure-ai-ml azure-identity`. "
            "Install puffin-finetune-studio[azure] for the bundled deps."
        ) from e


# Sensible defaults — caller can override every one.
DEFAULT_ENVIRONMENT = (
    "azureml://registries/HuggingFace/environments/"
    "transformers-pytorch-gpu/labels/latest"
)


def submit(
    train_config: Path,
    *,
    subscription_id: str,
    resource_group: str,
    workspace_name: str,
    compute_target: str,
    instance_type: str | None = None,
    instance_count: int = 1,
    experiment_name: str = "puffin-finetune",
    display_name: str = "puffin-sft-lora",
    environment: str = DEFAULT_ENVIRONMENT,
    distribution_type: str | None = None,
    processes_per_instance: int = 1,
    env_vars: dict[str, str] | None = None,
    dry_run: bool = False,
) -> str:
    MLClient, command, _, JobResourceConfiguration, *_ = _import_azureml()
    DefaultAzureCredential = _import_azureml()[-1]

    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = Path(train_config)
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(f"Train config not found: {cfg_path}")
    relative_cfg = cfg_path.relative_to(repo_root)

    env_vars = {
        "PYTHONUTF8": "1",
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "TRANSFORMERS_VERBOSITY": "error",
        **(env_vars or {}),
    }

    job_command = (
        "pip install --no-deps -e . && "
        f"python -m llmops.training.train_sft_lora --config {relative_cfg.as_posix()}"
    )

    resources = JobResourceConfiguration(instance_count=instance_count, shm_size="16g")
    if instance_type:
        resources.instance_type = instance_type

    distribution = None
    if distribution_type:
        # Lazy import to avoid hard dep when not needed.
        from azure.ai.ml import PyTorchDistribution

        if distribution_type.lower() != "pytorch":
            raise ValueError(
                f"Only 'pytorch' distribution is wired right now; got {distribution_type!r}."
            )
        distribution = PyTorchDistribution(process_count_per_instance=processes_per_instance)

    job = command(
        code=str(repo_root),
        command=job_command,
        environment=environment,
        compute=compute_target,
        experiment_name=experiment_name,
        display_name=display_name,
        resources=resources,
        distribution=distribution,
        environment_variables=env_vars,
    )

    if dry_run:
        print(f"[dry-run] Would submit to ws={workspace_name} compute={compute_target}")
        print(f"[dry-run] command: {job_command}")
        return ""

    client = MLClient(
        credential=DefaultAzureCredential(),
        subscription_id=subscription_id,
        resource_group_name=resource_group,
        workspace_name=workspace_name,
    )
    returned = client.jobs.create_or_update(job)
    print(f"Submitted job: {returned.name}")
    print(f"Studio URL:    {returned.studio_url}")
    return returned.name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Submit puffin training to Azure ML.")
    p.add_argument("--config", required=True, help="Path to configs/train.yaml")
    p.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"),
                   help="Azure subscription ID (or set AZURE_SUBSCRIPTION_ID).")
    p.add_argument("--resource-group", default=os.environ.get("AZURE_RESOURCE_GROUP"),
                   help="Resource group (or set AZURE_RESOURCE_GROUP).")
    p.add_argument("--workspace-name", default=os.environ.get("AZURE_ML_WORKSPACE"),
                   help="AzureML workspace name (or set AZURE_ML_WORKSPACE).")
    p.add_argument("--compute", required=True,
                   help="AmlCompute target name (e.g. 'gpu-cluster').")
    p.add_argument("--instance-type", default=None,
                   help="VM size override (e.g. Standard_NC24ads_A100_v4).")
    p.add_argument("--instance-count", type=int, default=1,
                   help="Number of nodes. >1 enables distributed.")
    p.add_argument("--display-name", default="puffin-sft-lora")
    p.add_argument("--experiment-name", default="puffin-finetune")
    p.add_argument("--environment", default=DEFAULT_ENVIRONMENT,
                   help="AzureML environment URI.")
    p.add_argument("--distributed", action="store_true",
                   help="Run with PyTorch distributed (1 process per GPU).")
    p.add_argument("--processes-per-instance", type=int, default=1)
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be submitted, but don't.")
    args = p.parse_args(argv)

    for required in ("subscription", "resource_group", "workspace_name"):
        if not getattr(args, required.replace("-", "_")):
            print(f"--{required.replace('_', '-')} is required (or set AZURE_* env vars).",
                  file=sys.stderr)
            return 2

    submit(
        train_config=Path(args.config),
        subscription_id=args.subscription,
        resource_group=args.resource_group,
        workspace_name=args.workspace_name,
        compute_target=args.compute,
        instance_type=args.instance_type,
        instance_count=args.instance_count,
        display_name=args.display_name,
        experiment_name=args.experiment_name,
        environment=args.environment,
        distribution_type="pytorch" if args.distributed else None,
        processes_per_instance=args.processes_per_instance,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
