"""Unified ingestion entrypoint. Runs EEPP then TEEE loaders sequentially.

Usage:
    PYTHONPATH=. python scripts/ingest_all.py [--initial] [--dry-run]

Behavior:
  - Runs load_eepp.py then load_teee.py with ``--state all`` (the default for
    both loaders).
  - ``--initial`` is forwarded to both loaders for a full historical load.
  - ``--dry-run`` is forwarded to both loaders.
  - The second loader always runs even if the first fails; all failures are
    reported together.

Exit codes:
    0   All loaders completed successfully.
    1   One or more loaders failed.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
LOGGER = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).parent


def _run_loader(name: str, script: Path, extra_args: list[str]) -> int:
    """Run a loader script as a subprocess and return its exit code."""
    cmd = [sys.executable, str(script)] + extra_args
    LOGGER.info("Starting loader: %s", name)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        LOGGER.error("Loader %s failed with exit code %d", name, result.returncode)
    else:
        LOGGER.info("Loader %s completed successfully", name)
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all ingestion loaders (EEPP + TEEE) sequentially.",
    )
    parser.add_argument(
        "--initial",
        action="store_true",
        help=(
            "Pass --initial to both loaders: full historical load in "
            "lifecycle order with always-overwrite semantics."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Pass --dry-run to both loaders (upsert but rollback).",
    )
    args = parser.parse_args()

    extra: list[str] = []
    if args.initial:
        extra.append("--initial")
    if args.dry_run:
        extra.append("--dry-run")

    loaders: list[tuple[str, Path]] = [
        ("EEPP", _SCRIPTS_DIR / "load_eepp.py"),
        ("TEEE", _SCRIPTS_DIR / "load_teee.py"),
    ]

    failed: list[str] = []
    for name, script in loaders:
        rc = _run_loader(name, script, extra)
        if rc != 0:
            failed.append(name)

    if failed:
        LOGGER.error("Ingestion finished with failures: %s", ", ".join(failed))
        sys.exit(1)

    LOGGER.info("All loaders completed successfully.")


if __name__ == "__main__":
    main()
