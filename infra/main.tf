terraform {
  required_version = ">= 1.10"

  # Native S3 locking, so there is no DynamoDB table to own.
  backend "s3" {
    bucket       = "sift-tfstate-741448935060"
    key          = "sift/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "sift"
      ManagedBy = "terraform"
    }
  }
}

# CloudFront reads certificates from us-east-1 only, wherever the rest lives.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project   = "sift"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}
