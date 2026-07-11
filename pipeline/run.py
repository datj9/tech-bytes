"""Framework-agnostic CLI entrypoint for the Tech Bytes pipeline.

Usage:
    python -m pipeline.run                 # run all enabled sources
    python -m pipeline.run all             # same
    python -m pipeline.run release_radar   # run one source
    python -m pipeline.run hn_digest
    python -m pipeline.run gh_trending
    python -m pipeline.run email_digest

Sources disabled in config (sources.<name>.enabled: false) are skipped when
running `all`. Naming an disabled source explicitly still runs it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from pipeline.email_digest import handler as email_digest_handler
from pipeline.gh_trending import handler as gh_trending_handler
from pipeline.hn_digest import handler as hn_digest_handler
from pipeline.release_radar import handler as release_radar_handler
from pipeline.shared.config import is_source_enabled, load_config
from pipeline.shared.utils import setup_logging

SOURCES: dict[str, Callable[[], dict]] = {
    "release_radar": release_radar_handler.handler,
    "hn_digest": hn_digest_handler.handler,
    "gh_trending": gh_trending_handler.handler,
    "email_digest": email_digest_handler.handler,
}


def run(source: str) -> int:
    """Run a single source by name. Returns process exit code."""
    if source not in SOURCES:
        print(f"Unknown source: {source!r}", file=sys.stderr)
        print(f"Valid sources: {', '.join(sorted(SOURCES))}", file=sys.stderr)
        return 2

    handler_fn = SOURCES[source]
    try:
        result = handler_fn()
    except Exception as exc:
        print(f"Source {source!r} failed: {exc}", file=sys.stderr)
        return 1

    print(f"[{source}] OK — {len(result)} top-level keys")
    return 0


def run_all() -> int:
    """Run every enabled source in config. Returns 0 if all succeeded."""
    config = load_config()
    exit_code = 0
    for name in SOURCES:
        if not is_source_enabled(config, name):
            print(f"[{name}] disabled in config — skipping")
            continue
        rc = run(name)
        if rc != 0:
            exit_code = rc
    return exit_code


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] == "all":
        return run_all()

    if args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    return run(args[0])


if __name__ == "__main__":
    sys.exit(main())
