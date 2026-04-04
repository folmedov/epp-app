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

    # directoresparachile.cl → use PDF filename stem as stable id (e.g. dee_1967_7707)
    if "directoresparachile.cl" in domain:
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            filename = parts[-1]
            stem = filename.split("?")[0]
            if stem.lower().endswith(".pdf"):
                stem = stem[: -4]
            return stem if stem else None

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


def compute_content_fingerprint(
    title: str,
    institution: str,
    region: str | None,
    city: str | None,
    *,
    ministry: str | None = None,
    start_date: str | None = None,
    conv_type: str | None = None,
    close_date: str | None = None,
) -> str:
    """MD5 of normalised composed fields.

    New fingerprint includes optional fields to reduce Stage-B collisions:
    title|institution|region|city|ministry|start_date|conv_type|close_date
    Text fields are lowercased and stripped; dates are included as-provided.
    """
    parts = [
        title.strip().lower(),
        institution.strip().lower(),
        (region or "").strip().lower(),
        (city or "").strip().lower(),
        (ministry or "").strip().lower(),
        (start_date or ""),
        (conv_type or "").strip().lower(),
        (close_date or ""),
    ]
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()


def compute_fingerprint(
    source: str,
    external_id: str | None,
    *,
    title: str,
    institution: str,
    region: str | None,
    city: str | None = None,
    external_id_generated: bool = False,
    ministry: str | None = None,
    start_date: str | None = None,
    conv_type: str | None = None,
    close_date: str | None = None,
) -> str:
    """Return the MD5 hex digest (32 chars) used as deduplication key.

    Two-stage strategy (mirrors ``teee_external_id_policy.md``):

    Stage A — reliable ``external_id`` (``external_id_generated=False``):
        ``MD5("source_id|{source}|{external_id}")``

    Stage B — no reliable ``external_id``:
        ``MD5("content|{compute_content_fingerprint(...)}")``

    The ``"source_id|"`` / ``"content|"`` prefixes prevent accidental
    hash collisions between the two families of fingerprints.
    """
    if external_id is not None and not external_id_generated:
        raw = f"source_id|{source}|{external_id}"
    else:
        content_fp = compute_content_fingerprint(
            title,
            institution,
            region,
            city,
            ministry=ministry,
            start_date=start_date,
            conv_type=conv_type,
            close_date=close_date,
        )
        raw = f"content|{content_fp}"
    return hashlib.md5(raw.encode()).hexdigest()


__all__ = [
    "compute_content_fingerprint",
    "compute_fingerprint",
    "extract_external_id",
    "parse_salary",
]
