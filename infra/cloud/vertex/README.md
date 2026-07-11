# GCP Vertex AI training jobs

Vertex AI does **not** yet have a HuggingFace-blessed integration as deep as
[Azure ML](../azureml/) or [SageMaker](../sagemaker/). The path is to wrap
puffin as a custom training job using the `google-cloud-aiplatform` SDK.

See `src/llmops/providers/gcp.py` for the storage + registry side.
For now, the recommended path is:

1. Build a Docker image containing puffin (use `infra/docker/Dockerfile.train`).
2. Push to Artifact Registry.
3. `gcloud ai custom-jobs create` pointing at the image, with
   `python -m llmops.training.train_sft_lora --config configs/train.yaml`
   as the entrypoint.

A first-class `submit.py` here is planned but not yet implemented. PRs welcome.
