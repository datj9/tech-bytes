# Contributing to Tech Bytes

Thanks for considering a contribution! This project is a self-hostable digest
pipeline — most contributions fall into one of these buckets:

## Ways to help

- **Add a source** — new digest pipeline under `pipeline/<source>/handler.py`
  that calls `provider.summarize(...)` and `storage.write_json(...)`. Register
  it in `pipeline/run.py`.
- **Add an LLM provider** — new file under `pipeline/providers/` implementing
  the `LLMProvider` protocol; add it to the factory in
  `pipeline/providers/__init__.py`.
- **Add a storage backend** — new file under `pipeline/storage/` implementing
  the `Storage` protocol; add it to the factory in
  `pipeline/storage/__init__.py`.
- **Improve the site** — Astro components/pages under `site/src/`.
- **Fix a bug** — check [Issues](../../issues).

## Development setup

```bash
git clone https://github.com/<your-fork>/tech-bytes.git
cd tech-bytes

# Python pipeline
cd pipeline && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest ruff

# Site
cd ../site && npm install
```

## Before opening a PR

All of these must pass:

```bash
# Python
cd pipeline
ruff check .
python -m pytest -q

# Site
cd ../site
npm run build
```

The `preview.yml` workflow runs all three on every PR — green there is green
here.

## Conventions

- **Config-driven.** Hardcoded lists belong in `config/techbytes.config.yml`,
  not in code. Icons live in config (emoji literals), not in site code.
- **Pluggable.** LLM and storage are interfaces — no provider-specific code in
  the source handlers.
- **Lazy AWS.** `boto3` is imported only inside the functions that need it.
  The free path (local + GitHub Pages) must never require AWS deps.
- **No secrets in code.** Keys come from env vars or SSM (AWS path only).
- **Keep the diff small.** Match existing code style; the ruff config and
  TypeScript/tsconfig already enforce formatting.

## Commit messages

Conventional Commits style:

```
feat(release_radar): add support for monorepo release listings
fix(site): handle missing icon in archive view
chore(deps): bump openai
docs(readme): clarify provider config
```

## Filing issues

- Bugs: include the command you ran, what you expected, and what happened.
  The bug-report template captures the right pieces.
- Source/provider requests: describe the source and why it's useful.

## License

By contributing you agree your contributions are licensed under the project's
[MIT license](LICENSE).
