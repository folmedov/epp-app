# Sprint 6.5 — Keyword Matcher

## Context

With confirmed subscriptions now stored in the DB (Sprint 6.1) and the email
sender ready (Sprint 6.2), the notification pipeline needs a single function
that answers: *"for a given batch of new offers, which confirmed subscribers
match at least one of their keywords?"*

The matcher runs inside `scripts/notify_new_offers.py` (Sprint 6.6) after each
ingestion. Its output feeds the `notification_queue` inserts.

## Design

### Matching rule

A subscription matches an offer when **at least one keyword** in
`subscriptions.keywords` is found as a substring of `job_offers.title`,
case-insensitively and ignoring diacritics.

SQL predicate (per keyword, per offer):

```sql
unaccent(job_offers.title) ILIKE unaccent('%' || keyword || '%')
```

The `unaccent` PostgreSQL extension is already enabled (migration
`0010_enable_unaccent`). This is the same mechanism used by the web search in
`src/web/queries.py`.

### Single-query approach

Rather than looping over subscriptions in Python and issuing one query per
subscription, a single SQL query uses `unnest(s.keywords)` to expand the
keywords array inline, joins it to the offers batch via `LATERAL`, and groups
by `(subscription_id, job_offer_id)` to deduplicate multiple-keyword hits:

```sql
SELECT s.id        AS subscription_id,
       jo.id       AS job_offer_id
FROM   subscriptions s
CROSS  JOIN job_offers jo
JOIN   LATERAL unnest(s.keywords) AS kw ON TRUE
WHERE  jo.id = ANY(:offer_ids)
  AND  s.confirmed = TRUE
  AND  unaccent(jo.title) ILIKE unaccent('%' || kw || '%')
GROUP  BY s.id, jo.id;
```

Complexity: O(subscriptions × offers × avg_keywords). At the expected volume
(< 100 subscriptions, < 50 new offers per run) this is well within budget for
a synchronous cron step. No index needed.

### Public interface

Module: `src/notifications/matcher.py`

```python
async def find_matches(
    session: AsyncSession,
    offer_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    """Return matching offer IDs per confirmed subscription.

    Args:
        session: Active async SQLAlchemy session.
        offer_ids: IDs of new offers to match against (typically offers
            with notified_at IS NULL from the current ingestion run).

    Returns:
        A dict mapping subscription_id → [job_offer_id, ...] for every
        confirmed subscription that matches at least one keyword in at
        least one of the given offers. Subscriptions with no matches are
        absent from the dict. Returns {} immediately if offer_ids is empty.
    """
```

Callers iterate the returned dict to insert `notification_queue` rows and
build the list of `OfferRow` objects for `send_notification_email`.

## Implementation

### `src/notifications/matcher.py`

Key points:

- Uses `sqlalchemy.text()` for the raw SQL query — the `LATERAL unnest` +
  `ILIKE` combination is not expressible cleanly with the ORM.
- Binds `offer_ids` as a PostgreSQL UUID array using `bindparam` with
  `type_=ARRAY(PGUUID())` so asyncpg handles the conversion correctly.
- Returns early with `{}` when `offer_ids` is empty to avoid a no-op query.
- No logging of email addresses in output — only IDs are logged.

```python
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LOGGER = logging.getLogger(__name__)

_MATCH_SQL = text("""
    SELECT s.id        AS subscription_id,
           jo.id       AS job_offer_id
    FROM   subscriptions s
    CROSS  JOIN job_offers jo
    JOIN   LATERAL unnest(s.keywords) AS kw ON TRUE
    WHERE  jo.id = ANY(:offer_ids)
      AND  s.confirmed = TRUE
      AND  unaccent(jo.title) ILIKE unaccent('%' || kw || '%')
    GROUP  BY s.id, jo.id
""")


async def find_matches(
    session: AsyncSession,
    offer_ids: list[UUID],
) -> dict[UUID, list[UUID]]:
    if not offer_ids:
        return {}

    result = await session.execute(
        _MATCH_SQL,
        {"offer_ids": [str(oid) for oid in offer_ids]},
    )
    rows = result.fetchall()

    matches: dict[UUID, list[UUID]] = {}
    for row in rows:
        sub_id = UUID(str(row.subscription_id))
        offer_id = UUID(str(row.job_offer_id))
        matches.setdefault(sub_id, []).append(offer_id)

    LOGGER.info(
        "Matcher: %d offer(s) → %d subscription(s) matched",
        len(offer_ids),
        len(matches),
    )
    return matches
```

### `src/notifications/__init__.py`

No changes — already an empty package init.

## Files changed

| File | Change |
|---|---|
| `src/notifications/matcher.py` | New module — `find_matches()` function |

## Acceptance criteria

- [ ] `find_matches(session, [])` returns `{}` without executing a DB query.
- [ ] `find_matches` returns a dict mapping each matching confirmed subscription ID to the list of matching offer IDs.
- [ ] A subscription with no matching offers is absent from the result dict.
- [ ] Matching is case-insensitive and diacritic-insensitive (e.g. keyword `"informática"` matches title `"ANALISTA INFORMATICA"`).
- [ ] A subscription with multiple keywords matching the same offer appears only once per offer in the result (no duplicate offer IDs per subscription).
- [ ] Unconfirmed subscriptions (`confirmed = FALSE`) are never included in the result.
