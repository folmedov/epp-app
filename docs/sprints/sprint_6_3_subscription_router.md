# Sprint 6.3 — Subscription Router

## Context

With the DB schema (6.1) and email sender (6.2) in place, this sprint wires
the subscriber lifecycle into the web layer. Three HTTP endpoints handle the
full flow: form submission, double opt-in confirmation, and one-click
unsubscribe.

No authentication is required for any of these routes — subscriptions are
identified by single-use or permanent URL tokens.

## Design

### Routes

| Method | Path | Form / Path param | Description |
|---|---|---|---|
| `POST` | `/subscribe` | `email`, `keywords` (form fields) | Create unconfirmed subscription and send confirmation email |
| `GET` | `/confirm/{token}` | `token` (UUID string) | Confirm subscription via double opt-in link |
| `GET` | `/unsubscribe/{token}` | `token` (UUID string) | Delete subscription via unsubscribe link |

### `POST /subscribe`

**Input** — HTML form body (`application/x-www-form-urlencoded`):

| Field | Type | Constraints |
|---|---|---|
| `email` | string | Required; max 254 chars |
| `keywords` | string | Required; comma-separated list, min 1 keyword after split |

**Processing:**

1. Normalise `email` to lowercase and strip whitespace.
2. Split `keywords` on commas, strip each token, discard empty strings.
3. Validate: missing/empty email or empty keyword list → re-render `subscribe.html` with an error message (no redirect).
4. If a confirmed subscription for this email already exists → re-render the form with a friendly notice ("Ya estás suscrito/a con este email").
5. If an unconfirmed subscription exists → regenerate `confirmation_token` + `token_expires_at` (overwrite the old one) and resend the confirmation email. This covers the case of a user who lost the first email without creating a duplicate row.
6. Otherwise, insert a new `Subscription` row:
   - `confirmed = False`
   - `confirmation_token = uuid4()`
   - `token_expires_at = datetime.utcnow() + timedelta(hours=24)`
   - `unsubscribe_token = None` (generated on confirmation)
7. Call `send_confirmation_email(email, str(confirmation_token))` — if `NotificationError` is raised, log the error and still show the success page (the token is saved; the user can request a resend later).
8. Return a `subscribe.html` render with `submitted=True` (no redirect — avoids form resubmission on browser refresh).

### `GET /confirm/{token}`

**Processing:**

1. Look up `Subscription` by `confirmation_token`.
2. If not found or `token_expires_at < utcnow()` → render `confirm_ok.html` with `success=False` and an appropriate message.
3. Set `confirmed = True`, `confirmation_token = None`, `token_expires_at = None`, `unsubscribe_token = uuid4()`.
4. Commit and render `confirm_ok.html` with `success=True`.

**Note:** The token is single-use — cleared on successful confirmation to prevent replay.

### `GET /unsubscribe/{token}`

**Processing:**

1. Look up `Subscription` by `unsubscribe_token`.
2. If not found → render `unsubscribe_ok.html` with `already_removed=True` (idempotent, no error shown).
3. Delete the subscription row — the `ON DELETE CASCADE` on `notification_queue` removes all pending queue entries automatically.
4. Commit and render `unsubscribe_ok.html` with `already_removed=False`.

## Implementation

### 1. `src/web/routers/subscriptions.py`

New `APIRouter` with the three routes described above. Uses `Depends(get_db_session)` for DB access and calls functions from `src/notifications/email.py`.

Key imports:
```python
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.database.models import Subscription
from src.notifications.email import NotificationError, send_confirmation_email
from src.web.deps import get_db_session
from src.web.templating import templates
```

### 2. `src/web/app.py`

Register the subscription router:
```python
from src.web.routers import subscriptions as subscriptions_router
# inside create_app():
app.include_router(subscriptions_router.router)
```

### 3. Templates (stub — detail in Sprint 6.4)

The router references three templates that will be created in Sprint 6.4:

| Template | Variables |
|---|---|
| `subscribe.html` | `submitted: bool`, `error: str \| None` |
| `confirm_ok.html` | `success: bool`, `message: str` |
| `unsubscribe_ok.html` | `already_removed: bool` |

To make the router testable before 6.4, placeholder templates with minimal
HTML are acceptable for now.

## Security notes

- Email is normalised to lowercase before DB write and lookup.
- `token` path parameters are matched exactly against UUID columns — no
  truncation or wildcard queries.
- Confirmation tokens are cleared on use to prevent replay.
- Stale unconfirmed rows (expired `token_expires_at`) are not re-exploitable:
  resending regenerates the token with a fresh 24h window.
- No user-controlled data is interpolated into SQL strings — all queries use
  bound parameters via SQLAlchemy.

## Acceptance criteria

- [ ] `POST /subscribe` with valid data creates an unconfirmed `Subscription` row and triggers a confirmation email.
- [ ] `POST /subscribe` with a duplicate confirmed email re-renders the form with a notice rather than inserting a duplicate row.
- [ ] `POST /subscribe` with missing or empty `email`/`keywords` re-renders the form with a validation error (no DB write).
- [ ] `GET /confirm/{token}` with a valid, unexpired token sets `confirmed=True` and clears the confirmation token.
- [ ] `GET /confirm/{token}` with an expired or unknown token renders the failure page without modifying any row.
- [ ] `GET /unsubscribe/{token}` with a valid token deletes the subscription and cascades to `notification_queue`.
- [ ] `GET /unsubscribe/{token}` with an unknown token renders `unsubscribe_ok.html` with `already_removed=True` without raising an error.
- [ ] The subscriptions router is registered in `src/web/app.py` and all three routes return HTTP 200.
