# The one secret the interface is guarded by: an scrypt hash of the passphrase,
# never the passphrase itself. The application derives the session cookie's
# signing key from this value, so rotating the phrase invalidates every issued
# session without a second secret to keep in step.
#
# Mint it with `sift passphrase` and keep it in terraform.tfvars.
resource "aws_secretsmanager_secret" "passphrase_hash" {
  name                    = "${var.name}/passphrase-hash"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "passphrase_hash" {
  secret_id     = aws_secretsmanager_secret.passphrase_hash.id
  secret_string = var.passphrase_hash
}
