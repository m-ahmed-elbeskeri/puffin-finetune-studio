"""Kubeflow Pipelines (KFP) DAG that runs on Vertex AI Pipelines.

Compile:
    python pipelines/vertex_pipeline.py --compile pipelines/compiled.json

Submit:
    python pipelines/vertex_pipeline.py --submit \
        --project $GCP_PROJECT_ID --location $GCP_REGION \
        --pipeline-root gs://$PUFFIN_GCS_BUCKET/pipelines

The pipeline mirrors the local Make targets:
    data → train → evaluate → gate → register
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

try:
    from kfp import compiler, dsl
    from kfp.dsl import Dataset, Input, Metrics, Model, Output  # noqa: F401
except ImportError:  # pragma: no cover
    print(
        "kfp is required for Vertex pipelines. Install with: pip install kfp>=2",
        file=sys.stderr,
    )
    raise


IMAGE_TRAIN = "us-docker.pkg.dev/${GCP_PROJECT_ID}/puffin/train:latest"
IMAGE_EVAL = "us-docker.pkg.dev/${GCP_PROJECT_ID}/puffin/eval:latest"


@dsl.component(base_image=IMAGE_TRAIN)
def data_pipeline(config_path: str = "configs/data.yaml") -> str:
    import subprocess

    for module in [
        "llmops.data.ingest",
        "llmops.data.validate",
        "llmops.data.redact_pii",
        "llmops.data.dedupe",
        "llmops.data.split",
        "llmops.data.build_dataset_card",
    ]:
        subprocess.run(
            ["python", "-m", module, "--config", config_path],
            check=True,
        )
    return "data/processed/"


@dsl.component(base_image=IMAGE_TRAIN)
def train_step(
    train_config: str = "configs/train.yaml",
    smoke_test: bool = False,
) -> str:
    import subprocess

    args = ["python", "-m", "llmops.training.train_sft_lora", "--config", train_config]
    if smoke_test:
        args.append("--smoke-test")
    subprocess.run(args, check=True)
    return "artifacts/adapter"


@dsl.component(base_image=IMAGE_EVAL)
def eval_step(eval_config: str = "configs/eval.yaml") -> str:
    import subprocess

    for module in [
        "llmops.evaluation.task_eval",
        "llmops.evaluation.safety_eval",
        "llmops.evaluation.regression_eval",
        "llmops.evaluation.latency_eval",
    ]:
        subprocess.run(["python", "-m", module, "--config", eval_config], check=True)
    return "artifacts/eval/metrics.json"


@dsl.component(base_image=IMAGE_EVAL)
def gate_step(
    eval_config: str = "configs/eval.yaml",
    metrics_path: str = "artifacts/eval/metrics.json",
) -> str:
    import subprocess

    subprocess.run(
        ["python", "-m", "llmops.evaluation.gate", "--config", eval_config, "--metrics", metrics_path],
        check=True,
    )
    return "passed"


@dsl.component(base_image=IMAGE_TRAIN)
def register_step(model_dir: str, model_name: str, alias: str = "candidate") -> str:
    import subprocess

    out = subprocess.run(
        [
            "python",
            "-m",
            "llmops.training.push_model",
            "--model-dir",
            model_dir,
            "--name",
            model_name,
            "--alias",
            alias,
            "--metrics",
            "artifacts/eval/metrics.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip().splitlines()[-1]


@dsl.pipeline(
    name="puffin-finetune-pipeline",
    description="Data → train → evaluate → gate → register, on Vertex AI Pipelines.",
)
def puffin_pipeline(
    data_config: str = "configs/data.yaml",
    train_config: str = "configs/train.yaml",
    eval_config: str = "configs/eval.yaml",
    model_name: str = "puffin-customer-support",
    smoke_test: bool = False,
) -> None:
    data = data_pipeline(config_path=data_config)
    train = train_step(train_config=train_config, smoke_test=smoke_test).after(data)
    evaluate = eval_step(eval_config=eval_config).after(train)
    gate = gate_step(eval_config=eval_config, metrics_path=evaluate.output).after(evaluate)
    register_step(
        model_dir=train.output,
        model_name=model_name,
    ).after(gate)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compile / submit the Vertex pipeline.")
    parser.add_argument("--compile", dest="compile_to", default=None)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--project", default=None)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--pipeline-root", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)

    target = args.compile_to or "pipelines/compiled.json"
    compiler.Compiler().compile(pipeline_func=puffin_pipeline, package_path=target)
    print(f"compiled pipeline → {target}")

    if args.submit:
        from google.cloud import aiplatform  # type: ignore

        aiplatform.init(project=args.project, location=args.location)
        job = aiplatform.PipelineJob(
            display_name="puffin-finetune-pipeline",
            template_path=target,
            pipeline_root=args.pipeline_root,
            parameter_values={"smoke_test": args.smoke_test},
            enable_caching=False,
        )
        job.submit()
        print(f"submitted: {job.resource_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
