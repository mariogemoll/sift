variable "region" {
  description = "Where the stack lives. London, for a UK audience."
  type        = string
  default     = "eu-west-2"
}

variable "name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "sift"
}

variable "domain_name" {
  description = <<-DESC
    Custom domain for the site, e.g. sift.example.com. Empty means the
    distribution answers on its own *.cloudfront.net name and no certificate
    is requested. See README.md for the two-phase apply a domain needs.
  DESC
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Image tag the service runs. CI overwrites this per deploy."
  type        = string
  default     = "bootstrap"
}

variable "desired_count" {
  description = "Fargate tasks behind the load balancer."
  type        = number
  default     = 1
}


variable "github_oidc_subject" {
  description = <<-DESC
    The `sub` claim in the token GitHub Actions presents, and the only thing the
    deploy role trusts. This repository has immutable subject claims enabled, so
    the prefix names the owner and the repository by numeric ID rather than by
    name: renaming or transferring either cannot hand the role to someone else.
    Read the prefix for a repository with

      gh api /repos/OWNER/REPO/actions/oidc/customization/sub

    and keep the `:ref:refs/heads/main` suffix, which is what restricts deploys
    to the default branch.
  DESC
  type        = string
  default     = "repo:mariogemoll@627106/sift@1383523523:ref:refs/heads/main"
}

variable "passphrase_hash" {
  description = <<-DESC
    scrypt hash of the passphrase that opens the web interface, as printed by
    `sift passphrase` — not the passphrase itself. Required: with no hash the
    service admits nobody, so this is the one variable without a default.
  DESC
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.passphrase_hash, "scrypt$")
    error_message = "Expected the output of `sift passphrase`, which starts with scrypt$."
  }
}

variable "typesafe_api_key" {
  description = <<-DESC
    API key for TypeSafe. The deployed service judges papers with Jev, which
    needs it; there is no default, so a stack is never deployed judging with
    the fake asker by accident.
  DESC
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.typesafe_api_key)) > 0
    error_message = "Set typesafe_api_key in terraform.tfvars."
  }
}
