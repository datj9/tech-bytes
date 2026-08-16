"""Run any Tech Bytes pipeline source locally.

Usage:
    python -m pipeline.run                 # run all enabled sources
    python -m pipeline.run release_radar   # run one source
    python -m pipeline.run hn_digest
    python -m pipeline.run gh_trending
    python -m pipeline.run email_digest

Configure via:
    cp config/techbytes.config.example.yml config/techbytes.config.yml
    export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY=... / LLM_PROVIDER=anthropic
    export STORAGE=local             # default; use s3 for the AWS path
"""
import sys

from pipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
