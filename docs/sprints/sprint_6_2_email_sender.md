# Sprint 6.2 — Email Sender Module

## Context

The notification system needs a reusable async email sender used by both the
immediate notification script (`notify_new_offers.py`) and the weekly digest
script (`weekly_digest.py`). The sender uses SMTP directly via `aiosmtplib` —
no external email API is required. Email content is rendered from Jinja2
templates shared with the web layer.

## Design

### Configuration

All SMTP settings are added to `src/core/config.py` as optional fields (to
avoid breaking the app when not configured). They are required at runtime only
when attempting to send email.

| Env var | Type | Description |
|---|---|---|
| `SMTP_HOST` | str | SMTP server hostname |
| `SMTP_PORT` | int | SMTP port (default `587` for STARTTLS) |
| `SMTP_USER` | str | SMTP authentication username |
| `SMTP_PASSWORD` | str | SMTP authentication password |
| `SMTP_FROM` | str | Sender address shown to recipients (e.g. `"Job Tracker <noreply@example.com>"`) |
| `APP_BASE_URL` | str | Base URL used to build confirm/unsubscribe links (e.g. `https://tracker.example.com`) |

### Module: `src/notifications/email.py`

Single public interface with two async functions:

```python
async def send_confirmation_email(email: str, token: str) -> None: ...
async def send_notification_email(
    email: str,
    offers: list[OfferRow],
    unsubscribe_token: str,
    notification_type: Literal["immediate", "digest"],
) -> None: ...
```

Both functions:
- Build an `aiosmtplib` connection using `settings.SMTP_*` values.
- Use STARTTLS (`start_tls=True`) on port 587, or plain SSL on port 465.
- Render HTML and plain-text bodies from Jinja2 templates (same `Environment` instance as the web templates).
- Raise a `NotificationError` (custom exception) if SMTP credentials are not configured or the send fails after one attempt — callers handle retries via the `notification_queue`.

### Email templates

Stored in `src/notifications/templates/`:

| Template | Used by |
|---|---|
| `confirm_email.html` + `confirm_email.txt` | `send_confirmation_email` |
| `notification_immediate.html` + `.txt` | `send_notification_email` with `type='immediate'` |
| `notification_digest.html` + `.txt` | `send_notification_email` with `type='digest'` |

All templates receive:
- `base_url` — from `settings.APP_BASE_URL`
- `unsubscribe_url` — `{base_url}/unsubscribe/{token}`
- `confirm_url` (confirmation only) — `{base_url}/confirm/{token}`
- `offers` (notification only) — list of `OfferRow` with title, institution, region, close_date, URL

### Error handling

- Missing SMTP config → raise `NotificationError` immediately (no attempt to connect).
- SMTP auth or connection failure → raise `NotificationError` with original exception chained.
- Callers (`notify_new_offers.py`, `weekly_digest.py`) catch `NotificationError`, increment `attempts` on the queue row, and mark `status='failed'` if `attempts >= 3`.

## Implementation

### 1. `src/core/config.py`

Add optional SMTP fields:

```python
SMTP_HOST: Optional[str] = Field(None)
SMTP_PORT: int = Field(587)
SMTP_USER: Optional[str] = Field(None)
SMTP_PASSWORD: Optional[str] = Field(None)
SMTP_FROM: Optional[str] = Field(None)
APP_BASE_URL: str = Field("http://localhost:8000")
```

### 2. `src/notifications/__init__.py`

Empty file — makes `notifications` a package.

### 3. `src/notifications/email.py`

- `_get_smtp_connection()` — returns a configured `aiosmtplib.SMTP` context manager.
- `_render(template_name, context)` — renders HTML and plain-text from the notifications Jinja2 env.
- `send_confirmation_email(email, token)` — public.
- `send_notification_email(email, offers, unsubscribe_token, notification_type)` — public.

### 4. `src/notifications/templates/`

Minimal HTML emails with:
- A clear subject line.
- Offer list with title, institution, region, close date, and a direct link.
- Plain-text fallback for every HTML template.
- An unsubscribe link in every notification email footer.

### 5. `pyproject.toml`

Add `aiosmtplib` dependency.

## Acceptance criteria

- [ ] `send_confirmation_email` sends a correctly formatted email with a working `confirm_url` link.
- [ ] `send_notification_email` with `type='immediate'` sends one offer per call with an unsubscribe link.
- [ ] `send_notification_email` with `type='digest'` sends a grouped list of offers.
- [ ] Calling either function with SMTP not configured raises `NotificationError` without attempting a connection.
- [ ] Plain-text fallback is present in all sent emails (multipart/alternative).
- [ ] `aiosmtplib` is listed as a project dependency in `pyproject.toml`.
