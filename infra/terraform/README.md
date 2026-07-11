# Terraform

Per-cloud root modules. Each one provisions the storage, container registry,
identity, and observability primitives the puffin pipeline needs to run on
that cloud. The Python code in `src/llmops/providers/` consumes these.

```text
infra/terraform/
├── gcp/              # Vertex AI + GCS + Artifact Registry
│   ├── envs/{dev,prod}/
│   └── modules/{storage,artifact_registry,iam,monitoring}/
├── aws/              # SageMaker + S3 + ECR
├── azure/            # Azure ML + Storage + ACR + Key Vault
└── kubernetes/       # vLLM-style serving Deployment + Service + HPA
```

## Common workflow

```bash
cd infra/terraform/gcp/envs/dev
terraform init
terraform plan -var project_id=$GCP_PROJECT_ID
terraform apply -var project_id=$GCP_PROJECT_ID
```

## What each module gives you

| Module                         | Resources |
| ------------------------------ | --------- |
| `gcp/modules/storage`          | 3 GCS buckets (raw / processed / artifacts) with versioning |
| `gcp/modules/artifact_registry`| Docker repo with cleanup policies |
| `gcp/modules/iam`              | Training + serving service accounts with least-privilege roles |
| `gcp/modules/monitoring`       | Log-based error metric + p95 latency alert policy |
| `aws/`                         | S3 buckets + ECR + SageMaker exec role + CloudWatch alarm |
| `azure/`                       | Resource group + storage + ACR + Azure ML workspace + Key Vault + Log Analytics |
| `kubernetes/`                  | Namespace + Deployment + Service + HPA, with optional GPU |

## Outputs feed Python configs

After `terraform apply`, copy the outputs into your `.env`:

```bash
terraform output -raw artifact_bucket   # → PUFFIN_GCS_BUCKET
terraform output -raw artifact_registry_repository
```

The `puffin` Python code reads those env vars in profiles like
`profiles/gcp_vertex.yaml`.
