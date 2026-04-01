"""Shared Jinja2 templates instance."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from decimal import Decimal, ROUND_HALF_UP


def _format_clp(value: Decimal | None) -> str:
	"""Format a Decimal as Chilean peso (CLP) with dot thousands separator.

	Examples:
		Decimal('1234567.00') -> "$1.234.567"
		None -> "—"
	"""
	if value is None:
		return "—"
	try:
		# Round to nearest peso
		amt = int(value.to_integral_value(rounding=ROUND_HALF_UP))
	except Exception:
		return "—"
	# Use comma thousands then replace with dot for CLP style
	return f"${{:,}}".format(amt).replace(",", ".")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Register custom filter for CLP formatting
templates.env.filters["clp"] = _format_clp
