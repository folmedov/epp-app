# Sprint 6.4 — Subscription UI

## Context

The router and backend logic for subscriptions are complete (Sprint 6.3). This
sprint finalises the user-facing layer:

1. **Topbar link** — a persistent "Alertas" link in `base.html` that navigates
   to `/subscribe` from any page.
2. **Template content** — fill in the stub templates created in Sprint 6.3
   (`subscribe.html`, `confirm_ok.html`, `unsubscribe_ok.html`) with polished
   copy and accessible markup.
3. **CSS** — add the missing utility classes referenced by these templates
   (`.card`, `.subscribe-card`, `.page-content`, `.form-group`, `.form-hint`,
   `.form-error`, `.btn`, `.btn-primary`) to `style.css`.

No new routes or backend logic are needed — this sprint is purely HTML + CSS.

## Design

### Topbar link

Add a text link "Alertas" to the right side of `.topbar-inner` in `base.html`,
after the `{% block topbar_search %}` block. It must be visible on both desktop
and mobile (does not hide below 600 px). Style: same color as the topbar brand
text, understated — it is a secondary action.

```html
<a class="topbar-nav-link" href="/subscribe" aria-label="Configurar alertas de email">
  Alertas
</a>
```

### `subscribe.html`

Two states rendered by the same template:

| State | Trigger | Content |
|---|---|---|
| **Form** (default) | `submitted=False` | Heading, description, optional error banner, email + keywords fields, submit button |
| **Success** | `submitted=True` | Confirmation message, "check your inbox" copy, link back to `/` |

Form layout:
- Two labelled inputs: `email` (type=email, maxlength=254) and `keywords`
  (type=text) with a hint about comma separation.
- Validation error shown in a `.form-error` banner above the form when
  `error` is set.
- Submit button uses `.btn.btn-primary`.

### `confirm_ok.html`

Two states:

| State | Trigger | Content |
|---|---|---|
| **Success** | `success=True` | Confirmation message, invitation to browse offers, link to `/` |
| **Failure** | `success=False` | Error message from `message`, link to `/subscribe` to retry |

### `unsubscribe_ok.html`

Two states:

| State | Trigger | Content |
|---|---|---|
| **Removed** | `already_removed=False` | "Suscripción cancelada" with a friendly goodbye message, link to `/` |
| **Already gone** | `already_removed=True` | Neutral message — no error shown, link to `/` |

## CSS additions (`style.css`)

New rules to append to `style.css`:

### `.page-content`

Centered content wrapper for standalone pages (subscribe, confirm, unsubscribe):

```css
.page-content {
  max-width: 560px;
  margin: 48px auto;
  padding: 0 16px;
}
```

### `.card`

Generic surface card:

```css
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 32px;
}
```

### `.subscribe-card`

No extra rules needed beyond `.card` — the class is kept as a hook for
future specificity if needed.

### `.form-group`

Vertical label + input pair:

```css
.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 20px;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.form-group input[type="email"],
.form-group input[type="text"] {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 0.95rem;
  background: var(--bg);
  color: var(--text);
  transition: border-color 0.15s;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
```

### `.form-hint`

Secondary helper text below an input:

```css
.form-hint {
  font-size: 0.8rem;
  color: var(--text-secondary);
}
```

### `.form-error`

Inline validation / notice banner:

```css
.form-error {
  background: #fef2f2;
  border: 1px solid #fca5a5;
  color: #b91c1c;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 0.875rem;
  margin-bottom: 16px;
}
```

### `.btn` and `.btn-primary`

Generic action button (`.btn`) with a filled primary variant:

```css
.btn {
  display: inline-block;
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  text-decoration: none;
  transition: opacity 0.15s;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}

.btn-primary:hover { opacity: 0.88; }
.btn-primary:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.25);
}
```

### `.topbar-nav-link`

Right-side navigation link inside the topbar:

```css
.topbar-nav-link {
  margin-left: auto;
  color: rgba(255, 255, 255, 0.82);
  font-size: 0.875rem;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
  padding: 4px 8px;
  border-radius: 4px;
  transition: color 0.15s, background 0.15s;
}

.topbar-nav-link:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}
```

## Implementation checklist

### 1. `src/web/templates/base.html`

Add after `{% block topbar_search %}{% endblock %}`:

```html
<a class="topbar-nav-link" href="/subscribe" aria-label="Configurar alertas de email">
  Alertas
</a>
```

### 2. `src/web/templates/subscribe.html`

Replace stub content with full form + success state (see Design section above).
The stub created in Sprint 6.3 already has the correct structure — this sprint
adds proper styling classes and polishes copy.

### 3. `src/web/templates/confirm_ok.html`

Replace stub with polished success/failure states.

### 4. `src/web/templates/unsubscribe_ok.html`

Replace stub with polished removed/already-gone states.

### 5. `src/web/static/style.css`

Append all new rule-sets listed in the CSS additions section above.

## Files changed

| File | Change |
|---|---|
| `src/web/templates/base.html` | Add "Alertas" topbar link |
| `src/web/templates/subscribe.html` | Full form + success state |
| `src/web/templates/confirm_ok.html` | Polished success/failure states |
| `src/web/templates/unsubscribe_ok.html` | Polished removed/already-gone states |
| `src/web/static/style.css` | New utility classes for subscription pages |

## Acceptance criteria

- [ ] A visible "Alertas" link appears in the topbar on the offers page and on all subscription pages.
- [ ] `GET /subscribe` renders a form with email and keywords fields.
- [ ] Submitting the form with valid data shows the "check your inbox" success message.
- [ ] Submitting with empty email or missing keywords shows a visible error banner above the form.
- [ ] `GET /confirm/{valid_token}` renders `confirm_ok.html` with a success message and a link to `/`.
- [ ] `GET /confirm/{expired_or_invalid_token}` renders the failure state with a link back to `/subscribe`.
- [ ] `GET /unsubscribe/{valid_token}` renders the "Suscripción cancelada" state.
- [ ] `GET /unsubscribe/{unknown_token}` renders the "Suscripción no encontrada" state without an error.
- [ ] All pages are usable on mobile (max-width 375 px) — no horizontal overflow.
- [ ] All interactive elements have visible focus styles.
