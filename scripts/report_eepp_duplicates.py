"""Report duplicate EEPP offers by `fingerprint`.

Fetches offers for a given state (default: `all`), groups them by
`fingerprint`, and emits a report for groups with more than one member.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/report_eepp_duplicates.py --state all --out duplicates.json

The output file (JSON) contains an array of groups; each group has the
`fingerprint`, `count`, and a `samples` list with representative entries
containing `external_id`, `source`, `title`, `institution`, `url`, and date
fields.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from src.ingestion.eepp_client import EEPPClient


def _summarise_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "external_id": entry.get("external_id"),
        "source": entry.get("source"),
        "state": entry.get("state"),
        "title": entry.get("title"),
        "institution": entry.get("institution"),
        "region": entry.get("region"),
        "city": entry.get("city"),
        "url": entry.get("url"),
        "ministry": entry.get("ministry"),
        "start_date": str(entry.get("start_date")) if entry.get("start_date") else None,
        "close_date": str(entry.get("close_date")) if entry.get("close_date") else None,
        "content_fingerprint": entry.get("content_fingerprint"),
    }


async def _run(state: str, out: Path | None, sample: int, limit: int | None) -> int:
    client = EEPPClient()

    if state == "all":
        results = await client.fetch_all()
    elif state == "postulacion":
        results = await client.fetch_postulacion()
    elif state == "evaluacion":
        results = await client.fetch_evaluacion()
    else:
        print(f"Unknown state {state!r}. Valid values: postulacion, evaluacion, all")
        return 1

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        fp = r.get("fingerprint") or ""
        groups[fp].append(r)

    dup_groups = [(fp, members) for fp, members in groups.items() if len(members) > 1]
    dup_groups.sort(key=lambda t: len(t[1]), reverse=True)

    report = []
    for fp, members in (dup_groups[:limit] if limit else dup_groups):
        report.append(
            {
                "fingerprint": fp,
                "count": len(members),
                "samples": [_summarise_entry(m) for m in members[:sample]],
            }
        )

    summary = {
        "state": state,
        "total_offers_fetched": len(results),
        "duplicate_groups": len(dup_groups),
        "total_duplicated_offers": sum(len(m) for _, m in dup_groups),
    }

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "groups": report}, fh, ensure_ascii=False, indent=2, default=str)

    print(f"Fetched {len(results)} offers for state={state}")
    print(f"Found {len(dup_groups)} fingerprint groups with >1 member; total duplicated offers: {summary['total_duplicated_offers']}")
    print()
    for g in report[:10]:
        print(f"fingerprint={g['fingerprint']}  count={g['count']}")
        for s in g["samples"]:
            print("  -", s)
        print()

    if out:
        print(f"Wrote duplicate report to {out}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Report duplicated EEPP offers by fingerprint")
    parser.add_argument("--state", type=str, default="all", help="State to fetch: postulacion, evaluacion, all")
    parser.add_argument("--out", type=Path, help="Write JSON report to file")
    parser.add_argument("--sample", type=int, default=3, help="Number of sample entries per group")
    parser.add_argument("--limit", type=int, help="Limit number of groups to include in report")
    args = parser.parse_args()

    return asyncio.run(_run(args.state, args.out, args.sample, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
