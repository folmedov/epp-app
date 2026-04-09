"""Canonical region codes and display names for Chile.

TEEE API provides ``"Codigo Region"`` (e.g. ``"region13"``) alongside the raw
``"Region"`` text.  EEPP API only provides free-form text.  This module maps
both formats to a stable set of 16 canonical display names so that the filter
dropdown stays clean regardless of source quirks.
"""

from __future__ import annotations

# Sentinel value stored in DB for offers that don't belong to a single Chilean region
# (multi-region strings, international, national-level, etc.)
OTRAS_UBICACIONES = "Otras ubicaciones"

# Maps TEEE "Codigo Region" → canonical display name
REGION_CODE_TO_NAME: dict[str, str] = {
    "region1":  "Tarapacá",
    "region2":  "Antofagasta",
    "region3":  "Atacama",
    "region4":  "Coquimbo",
    "region5":  "Valparaíso",
    "region6":  "O'Higgins",
    "region7":  "Maule",
    "region8":  "Biobío",
    "region9":  "La Araucanía",
    "region10": "Los Lagos",
    "region11": "Aysén",
    "region12": "Magallanes y Antártica Chilena",
    "region13": "Metropolitana de Santiago",
    "region14": "Arica y Parinacota",
    "region15": "Los Ríos",
    "region16": "Ñuble",
}

# Maps lowercase/stripped text forms → region code.
# Multi-region strings and foreign entries are intentionally absent so they
# resolve to None (stored as NULL in the DB).
_TEXT_TO_CODE: dict[str, str] = {
    # --- Full "Región de/del …" forms (EEPP / TEEE fallback) ---
    "región de tarapacá":                                         "region1",
    "región de antofagasta":                                      "region2",
    "región de atacama":                                          "region3",
    "región de coquimbo":                                         "region4",
    "región de valparaíso":                                       "region5",
    "región del libertador general bernardo o'higgins":           "region6",
    "región del libertador general bernardo ohiggins":            "region6",
    "región del libertador gral. bernardo o'higgins":             "region6",
    "región del libertador gral. bernardo ohiggins":              "region6",
    "región del libertador bernardo o'higgins":                   "region6",
    "región del maule":                                           "region7",
    "región del biobío":                                          "region8",
    "región del bío-bío":                                         "region8",
    "región de la araucanía":                                     "region9",
    "región de los lagos":                                        "region10",
    "región de aysén del general carlos ibáñez del campo":        "region11",
    "región de aysén del gral. carlos ibáñez del campo":          "region11",
    "aysén del general carlos ibáñez del campo":                  "region11",
    "aysén del gral. carlos ibáñez del campo":                    "region11",
    "región de magallanes y de la antártica chilena":             "region12",
    "magallanes y de la antártica chilena":                       "region12",
    "región metropolitana de santiago":                           "region13",
    "region metropolitana de santiago":                           "region13",  # no accent
    "región de arica y parinacota":                               "region14",
    "región de los ríos":                                         "region15",
    "región de ñuble":                                            "region16",
    # --- Short / no-prefix forms ---
    "tarapacá":                         "region1",
    "antofagasta":                      "region2",
    "atacama":                          "region3",
    "coquimbo":                         "region4",
    "valparaíso":                       "region5",
    "valparaiso":                       "region5",
    "libertador bernardo o'higgins":    "region6",
    "libertador bernardo ohiggins":     "region6",
    "o'higgins":                        "region6",
    "ohiggins":                         "region6",
    "maule":                            "region7",
    "bío-bío":                          "region8",
    "biobío":                           "region8",
    "biobio":                           "region8",
    "la araucanía":                     "region9",
    "araucanía":                        "region9",
    "los lagos":                        "region10",
    "aysén":                            "region11",
    "aysen":                            "region11",
    "magallanes y antártica chilena":   "region12",
    "metropolitana":                    "region13",
    "metropolitana de santiago":        "region13",
    "arica y parinacota":               "region14",
    "arica-parinacota":                 "region14",
    "los ríos":                         "region15",
    "ñuble":                            "region16",
    # --- Non-accented / typo variants ---
    "region valparaiso":                "region5",
    "tarapaca":                         "region1",
    "coquimbo":                         "region4",
    "la araucanía":                     "region9",
    "araucania":                        "region9",
    "la araucania":                     "region9",
    "aysen del general carlos ibanez del campo": "region11",
    "magallanes":                       "region12",
    "los rios":                         "region15",
    "nuble":                            "region16",
}

# Strings that map explicitly to OTRAS_UBICACIONES instead of NULL.
# These represent known non-geographic or multi-region patterns.
_OTHER_LOCATIONS: frozenset[str] = frozenset({
    "nivel nacional",
    "internacional",
    "extranjero",
    "rm o regiones",
    "otro",
    "otras",
})


def _is_multi_region(text: str) -> bool:
    """Return True if *text* mentions more than one region (comma, slash, ' y ')."""
    stripped = text.strip()
    return (
        "," in stripped
        or "/" in stripped
        or " y " in stripped.lower()
        or " y\n" in stripped.lower()
    )


def normalize_region_from_code(code: str | None) -> str | None:
    """Convert a TEEE ``Codigo Region`` value to a canonical display name.

    The TEEE code ``"otro"`` maps to :data:`OTRAS_UBICACIONES`.
    """
    if not code:
        return None
    key = code.strip().lower()
    if key == "otro":
        return OTRAS_UBICACIONES
    return REGION_CODE_TO_NAME.get(key)


def normalize_region_from_text(text: str | None) -> str | None:
    """Normalize a free-form region string to a canonical display name.

    - Single Chilean region → canonical display name (e.g. ``"Los Lagos"``)
    - Multi-region strings or known non-geographic values → :data:`OTRAS_UBICACIONES`
    - Empty / truly unknown → ``None`` (stored as NULL, excluded from filter)

    The lookup table is checked first so that regions whose names happen to
    contain "y" (e.g. "Arica y Parinacota") are resolved correctly before the
    multi-region heuristic runs.
    """
    if not text:
        return None
    stripped = text.strip()
    # 1. Lookup table first — covers all 16 regions including those with "y"
    code = _TEXT_TO_CODE.get(stripped.lower())
    if code:
        return REGION_CODE_TO_NAME[code]
    # 2. Explicit non-geographic labels
    if stripped.lower() in _OTHER_LOCATIONS:
        return OTRAS_UBICACIONES
    # 3. Heuristic: multi-region string (comma, slash, " y " between unknowns)
    if _is_multi_region(stripped):
        return OTRAS_UBICACIONES
    return None


__all__ = [
    "OTRAS_UBICACIONES",
    "REGION_CODE_TO_NAME",
    "normalize_region_from_code",
    "normalize_region_from_text",
]
