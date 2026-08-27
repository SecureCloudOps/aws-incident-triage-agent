variable "aws_region" {
  description = "AWS region in which to create the resources."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid AWS region name."
  }
}

variable "name_prefix" {
  description = "Prefix used to name resources."
  type        = string
  default     = "buggy-service"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,30}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 2-32 lowercase letters, numbers, or hyphens and cannot start or end with a hyphen."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "public_subnet_cidrs" {
  description = "IPv4 CIDR blocks for public subnets. One subnet is created per CIDR in a different availability zone."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]

  validation {
    condition = (
      length(var.public_subnet_cidrs) >= 2 &&
      length(var.public_subnet_cidrs) == length(distinct(var.public_subnet_cidrs)) &&
      alltrue([for cidr in var.public_subnet_cidrs : can(cidrnetmask(cidr))])
    )
    error_message = "Provide at least two unique, valid IPv4 subnet CIDR blocks."
  }
}

variable "allowed_ingress_cidrs" {
  description = "IPv4 CIDR blocks allowed to connect directly to the service port. The non-routable default forces an explicit operator choice."
  type        = set(string)
  default     = ["203.0.113.10/32"]

  validation {
    condition     = length(var.allowed_ingress_cidrs) > 0 && alltrue([for cidr in var.allowed_ingress_cidrs : can(cidrnetmask(cidr))])
    error_message = "allowed_ingress_cidrs must contain at least one valid IPv4 CIDR block."
  }
}

variable "container_image" {
  description = "Container image URI, preferably an immutable ECR image digest."
  type        = string

  validation {
    condition     = length(trimspace(var.container_image)) > 0
    error_message = "container_image must not be empty."
  }
}

variable "container_port" {
  description = "Port exposed by the FastAPI container."
  type        = number
  default     = 8000

  validation {
    condition     = var.container_port >= 1 && var.container_port <= 65535
    error_message = "container_port must be between 1 and 65535."
  }
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 256

  validation {
    condition     = contains([256, 512, 1024, 2048, 4096], var.task_cpu)
    error_message = "task_cpu must be a supported Fargate CPU value."
  }
}

variable "task_memory" {
  description = "Fargate task memory in MiB. The value must be compatible with task_cpu."
  type        = number
  default     = 512
}

variable "cpu_architecture" {
  description = "CPU architecture used by the published container image."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "desired_count" {
  description = "Number of Fargate tasks to run."
  type        = number
  default     = 1

  validation {
    condition     = var.desired_count >= 1 && floor(var.desired_count) == var.desired_count
    error_message = "desired_count must be a positive whole number."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention period."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a retention period supported by CloudWatch Logs."
  }
}

variable "tags" {
  description = "Additional tags to apply to all supported resources."
  type        = map(string)
  default     = {}
}
