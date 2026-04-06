# Sprint 3.13 — Unified Ingestion Entrypoint

## Goal

Provide a single entry point `scripts/ingest_all.py` that runs both EEPP and
TEEE loaders sequentially with proper exit codes and structured logging. This is
the command that will be scheduled by the cron job in Sprint 3.15.

---

## Background

After Sprint 3.12 both loaders (`load_eepp.py` and `load_teee.py`) share the
same interface (`--state`, `--initial`, `--dry-run`). Running them independently
works, but an operational job needs a single command that:

- Runs both in a deterministic order.
- Reports success only if **both** succeed.
- Lets each loader run even if the other fails (so we don't lose TEEE data if
  EEPP times out).
- Forwards common flags (`--initial`, `--dry-run`) to both loaders.

---

## Design Decisions

### Subprocess vs in-process import

Each loader calls `logging.basicConfig(...)` and `asyncio.run(...)` at the top
level, which makes in-process reuse fragile (basicConfig is a no-op after the
first call; asyncio loops can't be nested). Using `subprocess.run` gives full
isolation: each loader owns its event loop, its log handlers, and its process
environment.

Log output from each subprocess passes through to the parent's stdout/stderr in
real time (no `capture_output`), so structured log lines from the individual
loaders are visible in the cron job output alongside the parent-level events.

### Execution order

EEPP runs first, TEEE second. Both share the same canonical `job_offers` table
via fingerprint / `cross_source_key` matching, so order only matters in the
`--initial` scenario where both are reloading from scratch. EEPP has two states
(`postulacion`, `evaluacion`); TEEE has three (`finalizadas`, `evaluacion`,
`postulacion`). The per-loader `--initial` order already guarantees
`postulacion` wins within each loader; cross-loader conflicts are handled by
`cross_source_key` deduplication.

### Continue-on-failure

The second loader always runs regardless of the first loader's exit code. This
ensures partial failures don't cause silent data gaps. Both failures are logged
and the parent exits with code `1` if any loader failed.

### `--state all` is the default

Neither `--state` nor `--batch` flags are exposed from `ingest_all.py`. The
individual loaders default to `--state all`, which is the correct behavior for
both periodic and initial runs. Operators needing finer control should invoke
the individual loaders directly.

---

## Work Items

- [x] Create `scripts/ingest_all.py`
  - Accepts `--initial` and `--dry-run`; forwards both to each loader.
  - Runs `load_eepp.py` then `load_teee.py` via `subprocess.run(sys.executable, ...)`.
  - Collects exit codes; exits `1` if any loader fails, `0` if all succeed.
  - Logs structured events at loader start, loader end, and final summary.

---

## Acceptance Criteria

1. `PYTHONPATH=. python scripts/ingest_all.py` completes with exit code `0`
   when both loaders succeed.
2. If either loader exits non-zero, `ingest_all.py` exits with code `1` and
   names the failing loader(s) in the error log.
3. The second loader runs even when the first fails.
4. `--initial` is forwarded to both loaders.
5. `--dry-run` is forwarded to both loaders.
6. No EEPP-specific or TEEE-specific logic lives in `ingest_all.py`.

---

## Usage

```bash
# Periodic update (default — state all, forward-only priority)
PYTHONPATH=. python scripts/ingest_all.py

# Initial / historical load
PYTHONPATH=. python scripts/ingest_all.py --initial

# Dry run
PYTHONPATH=. python scripts/ingest_all.py --dry-run
```
