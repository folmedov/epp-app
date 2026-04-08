# Sprint 6.8 — Hook `notify_new_offers.py` into `ingest_all.py`

## Context

`notify_new_offers.py` (Sprint 6.6) is a standalone script. To be useful in
production it must run automatically after every ingestion cycle, not
manually. This sprint wires it into `ingest_all.py` as a non-fatal post-step,
immediately after `close_stale_offers.py`.

## Design

### Placement in the pipeline

The call order at the end of `ingest_all.py` (non-initial runs) becomes:

```
loaders (TEEE → EEPP)
  └─ [on failure] → sys.exit(1)         ← unchanged
close_stale_offers.py  (non-fatal)      ← unchanged
notify_new_offers.py   (non-fatal)      ← NEW
```

`notify_new_offers.py` runs **after** `close_stale_offers.py` so that
`is_active` flags are already updated before the notifier queries
`WHERE is_active = TRUE AND notified_at IS NULL`.

### Non-fatal behavior

A failure in `notify_new_offers.py` (exit code ≠ 0) must never prevent
`ingest_all.py` from exiting 0. It logs a warning and continues, matching the
existing pattern for `close_stale_offers.py`. The overall exit code of
`ingest_all.py` is still 1 only if a loader (TEEE or EEPP) fails.

### `--dry-run` forwarding

`notify_new_offers.py` already supports `--dry-run`. `ingest_all.py` passes
`common` (which holds `--dry-run` if the flag was given) so dry-run mode is
propagated automatically — no changes to the args parsing logic.

### `--initial` guard

`notify_new_offers.py` is only called when **not** in `--initial` mode,
consistent with `close_stale_offers.py`. An initial load should not trigger
notifications (it would flood every subscriber with thousands of emails).

## Implementation

### `scripts/ingest_all.py` — single addition

After the existing `close_stale_offers.py` block, add:

```python
        rc_notify = _run_loader(
            "notify",
            _SCRIPTS_DIR / "notify_new_offers.py",
            common,  # forwards --dry-run if present
        )
        if rc_notify != 0:
            LOGGER.warning("notify_new_offers completed with errors (non-fatal). Review logs.")
```

The full `if not args.initial:` block after the change:

```python
    if not args.initial:
        rc_stale = _run_loader(
            "close_stale",
            _SCRIPTS_DIR / "close_stale_offers.py",
            common,
        )
        if rc_stale != 0:
            LOGGER.warning("close_stale_offers completed with errors (non-fatal). Review logs.")

        rc_notify = _run_loader(
            "notify",
            _SCRIPTS_DIR / "notify_new_offers.py",
            common,
        )
        if rc_notify != 0:
            LOGGER.warning("notify_new_offers completed with errors (non-fatal). Review logs.")
```

## Files changed

| File | Change |
|---|---|
| `scripts/ingest_all.py` | Add `notify_new_offers.py` call after `close_stale_offers.py` |

## Acceptance criteria

- [ ] After a successful ingestion run, `notify_new_offers.py` is called automatically.
- [ ] A failure in `notify_new_offers.py` (exit code ≠ 0) does not cause `ingest_all.py` to exit 1.
- [ ] `--dry-run` passed to `ingest_all.py` is forwarded to `notify_new_offers.py`.
- [ ] In `--initial` mode, `notify_new_offers.py` is **not** called.
- [ ] `notify_new_offers.py` runs after `close_stale_offers.py`, not before.
