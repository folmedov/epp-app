# Sprint 8.1 — Offer Following & Token-based Dashboard

## Context

Users can currently subscribe with their email and receive a token for API access (no keyword-based matching). However, there is no way to **follow a specific offer** and receive notifications when its state changes (e.g. from `postulacion` to `evaluacion`). (Note: keyword-based matching was later removed in Sprint 8.2.)

Adding full user registration (passwords, sessions) would be disproportionate for this use case. The project already has a token-based auth system via `subscriptions.unsubscribe_token` — a permanent, unguessable UUID that is generated on confirmation and included in every notification email.

## Design

### Auth model — reuse `unsubscribe_token`

No new users, passwords, or sessions. The `unsubscribe_token` identifies the subscription. The user stores it in `localStorage` on the browser. All offer-following API calls include it as a query param or header.

Flow:
1. User clicks "Seguir oferta" → if no token in `localStorage`, prompt for email → send a magic link (like confirmation) with the token → user clicks → token saved to `localStorage`.
2. Subsequent visits: token is already in `localStorage` → follow/unfollow is instant.
3. User can also copy the token from the email footer and paste it on a settings page.

The same token already powers unsubscribe — no new table or migration needed for auth.

### New table: `offer_follows`

```
offer_follows
├── subscription_id  UUID  FK → subscriptions.id  ON DELETE CASCADE
├── job_offer_id     UUID  FK → job_offers.id      ON DELETE CASCADE
├── created_at       TIMESTAMP
└── UNIQUE(subscription_id, job_offer_id)
```

### API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/offers/{id}/follow?token=xxx` | token | Follow an offer |
| `DELETE` | `/offers/{id}/follow?token=xxx` | token | Unfollow an offer |
| `GET` | `/offers/follows?token=xxx` | token | List followed offers (JSON partial) |
| `GET` | `/follows?token=xxx` | token | Full dashboard page with all followed offers |

### UI changes

1. **Follow button** on each offer row (in `offers_table.html`): toggles "Seguir" / "Siguiendo" via HTMX, uses token from `localStorage`.
2. **Follows dashboard** (`/follows`): shows all followed offers with their current state, close_date, and state changes.
3. **localStorage JS**: small inline script in `base.html` to read/write `unsubscribe_token`.

### Notifications for state changes

A new script `scripts/notify_followed_offers.py` that:
1. Queries `offer_follows` for all active follows.
2. For each followed offer, compares its current `state` against `job_offer_sources.original_state` from the most recent ingest.
3. If the state changed, queues a notification (new `notification_type = 'state_change'`) and sends an email to the subscriber.
4. Respects the same retry logic from Sprint 6.12.

Called by `ingest_all.py` after `close_stale_offers.py` (non-fatal).

## Files changed

| File | Change |
|---|---|
| `src/database/models.py` | Add `OfferFollow` model |
| `migrations/versions/0013_offer_follows.py` | New migration |
| `src/web/routers/offers.py` | Add follow/unfollow/list endpoints |
| `src/web/routers/subscriptions.py` | Add token-link endpoint for magic auth |
| `src/web/app.py` | Register new routes |
| `src/web/templates/partials/offers_table.html` | Add follow button per row |
| `src/web/templates/follows.html` | New: dashboard page for followed offers |
| `src/web/templates/base.html` | Add localStorage token script |
| `scripts/notify_followed_offers.py` | New: detect state changes and notify |
| `scripts/ingest_all.py` | Hook `notify_followed_offers.py` after close_stale |

## Acceptance criteria

- [ ] `POST /offers/{id}/follow?token=xxx` with a valid token creates an `offer_follows` row.
- [ ] `DELETE /offers/{id}/follow?token=xxx` removes the row. Idempotent (no error if already unfollowed).
- [ ] `GET /offers/follows?token=xxx` returns the list of followed offers for that subscription.
- [ ] Follow button in the offers table toggles state without full page reload (HTMX).
- [ ] If no token is in `localStorage`, clicking "Seguir" prompts for email and sends a magic link.
- [ ] `/follows?token=xxx` renders a dashboard showing all followed offers with current state.
- [ ] `scripts/notify_followed_offers.py` detects a state change and sends an email.
- [ ] `--dry-run` in `notify_followed_offers.py` logs intent without sending.
- [ ] Deleting a subscription cascades to its `offer_follows` rows.
- [ ] Invalid/missing token returns 401 or a friendly error page.
