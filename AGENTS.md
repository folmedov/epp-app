# AGENTS.md — eepp

## Project Overview
ETL pipeline + web UI that tracks Chilean public sector job offers from **EEPP** (Empleos Públicos) and **TEEE** (Trabaja en el Estado).  
Ingests async, deduplicates cross-source, exposes via FastAPI + Jinja2 + HTMX.  
Deployed on Dokploy with cron workers for daily/monthly ingestion and email notifications.

## Sources of Truth
Before any change, consult these files (in order):

1. **`requirement.md`** — sprint scope, completion status, business rules
2. **`docs/sprints/`** — detailed implementation specs per sprint
3. **`architecture.md`** — system design, schema, fingerprint strategy, patterns

Do not duplicate or override rules already defined in those docs.

## Technical Defaults

| Concern | Convention |
|---------|-----------|
| Python | 3.11+, type hints required everywhere |
| DB | PostgreSQL + SQLAlchemy 2.0 **async** API (`AsyncSession`, `select()`) |
| Schemas | Pydantic v2 models for validation |
| HTTP | `httpx.AsyncClient` |
| DB driver | `asyncpg` |
| Logging | `logging.getLogger(__name__)`, never `print()` |
| Async | `asyncio.run()` for scripts, `async/await` throughout |
| SMTP | `aiosmtplib`, config via env vars (optional, graceful fallback) |
| Config | Pydantic `BaseSettings` in `src/core/config.py` |
| Migrations | Alembic in `migrations/` |

## Project Structure

```
src/
├── core/           # config.py, schemas.py
├── database/       # session.py, models.py, repository.py
├── ingestion/      # base.py, eepp_client.py, teee_client.py
├── notifications/  # email.py, matcher.py, templates/
├── processing/     # transformers.py
└── web/            # app.py, routers/, queries.py, templates/, static/
scripts/            # ingest_all.py, load_teee.py, load_eepp.py,
                    # notify_new_offers.py, weekly_digest.py,
                    # close_stale_offers.py, cleanup_notification_queue.py
tests/              # pytest-asyncio tests
```

## Commands

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_notifications.py -v

# Lint check (ruff)
uv run ruff check .

# Lint with auto-fix
uv run ruff check --fix .

# Type check (if mypy or pyright added)
# uv run mypy src/

# Run web server locally
uv run uvicorn src.web.app:app --reload --port 8000

# Run ingestion (daily policy)
uv run python scripts/ingest_all.py --policy daily

# Run ingestion (dry-run, no DB writes)
uv run python scripts/ingest_all.py --policy daily --dry-run

# Run notifications only (dry-run)
uv run python scripts/notify_new_offers.py --dry-run

# Apply DB migrations
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"
```

## Workflow

### Docs-driven implementation
1. Read the relevant **sprint doc** in `docs/sprints/` for context
2. Read `requirement.md` for the current sprint status and business rules
3. Read `architecture.md` for design decisions and patterns
4. Check `tests/` for existing test patterns
5. Implement the change following existing conventions
6. Run `uv run ruff check .` before committing
7. Run `uv run pytest` to verify nothing breaks
8. Update `requirement.md` to mark items as `[x]` when completed

### Sprint docs format

Sprint docs in `docs/sprints/` capture **context + design decisions + acceptance criteria**, not implementation details:

| Section | Content |
|---------|---------|
| **Context** | Problem description, observed symptoms, what led to this sprint |
| **Design** | Rationale, trade-offs, architectural decisions. Code-level detail only if it must be followed strictly (e.g. a critical SQL constraint) |
| **Files changed** | Table listing which files are created/modified and a one-line summary per file |
| **Acceptance criteria** | Checkbox list of verifiable conditions that define "done" |

Keep the focus on *why* decisions were made, not *how* they are implemented in code. Detailed code will live in the actual source files and is subject to change during implementation.

### Notification system (known context)
- `scripts/notify_new_offers.py`: runs after ingestion, matches new offers vs subscriptions, sends emails
- Flow: `ingest_all.py` → `close_stale_offers.py` → `notify_new_offers.py`
- Matcher uses `unaccent ILIKE` on keywords vs title (SQL in `src/notifications/matcher.py`)
- Only `state = 'postulacion'` offers trigger notifications (business rule 6.10)
- Queue rows stuck in `pending` indicate SMTP failures (no retry logic, known bug)
- Email config: `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` in env

## Coding Style
- Follow existing file conventions (import ordering, naming, formatting)
- Use `str()` for UUID serialization in SQL params (not `.hex`)
- Use `from __future__ import annotations` in all `.py` files
- Prefer small focused functions over large monoliths
- SQL queries as `text()` constants at module level (see existing files)
- Keep templates minimal — no JS build step (HTMX + Jinja2 only)

## Constraints
- Do not add dependencies beyond what's in `pyproject.toml` without asking
- Do not add features not defined in the current requirements
- Do not commit secrets or `.env` files
- Do not modify `requirement.md` or `architecture.md` without explicit task scope
- Prefer small iterative changes over large refactors
- Never assume undocumented API fields or contracts
