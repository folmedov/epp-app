# Sprint 3.14 — Configure Periodic Ingestion

## Goal

Define and implement a sustainable ingestion policy that keeps the DB current
while avoiding unnecessary load on the EEPP and TEEE APIs.

---

## Background

After Sprint 3.13 the pipeline has a single entrypoint (`ingest_all.py`). By
default it runs both loaders with `--state all`, which includes TEEE's
`finalizadas` bucket (~40 000+ rows). Fetching that bucket on every run is
wasteful because **finalised offers are immutable**: once an offer transitions to
`finalizada` it does not change title, salary, dates, or state.

The EEPP API does not expose a `finalizadas` endpoint; its `--state all` already
covers only `postulacion` and `evaluacion`. The TEEE API exposes three separate
endpoints, so we can skip `finalizadas` selectively.

---

## Policy Design

### `daily` (default)

```
PYTHONPATH=. python scripts/ingest_all.py --policy daily
```

| Loader | States fetched            | Rationale                                  |
|--------|---------------------------|--------------------------------------------|
| EEPP   | `postulacion, evaluacion` | The only states EEPP exposes               |
| TEEE   | `postulacion, evaluacion` | Active offers; `finalizadas` omitted       |

**Intent**: stay current on all active offers. Catches new postulations and
state transitions (postulacion → evaluacion → finalizada for active rows).

### `monthly` / `quarterly` / `biannual` / `semiannual` — full sweeps

These policies all fetch `--state all` from both loaders (includes TEEE
`finalizadas`). They differ only in the intended cron schedule:

| Policy       | Command                                            | Intended cadence |
|--------------|----------------------------------------------------|------------------|
| `monthly`    | `python scripts/ingest_all.py --policy monthly`    | Every month      |
| `quarterly`  | `python scripts/ingest_all.py --policy quarterly`  | Every 3 months   |
| `biannual`   | `python scripts/ingest_all.py --policy biannual`   | Every 4 months   |
| `semiannual` | `python scripts/ingest_all.py --policy semiannual` | Every 6 months   |

**Intent**: catch stragglers — offers that were missed during daily runs due to
network errors, API pagination gaps, or late state transitions.

Having separate policy names (rather than a single `--full-sweep` flag) lets
cron configurations be self-documenting: you can read the policy name in the
schedule and know the intended frequency without inspecting extra comments.

### `--initial`

```
PYTHONPATH=. python scripts/ingest_all.py --initial
```

Full historical load. Overrides the policy flag. Both loaders run with their
own `--initial` flag (lifecycle order, always-overwrite semantics). Used for
first-time DB population or after a truncate+reload.

---

## Implementation

All policy logic lives in `scripts/ingest_all.py`. No changes were needed to
the individual loaders.

| Policy  | EEPP extra args | TEEE extra args                      |
|---------|-----------------|--------------------------------------|
| `daily` | *(none)*        | `--state postulacion,evaluacion`     |
| `monthly`| *(none)*       | *(none)* (defaults to `--state all`) |

---

## Work Items

- [x] Add `_POLICIES` dict to `ingest_all.py` mapping policy name → per-loader args
- [x] Add `--policy daily|monthly` CLI flag (default: `daily`)
- [x] `--initial` overrides policy; logs that policy is ignored
- [x] Loader invocation logs include the extra args for traceability
- [x] Update requirement.md 3.13, 3.14, 3.16 entries

---

## Acceptance Criteria

1. `python scripts/ingest_all.py` (no flags) runs the `daily` policy.
2. `python scripts/ingest_all.py --policy daily` passes `--state postulacion,evaluacion` to TEEE and no extra state args to EEPP.
3. `python scripts/ingest_all.py --policy monthly` passes `--state all` (default) to both loaders.
4. `python scripts/ingest_all.py --initial` invokes both loaders with `--initial` and logs "policy ignored".
5. `--dry-run` is compatible with all policies.
6. Exit code `0` when all loaders succeed; `1` when any fails.

---

## Recommended Cron Schedule (implemented in Sprint 4.1)

| Frequency    | Command                                                           |
|--------------|-------------------------------------------------------------------|
| Daily        | `PYTHONPATH=. python scripts/ingest_all.py --policy daily`        |
| Monthly      | `PYTHONPATH=. python scripts/ingest_all.py --policy monthly`      |
| Quarterly    | `PYTHONPATH=. python scripts/ingest_all.py --policy quarterly`    |
| Every 4 mo.  | `PYTHONPATH=. python scripts/ingest_all.py --policy biannual`     |
| Every 6 mo.  | `PYTHONPATH=. python scripts/ingest_all.py --policy semiannual`   |

Only one full-sweep policy should be active in the cron schedule at a time.
Choose the cadence based on how often you want to reconcile `finalizadas`.
