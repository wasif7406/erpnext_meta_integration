"""Shared helpers: money, dates, sync windows."""

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from .constants import DEFAULT_SYNC_DAYS


def money(value) -> float:
	return flt(value, 2)


def insight_key(ad_id: str, day: str) -> str:
	"""Stable key for one ad's spend on one day (daily insights are unique)."""
	return f"{ad_id}-{str(day)[:10]}"


def base_amount(amount, exchange_rate) -> float:
	"""Convert ad-account currency to company currency."""
	return money(flt(amount) * flt(exchange_rate or 1))


def month_bounds(day=None) -> tuple:
	day = getdate(day or nowdate())
	first = day.replace(day=1)
	next_month = getdate(add_days(first, 32)).replace(day=1)
	last = getdate(add_days(next_month, -1))
	return str(first), str(last)


def previous_month_bounds(day=None) -> tuple:
	day = getdate(day or nowdate())
	first_of_this = day.replace(day=1)
	return month_bounds(getdate(add_days(first_of_this, -1)))


def sync_window(days=None, until=None) -> tuple:
	until = str(until or nowdate())[:10]
	days = max(1, min(int(days or DEFAULT_SYNC_DAYS), 400))
	return str(add_days(until, -(days - 1)))[:10], until


def clamp_window(from_date, to_date, start_date=None):
	"""Clip a requested period to the account's cutover date.

	Spend before `start_date` belongs to a period the books already cover, so the
	report must not include it. Returns None when the whole period predates it.
	"""
	start = str(from_date)[:10]
	end = str(to_date)[:10]
	if start_date and str(start_date)[:10] > start:
		start = str(start_date)[:10]
	if start > end:
		return None
	return start, end


def meta_datetime(value):
	"""Meta returns `2026-09-27T16:29:59+0500`; MySQL wants `YYYY-MM-DD HH:MM:SS`.

	The offset is dropped: these fields are informational (start/end times).
	"""
	text = str(value or "").strip()
	if not text:
		return None
	text = text[:19].replace("T", " ")
	return text if len(text) == 19 else None


def now():
	return now_datetime()


def chunked(items, size=200):
	items = list(items)
	for start in range(0, len(items), size):
		yield items[start : start + size]


def log_error(title: str, message: str, reference_doctype=None, reference_name=None):
	frappe.log_error(
		title=title[:140],
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def snippet(value, limit=600) -> str:
	try:
		return str(value)[:limit]
	except Exception:
		return "<unprintable>"
