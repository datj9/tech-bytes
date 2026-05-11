"""Run any Tech Bytes handler locally.

Usage:
    python -m release_radar.handler
    python -m hn_digest.handler
    python -m gh_trending.handler

Or run this file directly to see usage instructions:
    python __main__.py
"""

import sys


def main() -> None:
    print("Tech Bytes Lambda Handlers")
    print("=" * 40)
    print()
    print("Run individual handlers with:")
    print("  python -m release_radar.handler")
    print("  python -m hn_digest.handler")
    print("  python -m gh_trending.handler")
    print()
    print("Make sure you have a .env file with:")
    print("  OPENAI_API_KEY=sk-...")
    print("  DATA_BUCKET_NAME=your-bucket  (optional for local runs)")
    sys.exit(0)


if __name__ == "__main__":
    main()
