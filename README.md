# Tech Bytes

A self-hostable, pluggable daily tech digest — release updates, Hacker News
summaries, and GitHub trending, all summarized by the LLM of your choice and
published as a static site.

**Default path: GitHub Pages + GitHub Actions cron. Zero AWS required.**
OpenAI, Anthropic, or any local/OpenAI-compatible LLM (Ollama, LM Studio,
Groq, OpenRouter).

## 60-second quickstart (free path)

```bash
# 1. Fork/clone
git clone https://github.com/<you>/tech-bytes.git
cd tech-bytes

# 2. Configure sources + branding
cp config/techbytes.config.example.yml config/techbytes.config.yml
$EDITOR config/techbytes.config.yml

# 3. Set your LLM key
export OPENAI_API_KEY=sk-...          # or ANTHROPIC_API_KEY + LLM_PROVIDER=anthropic

# 4. Run the pipeline locally (writes data/*.json)
cd pipeline && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ..
python -m pipeline.run all

# 5. Build the site
cd site && npm install && npm run build
```

To publish on a schedule: enable GitHub Pages (Settings → Pages → Source:
GitHub Actions), set `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) as a repo
secret, and the included `digest.yml` workflow runs daily — fetches → commits
fresh `data/` → builds → deploys.

## What it does

Three digest sources, each configurable in `config/techbytes.config.yml`:

- **Release Radar** — latest releases for any GitHub-tracked projects you list.
- **HN Digest** — top Hacker News stories, summarized.
- **GitHub Trending** — weekly + monthly trending repos, summarized.
- **Email Digest** *(optional, AWS path only)* — weekly email via SES.

## Configuration

Everything you'll edit lives in **`config/techbytes.config.yml`** (see
`techbytes.config.example.yml` for a full demo):

```yaml
site:
  title: "Tech Bytes"
  tagline: "Daily developer digest"
  url: ""           # blank = relative paths (default); set for a custom domain
  accent: emerald   # tailwind color token

llm:
  provider: openai  # openai | anthropic | local
  model: ""         # blank = provider default; set to override
  base_url: ""      # local/OpenAI-compatible server (Ollama, Groq, OpenRouter, ...)

sources:
  release_radar:
    enabled: true
    categories:
      - label: Runtimes
        icon: "🚀"             # emoji lives in CONFIG now — pick any
        items:
          - { name: Node.js, repo: nodejs/node }
  hn_digest:   { enabled: true, top_n: 15 }
  gh_trending: { enabled: true, languages: [all] }
  email_digest: { enabled: false }
```

### Environment variables

| Variable             | Default     | Purpose                                                     |
|----------------------|-------------|-------------------------------------------------------------|
| `OPENAI_API_KEY`     | —           | Required if `llm.provider=openai`                           |
| `ANTHROPIC_API_KEY`  | —           | Required if `llm.provider=anthropic`                        |
| `LLM_API_KEY`        | —           | Optional for the local provider                             |
| `LLM_PROVIDER`       | from config | Overrides `llm.provider` at runtime                         |
| `LLM_MODEL`          | from config | Overrides `llm.model`                                       |
| `LLM_BASE_URL`       | from config | Overrides `llm.base_url`                                    |
| `STORAGE`            | `local`     | `local` (writes `data/`) or `s3` (AWS path)                 |
| `DATA_DIR`           | `../data`   | Where the local storage backend reads/writes                |
| `GITHUB_TOKEN`       | —           | Bumps GitHub API rate limit for trending/README fetches     |
| `TECHBYTES_CONFIG`   | —           | Explicit path to a config file                              |

## Local development

```bash
# Pipeline (Python)
cd pipeline && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest ruff
pytest                 # tests
ruff check .           # lint
python -m pipeline.run release_radar   # one source

# Site (Astro + Tailwind)
cd site
npm install
npm run dev            # http://localhost:4321
npm run build          # static build → site/dist/
```

## Deploy paths

### Free (default): GitHub Pages

1. Push to your repo.
2. Repo Settings → Pages → Source: **GitHub Actions**.
3. Repo Settings → Secrets → add `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`).
4. The `digest.yml` workflow runs daily (06:00 UTC), commits `data/`, builds,
   deploys.

The site URL will be `https://<you>.github.io/<repo>/`. Astro's `base` path is
auto-detected from `GITHUB_REPOSITORY`. Set `PUBLIC_SITE_URL` as a secret to
override.

### Advanced (optional): AWS CDK

CloudFront + Route53 + Lambda + SES for custom domains and email digests.
Requires a Route53-managed domain. See **[`infra/README.md`](infra/README.md)**.

## Project layout

```
config/           # Single user-facing config (sources + branding + llm choice)
pipeline/         # Python package: providers/, storage/, sources/, shared/
  providers/      # openai, anthropic, local — pluggable LLM backend
  storage/        # local_fs (default), s3 — pluggable storage backend
  run.py          # CLI: python -m pipeline.run [all|source]
site/             # Astro static site; reads config at build, reads data/*.json
infra/            # AWS CDK (optional advanced path)
data/             # Generated JSON (committed by the digest workflow)
.github/workflows/
  digest.yml      # Free path: cron → pipeline → commit data → build → Pages
  deploy-aws.yml  # Optional AWS path
  preview.yml     # PR build + pipeline tests + cdk synth
```

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs
at the repository.

## License

[MIT](LICENSE).
