"""Processing utilities: external ID extraction, salary parsing, and fingerprint computation."""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse


def extract_external_id(url: str | None) -> str | None:
    """Extract the source-native ID from a job offer URL.

    Returns None when the URL is empty, None, or belongs to a domain
    that does not expose a stable numeric identifier.

    Rules per domain:
    - empleospublicos.cl  → ``?i=<id>`` query param
    - junji.myfront.cl    → ``/oferta-de-empleo/<id>/slug`` path segment
    - *.trabajando.cl     → ``/trabajo/<id>-slug`` numeric prefix
    - anything else       → None
    """
    if not url:
        return None

    parsed = urlparse(url)
    domain = parsed.netloc

    # empleospublicos.cl → ?i=<id>
    if "empleospublicos.cl" in domain:
        qs = parse_qs(parsed.query)
        values = qs.get("i", [])
        return values[0] if values and values[0] else None

    # junji.myfront.cl → /oferta-de-empleo/<id>/slug
    if domain == "junji.myfront.cl":
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "oferta-de-empleo":
            candidate = parts[1]
            return candidate if candidate else None

    # *.trabajando.cl → /trabajo/<id>-slug  (id is numeric prefix before first -)
    if "trabajando.cl" in domain:
        parts = [p for p in parsed.path.split("/") if p]
        try:
            idx = parts.index("trabajo")
            if idx + 1 < len(parts):
                numeric = parts[idx + 1].split("-")[0]
                return numeric if numeric.isdigit() else None
        except ValueError:
            pass

    return None


def parse_salary(raw: str | None) -> Decimal | None:
    """Parse a raw salary string from EEPP into a Decimal.

    EEPP delivers salary as a string with a comma decimal separator,
    e.g. ``"594027,00"``. Returns ``None`` for empty, zero, or unparseable values.
    """
    if not raw:
        return None
    normalised = raw.replace(".", "").replace(",", ".").strip()
    try:
        value = Decimal(normalised)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def compute_fingerprint(
    source: str,
    external_id: str | None,
    *,
    title: str,
    institution: str,
    region: str | None,
) -> str:
    """Return the MD5 hex digest (32 chars) used as deduplication key.

    When ``external_id`` is available: ``MD5(source|external_id)``
    Fallback (no external_id): ``MD5(source|title|institution|region)``
    """
    if external_id is not None:
        raw = f"{source}|{external_id}"
    else:
        raw = f"{source}|{title}|{institution}|{region or ''}"
    return hashlib.md5(raw.encode()).hexdigest()


__all__ = [
    "compute_fingerprint",
    "extract_external_id",
    "parse_salary",
]
