"""Processing utilities: external ID extraction, salary parsing, and fingerprint computation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

# Date formats shared by EEPP and TEEE (DD/MM/YYYY with varying time precision).
_DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %-H:%M:%S",
    "%d/%m/%Y %-H:%M",
)


def parse_date(raw: str | datetime | None) -> datetime | None:
    """Normalize a raw date value from any source into a ``datetime``.

    Accepts an already-parsed ``datetime`` (returned as-is), a string in any
    of the EEPP/TEEE formats (``DD/MM/YYYY H:MM`` or ``DD/MM/YYYY H:MM:SS``),
    or ``None`` / empty string (returns ``None``).
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def extract_external_id(url: str | None) -> str | None:
    """Extract the source-native ID from a job offer URL.

    Returns None when the URL is empty, None, or belongs to a domain
    that does not expose a stable numeric identifier.

    Rules per domain:
    - empleospublicos.cl  → ``?i=<id>`` query param
    - *.trabajando.cl     → ``/trabajo/<id>-slug`` numeric prefix
    - anything else       → None

    Note: ``junji.myfront.cl`` IDs are **not extracted** because JUNJI
    reuses the same numeric ID across different positions. Treating those
    IDs as stable external keys causes Stage-A fingerprint collisions where
    two genuinely distinct offers share one canonical ``job_offers`` row.
    These records fall through to Stage-B (content fingerprint) instead.
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

    # directoresparachile.cl → only use `?i=<id>` query param as stable id.
    # PDF filename stems (e.g. dee_18099) are NOT unique — the same file is
    # reused across different concursos at different times, so treating the stem
    # as external_id causes false Stage-A collisions.  When `?i=` is absent,
    # returning None forces Stage-B (content fingerprint) which correctly
    # differentiates records by title, institution, and dates.
    if "directoresparachile.cl" in domain:
        qs = parse_qs(parsed.query)
        values = qs.get("i", [])
        if values and values[0]:
            return values[0]
        return None

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


def compute_cross_source_key(external_id: str | None, external_id_generated: bool) -> str | None:
    """Return a source-agnostic linking key for cross-portal deduplication.

    Computes ``MD5("cross|{external_id}")`` when *external_id* is a verified
    (non-generated) value.  Returns ``None`` for generated / absent IDs.  The
    ``"cross|"`` prefix prevents accidental collisions with Stage-A or Stage-B
    fingerprints.
    """
    if external_id is None or external_id_generated:
        return None
    return hashlib.md5(f"cross|{external_id}".encode()).hexdigest()


def compute_content_fingerprint(
    title: str,
    institution: str,
    region: str | None,
    city: str | None,
    *,
    ministry: str | None = None,
    start_date: datetime | None = None,
    conv_type: str | None = None,
    close_date: datetime | None = None,
) -> str:
    """MD5 of normalised composed fields.

    New fingerprint includes optional fields to reduce Stage-B collisions:
    title|institution|region|city|ministry|start_date|conv_type|close_date
    Text fields are lowercased and stripped; dates are formatted as ISO 8601.
    """
    parts = [
        title.strip().lower(),
        institution.strip().lower(),
        (region or "").strip().lower(),
        (city or "").strip().lower(),
        (ministry or "").strip().lower(),
        start_date.isoformat() if start_date is not None else "",
        (conv_type or "").strip().lower(),
        close_date.isoformat() if close_date is not None else "",
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
    start_date: datetime | None = None,
    conv_type: str | None = None,
    close_date: datetime | None = None,
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
    "compute_cross_source_key",
    "compute_fingerprint",
    "extract_external_id",
    "parse_date",
    "parse_salary",
]
