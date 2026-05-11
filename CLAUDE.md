# Tech Bytes — bytes.finaldivision.com

Daily tech digest: release updates, Hacker News summaries, GitHub trending.

## Architecture

- `site/` — Astro static site (SSG), deployed to S3 + CloudFront
- `lambdas/` — Python Lambda functions that fetch + summarize content via OpenAI
- `infra/` — AWS CDK (TypeScript) for all cloud resources
- `data/` — Generated JSON files (local dev only, S3 in prod)

## AWS

- Profile: `super-personal`
- Domain: `bytes.finaldivision.com` (hosted zone: `finaldivision.com`)
- Deploy: `cd infra && npx cdk deploy --profile super-personal`

## Lambdas

Three functions, each triggered daily by EventBridge:
1. `release_radar` — fetches version updates for tracked technologies
2. `hn_digest` — summarizes top Hacker News stories
3. `gh_trending` — summarizes GitHub trending repos (weekly + monthly)

All use OpenAI API for summarization. Output goes to S3 as JSON, consumed by Astro at build time.

## Auto-rebuild

After each Lambda writes new data to S3, it triggers a GitHub Actions `workflow_dispatch`
on `deploy.yml` to rebuild and redeploy the site with fresh data. This requires a GitHub
Personal Access Token (PAT) with `actions:write` scope stored in SSM.

The existing `/tech-bytes/github-token` SSM parameter is set to `PLACEHOLDER`. To enable
the auto-rebuild trigger, replace it with a real PAT:

```bash
aws ssm put-parameter --name /tech-bytes/github-token --value "ghp_..." --type SecureString --overwrite --profile super-personal
```

The token needs the `actions:write` scope on the `datj9/tech-bytes` repository.

## Dev commands

```bash
# Site
cd site && npm install && npm run dev

# Lambda local test
cd lambdas && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m release_radar.handler

# Deploy
cd infra && npm install && npx cdk deploy --profile super-personal
```
