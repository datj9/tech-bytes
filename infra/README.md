# Infra — AWS CDK (optional advanced path)

The default Tech Bytes deploy path is GitHub Pages (`.github/workflows/digest.yml`) —
no AWS required. This CDK stack is the **optional** advanced path: CloudFront +
Route53 + Lambda + SES for higher throughput, custom domains, and email digests.

## Prerequisites

- An AWS account with a Route53-managed domain (the free Pages path doesn't need this).
- `aws-cli` configured with credentials.
- Node.js 22+ and pnpm.

## Required CDK context

The stack is fully parameterized — no hardcoded domain or repo. Pass these via
`-c key=value` (or set them in `cdk.json` context):

| Key                | Example                          | Purpose                                  |
|--------------------|----------------------------------|------------------------------------------|
| `domain.name`      | `bytes.example.com`              | CloudFront distribution + ACM cert        |
| `hosted.zone.name` | `example.com`                    | Existing Route53 hosted zone to look up   |
| `github.repo`      | `youruser/tech-bytes`            | GitHub OIDC subject restriction           |

Optional:

| Key          | Default        | Purpose                                  |
|--------------|----------------|------------------------------------------|
| `ssm.prefix` | `/tech-bytes`  | SSM parameter namespace for secrets      |

## Deploy

```bash
cd infra
pnpm install
npx cdk deploy \
  -c domain.name=bytes.example.com \
  -c hosted.zone.name=example.com \
  -c github.repo=youruser/tech-bytes \
  --require-approval never
```

Outputs you'll need:

- `GitHubActionsRoleArn` → set as `AWS_ROLE_ARN` repo secret (used by `deploy-aws.yml`).
- `BucketName` → data bucket name (Lambdas write here).
- `SiteUrl` → your deployed URL.

## Set SSM secrets

```bash
aws ssm put-parameter --name /tech-bytes/openai-api-key --value "sk-..." \
  --type SecureString --overwrite
aws ssm put-parameter --name /tech-bytes/github-token --value "ghp_..." \
  --type SecureString --overwrite
aws ssm put-parameter --name /tech-bytes/subscribers --value "you@example.com" \
  --type SecureString --overwrite
```

## Useful commands

* `pnpm exec cdk synth`  — emit the CloudFormation template (no deploy)
* `pnpm exec cdk diff`   — compare deployed stack with current state
* `pnpm exec cdk deploy` — deploy
