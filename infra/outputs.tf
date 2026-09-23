output "site_url" {
  description = "Where the application answers."
  value       = var.domain_name == "" ? "https://${aws_cloudfront_distribution.main.domain_name}" : "https://${var.domain_name}"
}

output "cloudfront_domain" {
  description = "Distribution hostname, the CNAME target for a custom domain."
  value       = aws_cloudfront_distribution.main.domain_name
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "site_bucket" {
  value = aws_s3_bucket.site.id
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "service_name" {
  value = aws_ecs_service.api.name
}

output "task_definition_family" {
  value = aws_ecs_task_definition.api.family
}

output "service_subnets" {
  description = "Subnets the migration task runs in."
  value       = aws_subnet.public[*].id
}

output "service_security_group" {
  value = aws_security_group.service.id
}

output "deploy_role_arn" {
  description = "Role GitHub Actions assumes. Set as AWS_DEPLOY_ROLE in the repo."
  value       = aws_iam_role.github_deploy.arn
}

output "database_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "certificate_validation_record" {
  description = "CNAME to create in Cloudflare, DNS-only, to validate the certificate."
  value = var.domain_name == "" ? null : {
    name  = one(aws_acm_certificate.site[0].domain_validation_options).resource_record_name
    type  = one(aws_acm_certificate.site[0].domain_validation_options).resource_record_type
    value = one(aws_acm_certificate.site[0].domain_validation_options).resource_record_value
  }
}
