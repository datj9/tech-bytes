# Tech Bytes

Self-hostable daily tech digest: release updates, Hacker News summaries, GitHub
trending — summarized by a pluggable LLM and published as a static site.

## Architecture

- `site/` — Astro static site (SSG). Reads branding from `config/techbytes.config.yml`
  at build time and data from `data/*.json`.
- `pipeline/` — Python package: framework-agnostic digest sources. Run via
  `python -m pipeline.run [all|source]`. Pluggable LLM (`pipeline/providers/`) and
  pluggable storage (`pipeline/storage/`).
- `infra/` — AWS CDK (TypeScript) for the **optional** advanced path.
- `config/` — single user-facing config (`techbytes.config.yml` + full example).
- `data/` — Generated JSON files (committed by the digest workflow in the free path).
- `.github/workflows/` — `digest.yml` (Pages, free path), `deploy-aws.yml`
  (optional AWS path), `preview.yml` (PR checks).

## Deploy paths

- **Default (free):** GitHub Pages via `digest.yml`. Cron → run pipeline →
  commit `data/` → build → deploy Pages. No AWS required.
- **Optional:** AWS via `deploy-aws.yml` + CDK (CloudFront + Route53 + Lambda + SES).

## Dev commands

```bash
# Site
cd site && npm install && npm run dev

# Pipeline
cd pipeline && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pipeline.run all             # run all enabled sources

# Pipeline checks
cd pipeline && ruff check . && python -m pytest -q

# AWS path (optional) — requires domain.name/hosted.zone.name/github.repo context
cd infra && npm install
npx cdk deploy -c domain.name=... -c hosted.zone.name=... -c github.repo=owner/name
```

## Conventions

- **Config-driven.** Tracked sources, branding, and icons live in
  `config/techbytes.config.yml`, never in code.
- **Pluggable providers.** LLM and storage are interfaces under `pipeline/providers/`
  and `pipeline/storage/`. No provider-specific code in source handlers.
- **Lazy AWS.** `boto3` is imported only inside functions that need it; the free
  path never requires AWS deps.
- **No secrets in code.** Keys come from env vars (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, etc.) or SSM on the AWS path only.
