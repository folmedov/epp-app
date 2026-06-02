# Sprint 10.2 — Pill Toggle & Contrast

## Context

Sprint 10.1 introduced term pills for search subscriptions with separate icon buttons for toggle (checkmark/cross), view (magnifier), and delete (trash). In practice:

- The toggle icon was too small and easy to miss.
- Active vs. inactive state was visually subtle (#eef2ff vs. #f1f5f9), making it hard to tell at a glance which terms were enabled.
- Users expected the pill itself to act as the toggle, since that is the dominant visual element.

## Design

### Pill-as-toggle

Replace the separate `.term-pill-btn--toggle` button with a `<form>` wrapping the entire pill (label + count badge). The pill is now a `<button type="submit">` styled identically to the old pill `<div>`.

The view (magnifier) and delete (trash) icons become sibling elements in a flex container `.term-pill-wrapper`, visually attached left/right with shared borders to appear as one continuous pill-shaped group.

```
┌─────────────────────────────────────────────────┐
│ [analis (5)] [🔍] [🗑️]                        │
│  ↑ toggle       ↑ view  ↑ delete                │
└─────────────────────────────────────────────────┘
```

Structure per term:
```
.term-pill-wrapper (display: inline-flex)
  ├── form.term-pill-form (POST /toggle)
  │     └── button.term-pill (border-radius: 99px 0 0 99px)
  │            ├── span.term-pill-label
  │            └── span.term-pill-count
  ├── a.term-pill-action--view (→ /?q=term)
  └── form.term-pill-action-form (POST /delete)
        └── button.term-pill-action--delete (border-radius: 0 99px 99px 0)
```

### Contrast

| State | Pill bg | Border | Count badge | Text |
|-------|---------|--------|-------------|------|
| Active | `#e0e7ff` | `#a5b4fc` 2px solid | `#8b5cf6` bg, white text, weight 700 | weight 600 |
| Inactive | `#f1f5f9` | `#cbd5e1` 1.5px dashed | `#cbd5e1` bg, `#64748b` text | `#94a3b8`, weight 400, opacity 0.8 |

The dashed border is a strong visual cue that the term is disabled, similar to "disabled" patterns in other UIs.

### Files changed

| File | Change |
|------|--------|
| `src/web/templates/search_subscriptions.html` | Replace pill structure: wrapper with form/button for toggle, sibling view link and delete form |
| `src/web/static/style.css` | Replace `.term-pill-btn-*` / `.term-pill-actions` with `.term-pill-wrapper`, `.term-pill-form`, `.term-pill-action-*`; increase contrast for both states |

### Acceptance criteria

- [ ] Clicking anywhere on the pill (label or count badge) toggles active/inactive.
- [ ] Active pills have a solid indigo border (2px) and violet count badge.
- [ ] Inactive pills have a dashed gray border with reduced opacity.
- [ ] The view (magnifier) and delete (trash) icons are visually attached to the pill and function independently (no accidental toggle).
- [ ] Hover states are distinct for all interactive elements.
- [ ] `ruff check .` passes.
