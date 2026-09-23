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

## Tearing it down

```sh
terraform destroy
```

The database has `skip_final_snapshot`, the buckets `force_destroy`, and the ECR
repository `force_delete`, so nothing survives to bill you. The state bucket is
not managed by Terraform and stays behind; it costs nothing.
