# Sprint 3.1 — Database refactor: `job_offer_sources`

## Objective

Introduce a per-source table to persist raw payloads and ingestion metadata so the canonical `job_offers` table contains only normalized fields used by the UI and queries.

## Scope

- Add a new ORM model `JobOfferSource` (table `job_offer_sources`).
- Provide a safe backfill/migration script that moves existing `job_offers.raw_data` into `job_offer_sources`.
- Ensure appropriate indexes and constraints: unique(`source`, `external_id`) and index on `job_offer_id`.

## Exclusions

- This sprint does not change the canonical `job_offers` fields used by the web UI except to remove or rename `raw_data` after backfill (drop/rename is optional and scheduled after verification).

## Expected output

- `JobOfferSource` model added to `src/database/models.py` (or new module imported there).
- Migration/backfill script `scripts/migrate_raw_to_sources.py` with `--dry-run` and batching support.
- Documentation of migration steps and rollback plan.

## Model sketch

```py
class JobOfferSource(Base):
    __tablename__ = "job_offer_sources"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_offer_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job_offers.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    original_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("source", "external_id"),)
```

## Migration / Backfill plan

1. Create the new table via `Base.metadata.create_all()` (or a migration tool).
2. Run a controlled backfill:

```sql
INSERT INTO job_offer_sources (job_offer_id, source, external_id, raw_data, original_state, ingested_at)
SELECT id, source, external_id, raw_data, state, created_at FROM job_offers WHERE raw_data IS NOT NULL;
```

Do the insert in batches (e.g. LIMIT/OFFSET or server-side cursor) to avoid long transactions and excessive WAL.

3. Validate row counts and sample rows.
4. Optionally rename or drop `job_offers.raw_data` after verification.

## Acceptance criteria

- All existing `raw_data` entries are present in `job_offer_sources` and associated via `job_offer_id`.
- `job_offer_sources` enforces unique `(source, external_id)`.
- Migration script supports `--dry-run`, logging and a safe commit mode.

## Rollback

- Keep original `raw_data` column until verified. To revert, use a reverse insert from `job_offer_sources` back into `job_offers.raw_data`.

## Operational notes

- Take a DB backup before running backfill.
- Consider running the backfill during low-traffic window.
