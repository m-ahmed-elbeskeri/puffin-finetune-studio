variable "environment" {
  type = string
}

variable "namespace" {
  type    = string
  default = "puffin"
}

variable "serving_image" {
  type    = string
  default = "puffin-serve:latest"
}

variable "replicas" {
  type    = number
  default = 2
}

variable "max_replicas" {
  type    = number
  default = 10
}

variable "cpu_request" {
  type    = string
  default = "1"
}

variable "cpu_limit" {
  type    = string
  default = "4"
}

variable "memory_request" {
  type    = string
  default = "4Gi"
}

variable "memory_limit" {
  type    = string
  default = "16Gi"
}

variable "gpu_count" {
  type    = number
  default = 0
}

variable "env_vars" {
  type    = map(string)
  default = {}
}
