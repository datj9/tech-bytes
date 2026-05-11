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
