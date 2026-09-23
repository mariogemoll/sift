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


variable "github_repo" {
  description = "owner/name of the repository allowed to deploy."
  type        = string
  default     = "mariogemoll/sift"
}
