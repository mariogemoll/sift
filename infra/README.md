# Deploying sift

The stack: a Fargate service behind an application load balancer, RDS Postgres,
the built SPA in S3, and CloudFront in front of both — `/api/*` to the load
balancer, everything else to the bucket. The browser therefore talks to one
origin in production exactly as it does against the Vite dev server.

Terraform owns everything except the state bucket, which cannot describe its
own storage; `bootstrap.sh` creates that.

## Shape

```
CloudFront ──▶ S3 bucket              the SPA, private, read via OAC
     └──/api/*─▶ ALB ─▶ Fargate task ─▶ RDS Postgres   private subnets
```

Three decisions worth knowing:

- **No NAT gateway.** Tasks sit in public subnets with public IPs and reach ECR,
  Secrets Manager and arXiv directly. A NAT gateway would add about $35/month to
  achieve the same thing. Reachability is controlled by security groups: the
  tasks accept traffic from the load balancer alone.
- **The load balancer accepts CloudFront only**, via the managed
  `com.amazonaws.global.cloudfront.origin-facing` prefix list, so its public
  hostname is not a way around the CDN.
- **No AWS keys in GitHub.** Actions assumes a role through OIDC, restricted to
  this repository's default branch.

## The passphrase

The web interface is guarded by one shared passphrase. Secrets Manager holds an
scrypt hash of it, never the phrase, and the application derives the key that
signs session cookies from that hash — so this is the only auth secret in the
stack, and changing it invalidates every session already handed out.

Mint a hash from the backend and put it in `terraform.tfvars`, which is
gitignored:

```sh
cd ../backend && sift passphrase     # prints SIFT_PASSPHRASE_HASH=scrypt$...
```

```hcl
# infra/terraform.tfvars
passphrase_hash = "scrypt$16384$8$1$...$..."
```

There is no default: a service with no hash admits nobody, so Terraform asks
for it rather than quietly deploying a stack that either locks you out or, worse,
lets everyone in.

To rotate, replace the value and apply, then force a new deployment — ECS reads
secrets when a task starts, so the running task keeps the old hash until it is
replaced:

```sh
terraform apply
aws ecs update-service --cluster sift --service sift --force-new-deployment
```

Everyone signed in with the old passphrase is signed out by that, including you.

## The model key

The deployed service judges papers with Jev (`SIFT_ASKER=typesafe` in the task
definition), which needs a TypeSafe API key. It lives in Secrets Manager next to
the passphrase hash and reaches the container as `TYPESAFE_API_KEY`:

```hcl
# infra/terraform.tfvars
typesafe_api_key = "..."
```

There is no default, for the same reason as the passphrase: a stack that
silently fell back to the offline fake would rank papers by noise. Rotating is
the same too: replace the value, `terraform apply`, and force a new deployment.

## First deployment

```sh
./bootstrap.sh                                   # state bucket, once per account
terraform init

terraform apply -target=aws_ecr_repository.api   # somewhere to push to

aws ecr get-login-password --region eu-west-2 \
  | docker login --username AWS --password-stdin "$(terraform output -raw ecr_repository_url | cut -d/ -f1)"
docker build -t "$(terraform output -raw ecr_repository_url):bootstrap" ../backend
docker push "$(terraform output -raw ecr_repository_url):bootstrap"

terraform apply                                  # about 10 minutes, RDS dominates
```

Then run the migrations once, the same way CI does on every deploy — see the
`Migrate the database` step in `.github/workflows/deploy.yml`.

## Wiring up CI

The workflow reads three repository variables:

```sh
gh variable set AWS_DEPLOY_ROLE     --body "$(terraform output -raw deploy_role_arn)"
gh variable set AWS_SITE_BUCKET     --body "$(terraform output -raw site_bucket)"
gh variable set AWS_DISTRIBUTION_ID --body "$(terraform output -raw cloudfront_distribution_id)"
```

The deploy role trusts exactly one `sub` claim from GitHub's job token, and this
repository has **immutable subject claims** enabled, so that claim names the
owner and the repository by numeric ID rather than by name — a rename or a
transfer cannot hand the role to whoever picks up the old name. Point
`github_oidc_subject` at the prefix the repository actually uses:

```sh
gh api /repos/OWNER/REPO/actions/oidc/customization/sub
```

Get this wrong and every deploy stops at its first step, after two minutes of
retries, with `Not authorized to perform sts:AssumeRoleWithWebIdentity` — which
says nothing about which claim failed to match.

After that, deploy from the Actions tab, or:

```sh
gh workflow run Deploy
```

The workflow builds the image, registers a task definition revision, runs
migrations as a one-off task, rolls the service, and publishes the site. It is
never triggered by a push: CI reports whether `main` is deployable, and this
decides to deploy it. The role trusts `main` only, so a dispatch from another
branch is refused by AWS rather than by the workflow.

## A custom domain

DNS for the domain lives in Cloudflare, so the certificate is validated by hand.
Two applies, because CloudFront will not accept a certificate that is not yet
issued:

```sh
terraform apply -target=aws_acm_certificate.site -var 'domain_name=sift.example.com'
terraform output certificate_validation_record
```

Create that CNAME in Cloudflare **DNS-only (grey cloud)**, then:

```sh
terraform apply -var 'domain_name=sift.example.com'
```

which waits for validation and attaches the alias. Finally point the hostname at
the distribution, also grey-cloud:

```
sift  CNAME  <terraform output -raw cloudfront_domain>
```

Grey cloud matters. Proxying puts Cloudflare in front of CloudFront: TLS
terminates twice, two CDNs cache the same objects, and origin errors arrive
dressed as Cloudflare error pages.

## Changing the container definition

The task definition carries `ignore_changes = [container_definitions]` so that
Terraform does not fight CI over the image tag. The cost is that editing the
environment or the secrets of a container — adding one, renaming one — produces
no plan. Force a fresh revision from the configuration, then deploy so the
service picks it up:

```sh
terraform apply -replace=aws_ecs_task_definition.api
gh workflow run Deploy
```

The workflow reads the family's latest revision, so it builds on the one
Terraform just registered.

## Tearing it down

```sh
terraform destroy
```

The database has `skip_final_snapshot`, the buckets `force_destroy`, and the ECR
repository `force_delete`, so nothing survives to bill you. The state bucket is
not managed by Terraform and stays behind; it costs nothing.
