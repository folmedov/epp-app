"""Report duplicate TEEE offers by `fingerprint`.

Fetches offers for a given `Estado` (default: `postulacion`), groups them by
`fingerprint`, and emits a report for groups with more than one member.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/report_teee_duplicates.py --state postulacion --out duplicates.json

The output file (JSON) contains an array of groups; each group has the
`fingerprint`, `count`, and a `samples` list with a few representative
entries containing `external_id`, `title`, `institution`, `url`, and
`_elastic_id` when available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from src.ingestion.teee_client import TEEEClient


def _summarise_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    raw = entry.get("raw_data", {}) or {}
    return {
        "external_id": entry.get("external_id"),
        "external_id_generated": entry.get("external_id_generated"),
        "title": entry.get("title"),
        "institution": entry.get("institution"),
        "url": entry.get("url"),
        "ministry": entry.get("ministry"),
        "start_date": entry.get("start_date"),
        "close_date": entry.get("close_date"),
        "conv_type": entry.get("conv_type"),
        "_elastic_id": raw.get("_elastic_id"),
    }


async def _run(state: str, out: Path | None, sample: int, limit: int | None) -> int:
    client = TEEEClient()
    if state == "all":
        results = await client.fetch_all()
    else:
        # call the public fetch_{state} where possible
        if state == "postulacion":
            results = await client.fetch_postulacion()
        elif state == "evaluacion":
            results = await client.fetch_evaluacion()
        elif state in ("finalizadas", "finalizada", "finalizado"):
            results = await client.fetch_finalizado()
        else:
            results = await client._fetch_state(state)

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        fp = r.get("fingerprint") or ""
        groups[fp].append(r)

    dup_groups = [(fp, members) for fp, members in groups.items() if len(members) > 1]
    dup_groups.sort(key=lambda t: len(t[1]), reverse=True)

    report = []
    for fp, members in dup_groups[:limit] if limit else dup_groups:
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
            json.dump({"summary": summary, "groups": report}, fh, ensure_ascii=False, indent=2)

    # Print concise terminal summary and top groups
    print(f"Fetched {len(results)} offers for state={state}")
    print(f"Found {len(dup_groups)} fingerprint groups with >1 member; total duplicated offers: {summary['total_duplicated_offers']}")
    print()
    top_n = report[:10]
    for g in top_n:
        print(f"fingerprint={g['fingerprint']} count={g['count']}")
        for s in g["samples"]:
            print("  - ", s)
        print()

    if out:
        print(f"Wrote duplicate report to {out}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Report duplicated TEEE offers by fingerprint")
    parser.add_argument("--state", type=str, default="postulacion", help="Estado to fetch: postulacion,evaluacion,finalizadas,all")
    parser.add_argument("--out", type=Path, help="Write JSON report to file")
    parser.add_argument("--sample", type=int, default=3, help="Number of sample entries per group")
    parser.add_argument("--limit", type=int, help="Limit number of groups to include in report")
    args = parser.parse_args()

    return asyncio.run(_run(args.state, args.out, args.sample, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
