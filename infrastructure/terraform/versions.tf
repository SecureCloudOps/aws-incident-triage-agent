terraform {
  required_version = "= 1.14.3"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.62.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        ManagedBy = "Terraform"
        Project   = var.name_prefix
      },
      var.tags
    )
  }
}
