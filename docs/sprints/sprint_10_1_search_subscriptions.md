# Sprint 10.1 — Search Subscriptions

## Context

Users can follow individual offers, but there is no way to proactively discover new offers matching their interests. The old keyword-matching system was removed in Sprint 8.2 because it was too broad (matched against all new offers across all subscriptions) and relied on separate cron scripts.

We want a simpler, more focused feature: users subscribe to specific search terms, and when new offers matching those terms appear, they get an immediate email notification. This is similar to the old keyword system but scoped to individual user-managed terms with an on/off toggle, integrated into the ingestion pipeline.

## Design

### Data model

New table `search_subscriptions`:

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `subscription_id` | UUID FK → subscriptions.id | CASCADE on delete |
| `term` | VARCHAR(255) | The search term |
| `active` | BOOLEAN | Default true. Allows disabling without deleting |
| `created_at` | TIMESTAMP | |

Unique constraint on `(subscription_id, term)` to prevent duplicates.

### Matching logic

Runs as `scripts/match_search_subscriptions.py` after each non-initial ingestion run, called from `ingest_all.py`. Algorithm:

1. Query all active `search_subscriptions` with confirmed subscriptions.
2. For each term, find active `job_offers` whose `unaccent(title) ILIKE unaccent('%term%')`.
3. Exclude offers already present in `notification_queue` with `notification_type = 'search_match'` for that subscription.
4. For each new match: insert into `notification_queue` and call `send_search_match_email()`.
5. If SMTP fails, mark queue row as `failed` instead of `sent`.

This follows the same pattern as `notify_followed_offers.py` — deduplication via `notification_queue` ensures each subscriber gets at most one notification per offer per term.

### Email

New function `send_search_match_email()` in `src/notifications/email.py`. Two new templates: `search_match_email.{html,txt}`. Email includes:
- The search term that matched
- Offer title, institution, region, close date
- Link to the offer on the portal
- Link to manage search subscriptions

### UI

New page at `/search-subscriptions` with:
- Form to add a new term
- Table of existing terms with columns: Termino, Activo (green/gray badge toggle), Resultados (link to `/?q=term`), Accion (delete button with trash icon)
- Delete uses `btn-follow--danger` class (red hover, same shape as follow button)
- Toggle uses `badge-green` / `badge-gray` classes

In the navbar dropdown, a "Mis busquedas" link is added (both server-rendered and JS-injected).

### Files changed

| File | Change |
|------|--------|
| `src/database/models.py` | Add `SearchSubscription` model |
| `migrations/versions/0016_add_search_subscriptions.py` | New migration |
| `scripts/match_search_subscriptions.py` | New script: match offers against active terms, queue + send emails |
| `scripts/ingest_all.py` | Call `match_search_subscriptions.py` after `notify_followed_offers.py` |
| `src/notifications/email.py` | Add `send_search_match_email()` and export |
| `src/notifications/templates/search_match_email.html` | New email template (HTML) |
| `src/notifications/templates/search_match_email.txt` | New email template (text) |
| `src/web/routers/subscriptions.py` | Add search subscription endpoints: GET/POST `/search-subscriptions`, POST `/{id}/delete`, POST `/{id}/toggle` |
| `src/web/templates/search_subscriptions.html` | New page: manage search terms |
| `src/web/templates/partials/navbar.html` | Add "Mis busquedas" link in authenticated dropdown |
| `src/web/templates/base.html` | Add "Mis busquedas" link in JS-injected dropdown |
| `src/web/static/style.css` | Add `.form-card`, `.search-term-form`, `.btn-follow--danger` |

### Acceptance criteria

- [ ] `POST /search-subscriptions?token=` with a term creates a new search_subscription row.
- [ ] `POST /search-subscriptions/{id}/delete?token=` removes the term.
- [ ] `POST /search-subscriptions/{id}/toggle?token=` toggles the active state.
- [ ] Active terms are displayed with `badge-green`; inactive with `badge-gray`.
- [ ] Each term has a "Ver" link to `/?q=term` that opens in the same tab.
- [ ] Delete button has a trash icon and uses `btn-follow--danger` styling (red hover).
- [ ] `scripts/match_search_subscriptions.py --dry-run` logs matches without sending or writing.
- [ ] `scripts/match_search_subscriptions.py` sends one email per match for unmatched offers.
- [ ] `ingest_all.py` runs `match_search_subscriptions.py` after `notify_followed_offers.py`.
- [ ] Navbar dropdown (authenticated) shows "Mis busquedas" link.
- [ ] Navbar dropdown (JS-injected) shows "Mis busquedas" link.
- [ ] Migration 0016 creates the `search_subscriptions` table.
- [ ] `ruff check .` passes.
