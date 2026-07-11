variable "project_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "notification_channels" {
  type    = list(string)
  default = []
}
