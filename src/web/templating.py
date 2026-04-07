"""Shared Jinja2 templates instance."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime


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


def _format_date(value: datetime | None) -> str:
	"""Format a datetime to local readable string.

	- If value is None -> em dash
	- If time portion is 00:00 -> show only date `DD/MM/YYYY`
	- Otherwise show `DD/MM/YYYY HH:MM`
	"""
	if value is None:
		return "—"
	try:
		if isinstance(value, datetime):
			dt = value
		else:
			dt = datetime.fromisoformat(str(value))
	except Exception:
		return "—"
	if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
		return dt.strftime("%d/%m/%Y")
	return dt.strftime("%d/%m/%Y %H:%M")

def _format_date_only(value: datetime | None) -> str:
	"""Format a datetime to date-only string DD/MM/YYYY. Ignores time portion."""
	if value is None:
		return "—"
	try:
		dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
		return dt.strftime("%d/%m/%Y")
	except Exception:
		return "—"

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Register custom filter for CLP formatting
templates.env.filters["clp"] = _format_clp
templates.env.filters["fmt_date"] = _format_date
templates.env.filters["fmt_date_only"] = _format_date_only
