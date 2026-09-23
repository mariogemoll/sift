# The key for TypeSafe, whose model Jev answers the questions papers are judged
# by. Keep it in terraform.tfvars; the task reads it from here at start.
resource "aws_secretsmanager_secret" "typesafe_api_key" {
  name                    = "${var.name}/typesafe-api-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "typesafe_api_key" {
  secret_id     = aws_secretsmanager_secret.typesafe_api_key.id
  secret_string = var.typesafe_api_key
}
