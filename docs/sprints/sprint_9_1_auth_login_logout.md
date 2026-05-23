# Sprint 9.1 — Email-based Auth: Register, Login, Logout

## Context

Users authenticate via `unsubscribe_token` stored in localStorage and sent as `?token=` query param on follow/unfollow requests. There is no explicit login, logout, or user-facing identity — the token is permanent and the user never sees their email in the UI.

We want proper auth flows (register, login, logout) while keeping the email-based, passwordless approach. No JWT, no sessions, no password storage.

## Design

### Auth model — reuse `unsubscribe_token` as Bearer token

The existing `subscriptions.unsubscribe_token` (UUID) serves as the auth token. No new table, column, or migration is needed for token storage.

| Change | Detail |
|--------|--------|
| Transport | `Authorization: Bearer <uuid>` header becomes the primary mechanism. `?token=` query param is kept as fallback for HTMX links that cannot set custom headers easily. |
| Token scope | Same as today — identifies a subscription. No roles or permissions. |
| Token lifecycle | Permanent by default. Logout is client-side (remove from localStorage). Optional server-side invalidation via `token_invalidated_at` column (future). |

### Auth middleware

A FastAPI dependency (or middleware) that:
1. Reads `Authorization: Bearer <token>` header, or falls back to `?token=` query param.
2. Looks up `subscriptions WHERE unsubscribe_token = $1 AND confirmed = true AND (token_invalidated_at IS NULL OR token_invalidated_at > now())`.
3. Attaches the `Subscription` (or `subscription_id`, `email`) to `request.state`.
4. Returns 401 if token is missing or invalid on protected endpoints.

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `POST` | `/auth/register` | No | Subscribe with email (alias for existing `/subscribe`) |
| `POST` | `/auth/login` | No | Send magic link email with the unsubscribe_token |
| `POST` | `/auth/logout` | Bearer | Invalidate token server-side (optional) + instruct client to remove from localStorage |
| `GET` | `/auth/me` | Bearer | Return `{ email, subscription_id, created_at }` |
| `GET` | `/auth/confirm/{token}` | No | Confirm subscription (existing, redirect to magic-link landing) |
| `GET` | `/auth/magic-link/{token}` | No | Landing page that saves token to localStorage and redirects to `/` |

### Flows

**Register:**
```
POST /auth/register { email }
  → create unconfirmed subscription row
  → send confirmation email (confirm_email template)
  → return 201 { message: "Revisa tu correo" }

User clicks confirmation link → GET /auth/confirm/{token}
  → validate token & expiry → set confirmed=True, generate unsubscribe_token
  → redirect to /auth/magic-link/{unsubscribe_token}

GET /auth/magic-link/{token}
  → renders page that saves token to localStorage, then redirects to /
  → navbar now shows user email + "Cerrar sesion"
```

**Login:**
```
POST /auth/login { email }
  → look up confirmed subscription by email
  → if found: send magic link email (follow_link_email template) with unsubscribe_token
  → if not found: return success anyway (don't reveal which emails are registered)
  → return 200 { message: "Si el correo esta registrado, revisa tu bandeja" }

User clicks magic link → GET /auth/magic-link/{token}
  → same landing page, saves token to localStorage
  → navbar shows user email + "Cerrar sesion"
```

**Logout:**
```
POST /auth/logout (Authorization: Bearer <token>)
  → optionally set token_invalidated_at on the subscription (server-side)
  → return 200 { message: "Sesion cerrada" }

Client also removes token from localStorage.
```

### UI changes

1. **Navbar**: Replace "Suscribirme" with two links when not authenticated: "Iniciar sesion" and "Registrarse". When authenticated: show user email (truncated) and "Cerrar sesion".
2. **Auth state**: Determined by presence of token in localStorage. On page load, if token exists, `GET /auth/me` validates it server-side and returns user info.
3. **Magic link landing page** (`save_token.html` / `magic_link.html`): Enhanced to also call `GET /auth/me` and update navbar state after saving token.
4. **Login page** (`login.html`): Simple form with email field, posts to `POST /auth/login`.
5. **Register page**: The existing subscribe form, accessible from `/auth/register`.
6. **Logout**: Button that calls `POST /auth/logout`, removes token from localStorage, reloads page.

### Files changed

| File | Change |
|------|--------|
| `src/web/routers/auth.py` | New router with register, login, logout, me, magic-link endpoints |
| `src/web/app.py` | Register auth router |
| `src/web/templates/base.html` | Update navbar: conditional links based on auth state, JS to check token on load |
| `src/web/templates/login.html` | New: login form (email only) |
| `src/web/templates/magic_link.html` | New or update `save_token.html`: landing page that saves token and redirects |
| `src/web/templates/partials/navbar.html` | New: extract navbar to partial for HTMX swap on login/logout |
| `src/web/routers/subscriptions.py` | Keep existing `/subscribe` for backward compat, but redirect to `/auth/register` |
| `src/database/models.py` | Add optional `token_invalidated_at` column on `Subscription` |
| `migrations/versions/0015_token_invalidated_at.py` | New migration |

### Acceptance criteria

- [ ] `POST /auth/register` with a new email creates an unconfirmed subscription and sends confirmation email.
- [ ] `POST /auth/register` with an already-registered email returns success (idempotent, resends email).
- [ ] `POST /auth/login` with a registered email sends a magic link with the unsubscribe_token.
- [ ] `POST /auth/login` with an unregistered email returns success (no information leak).
- [ ] `GET /auth/magic-link/{token}` saves the token to localStorage and redirects to `/`.
- [ ] `GET /auth/me` with a valid Bearer token returns `{ email, subscription_id }`.
- [ ] `GET /auth/me` without a token returns 401.
- [ ] `GET /auth/me` with an invalid token returns 401.
- [ ] `POST /auth/logout` with a valid token sets `token_invalidated_at` and returns 200.
- [ ] After logout, the same token returns 401 on `/auth/me`.
- [ ] Navbar shows "Iniciar sesion" and "Registrarse" when no token is in localStorage.
- [ ] Navbar shows user email and "Cerrar sesion" when a valid token is present.
- [ ] Existing `?token=` query param auth on follow/unfollow/dashboard endpoints still works.
- [ ] Follow/unfollow/dashboard accept `Authorization: Bearer <token>` in addition to `?token=`.
- [ ] `ruff check .` passes.
- [ ] `pytest` passes.
