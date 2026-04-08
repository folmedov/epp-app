"""Unified ingestion entrypoint. Runs EEPP then TEEE loaders sequentially.

Usage:
    PYTHONPATH=. python scripts/ingest_all.py [--policy POLICY] [--initial] [--dry-run]

Policies
--------
daily (default)
    Fetch active states only (postulacion + evaluacion).
    Avoids re-querying ``finalizadas``; finalised offers do not change.
    Intended for daily cron runs.

monthly
    Fetch all states including ``finalizadas``.
    Catches stragglers and any offer whose state changed outside the normal
    lifecycle (e.g. reopened competition).
    Intended for a monthly catch-up run.

``--initial`` overrides the policy; both loaders are invoked with their own
``--initial`` flag for a full historical load in lifecycle order.

Behavior:
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

# Per-policy extra args for each loader.
# EEPP only surfaces postulacion + evaluacion so --state all is always correct.
# TEEE has finalizadas; we skip it on daily runs.
# All policies that include a full sweep (monthly / quarterly / biannual / semiannual)
# pass no extra args to either loader, which defaults both to --state all.
_POLICIES: dict[str, dict[str, list[str]]] = {
    "daily": {
        "eepp": [],                                         # defaults to --state all (postulacion + evaluacion)
        "teee": ["--state", "postulacion,evaluacion"],      # skip finalizadas
    },
    "monthly": {
        "eepp": [],                                         # defaults to --state all
        "teee": [],                                         # defaults to --state all (includes finalizadas)
    },
    "quarterly": {
        "eepp": [],                                         # full sweep, every 3 months
        "teee": [],
    },
    "biannual": {
        "eepp": [],                                         # full sweep, every 4 months
        "teee": [],
    },
    "semiannual": {
        "eepp": [],                                         # full sweep, every 6 months
        "teee": [],
    },
}


def _run_loader(name: str, script: Path, extra_args: list[str]) -> int:
    """Run a loader script as a subprocess and return its exit code."""
    cmd = [sys.executable, str(script)] + extra_args
    LOGGER.info("Starting loader: %s  args=%s", name, extra_args)
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
        "--policy",
        choices=list(_POLICIES),
        default="daily",
        help=(
            "Ingestion policy. "
            "'daily': active states only (postulacion + evaluacion). "
            "'monthly': full sweep including finalizadas (every month). "
            "'quarterly': full sweep every 3 months. "
            "'biannual': full sweep every 4 months. "
            "'semiannual': full sweep every 6 months. "
            "Default: daily."
        ),
    )
    parser.add_argument(
        "--initial",
        action="store_true",
        help=(
            "Full historical load: pass --initial to both loaders "
            "(lifecycle order, always-overwrite semantics). Overrides --policy."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Pass --dry-run to both loaders (upsert but rollback).",
    )
    args = parser.parse_args()

    common: list[str] = []
    if args.dry_run:
        common.append("--dry-run")

    if args.initial:
        # --initial overrides policy; both loaders handle their own state order.
        # TEEE runs first so that TEEE canonical rows are created before EEPP
        # enrichment; this ensures TEEE is the authoritative source for shared offers.
        LOGGER.info("Running in INITIAL mode (policy ignored) — TEEE first, EEPP second")
        loaders: list[tuple[str, Path, list[str]]] = [
            ("TEEE", _SCRIPTS_DIR / "load_teee.py", ["--initial"] + common),
            ("EEPP", _SCRIPTS_DIR / "load_eepp.py", ["--initial"] + common),
        ]
    else:
        policy = _POLICIES[args.policy]
        LOGGER.info("Running with policy=%s — TEEE first, EEPP second", args.policy)
        loaders = [
            ("TEEE", _SCRIPTS_DIR / "load_teee.py", policy["teee"] + common),
            ("EEPP", _SCRIPTS_DIR / "load_eepp.py", policy["eepp"] + common),
        ]

    failed: list[str] = []
    for name, script, extra in loaders:
        rc = _run_loader(name, script, extra)
        if rc != 0:
            failed.append(name)

    if failed:
        LOGGER.error("Ingestion finished with failures: %s", ", ".join(failed))
        sys.exit(1)

    LOGGER.info("All loaders completed successfully.")

    # After every non-initial run, close stale offers (non-fatal).
    if not args.initial:
        rc_stale = _run_loader(
            "close_stale",
            _SCRIPTS_DIR / "close_stale_offers.py",
            common,  # forwards --dry-run if present
        )
        if rc_stale != 0:
            LOGGER.warning("close_stale_offers completed with errors (non-fatal). Review logs.")

        rc_notify = _run_loader(
            "notify",
            _SCRIPTS_DIR / "notify_new_offers.py",
            common,  # forwards --dry-run if present
        )
        if rc_notify != 0:
            LOGGER.warning("notify_new_offers completed with errors (non-fatal). Review logs.")


if __name__ == "__main__":
    main()
