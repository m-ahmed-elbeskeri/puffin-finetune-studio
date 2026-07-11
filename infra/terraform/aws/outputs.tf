output "raw_bucket" {
  value = aws_s3_bucket.raw.bucket
}

output "processed_bucket" {
  value = aws_s3_bucket.processed.bucket
}

output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "ecr_repository_url" {
  value = aws_ecr_repository.puffin.repository_url
}

output "sagemaker_role_arn" {
  value = aws_iam_role.sagemaker_exec.arn
}

output "log_group" {
  value = aws_cloudwatch_log_group.puffin.name
}
