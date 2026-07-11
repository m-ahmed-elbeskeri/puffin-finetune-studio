variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
  }
}

variable "extra_tags" {
  type    = map(string)
  default = {}
}

variable "alarm_topic_arns" {
  type    = list(string)
  default = []
}
