# The certificate only. DNS for the domain lives outside this account
# (Cloudflare), so validation records are added by hand — `terraform output
# certificate_validation_record` prints exactly what to create. See README.md.

resource "aws_acm_certificate" "site" {
  count    = var.domain_name == "" ? 0 : 1
  provider = aws.us_east_1

  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "site" {
  count    = var.domain_name == "" ? 0 : 1
  provider = aws.us_east_1

  certificate_arn = aws_acm_certificate.site[0].arn

  timeouts {
    create = "30m"
  }
}
