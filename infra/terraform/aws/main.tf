###############################################################################
# puffin-finetune-studio — AWS root module
#
# Provisions: S3 buckets (raw / processed / artifacts), ECR repository,
# SageMaker execution role, CloudWatch log group + a starter alarm.
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  base_tags = merge(
    {
      app         = "puffin"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.extra_tags,
  )
  prefix = "puffin-${var.environment}"
}

# --- S3 buckets ---
resource "aws_s3_bucket" "raw" {
  bucket = "${local.prefix}-raw"
  tags   = local.base_tags
}

resource "aws_s3_bucket" "processed" {
  bucket = "${local.prefix}-processed"
  tags   = local.base_tags
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.prefix}-artifacts"
  tags   = local.base_tags
}

resource "aws_s3_bucket_versioning" "all" {
  for_each = {
    raw       = aws_s3_bucket.raw.id
    processed = aws_s3_bucket.processed.id
    artifacts = aws_s3_bucket.artifacts.id
  }
  bucket = each.value
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each = {
    raw       = aws_s3_bucket.raw.id
    processed = aws_s3_bucket.processed.id
    artifacts = aws_s3_bucket.artifacts.id
  }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = {
    raw       = aws_s3_bucket.raw.id
    processed = aws_s3_bucket.processed.id
    artifacts = aws_s3_bucket.artifacts.id
  }
  bucket = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --- ECR ---
resource "aws_ecr_repository" "puffin" {
  name                 = local.prefix
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }
  tags = local.base_tags
}

# --- SageMaker execution role ---
data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_exec" {
  name               = "${local.prefix}-sagemaker-exec"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
  tags               = local.base_tags
}

resource "aws_iam_role_policy_attachment" "sagemaker_full" {
  role       = aws_iam_role.sagemaker_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

data "aws_iam_policy_document" "puffin_s3" {
  statement {
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:GetBucketLocation",
    ]
    resources = [
      aws_s3_bucket.raw.arn,
      "${aws_s3_bucket.raw.arn}/*",
      aws_s3_bucket.processed.arn,
      "${aws_s3_bucket.processed.arn}/*",
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]
  }
}

resource "aws_iam_policy" "puffin_s3" {
  name   = "${local.prefix}-s3-access"
  policy = data.aws_iam_policy_document.puffin_s3.json
}

resource "aws_iam_role_policy_attachment" "sagemaker_s3" {
  role       = aws_iam_role.sagemaker_exec.name
  policy_arn = aws_iam_policy.puffin_s3.arn
}

# --- Logs + alarm ---
resource "aws_cloudwatch_log_group" "puffin" {
  name              = "/puffin/${var.environment}"
  retention_in_days = 30
  tags              = local.base_tags
}

resource "aws_cloudwatch_metric_alarm" "endpoint_5xx" {
  count               = length(var.alarm_topic_arns) > 0 ? 1 : 0
  alarm_name          = "${local.prefix}-endpoint-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5
  metric_name         = "Invocation5XXErrors"
  namespace           = "AWS/SageMaker"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Spike in SageMaker endpoint 5xx errors for puffin."
  alarm_actions       = var.alarm_topic_arns
  tags                = local.base_tags
}
