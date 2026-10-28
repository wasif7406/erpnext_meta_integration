"""Shared helpers: money, dates, and the pure insight-selection logic."""

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from .constants import DEFAULT_SYNC_DAYS


# ---------------------------------------------------------------------------
# Money / dates
# ---------------------------------------------------------------------------
def money(value) -> float:
	return flt(value, 2)


def insight_key(ad_id: str, day: str) -> str:
	"""Stable key for one ad's spend on one day (daily insights are unique).

	No special characters: the key is also the document name.
	"""
	return f"{ad_id}-{str(day)[:10]}"


def base_amount(amount, exchange_rate) -> float:
	"""Convert ad-account currency to company currency."""
	return money(flt(amount) * flt(exchange_rate or 1))


def month_bounds(day=None) -> tuple[str, str]:
	"""First and last day of the month containing `day`."""
	day = getdate(day or nowdate())
	first = day.replace(day=1)
	next_month = getdate(add_days(first, 32)).replace(day=1)
	last = getdate(add_days(next_month, -1))
	return str(first), str(last)


def previous_month_bounds(day=None) -> tuple[str, str]:
	day = getdate(day or nowdate())
	first_of_this = day.replace(day=1)
	last_of_previous = getdate(add_days(first_of_this, -1))
	return month_bounds(last_of_previous)


def sync_window(days=None, until=None) -> tuple[str, str]:
	until = str(until or nowdate())[:10]
	days = int(days or DEFAULT_SYNC_DAYS)
	days = max(1, min(days, 400))
	since = str(add_days(until, -(days - 1)))[:10]
	return since, until


def now():
	return now_datetime()


def meta_datetime(value) -> str | None:
	"""Meta timestamps are ISO-8601 with a numeric offset, e.g.
	`2026-09-27T16:29:59+0500`. Frappe/MySQL want `YYYY-MM-DD HH:MM:SS`, so keep
	the wall-clock part (ad-account local time) and drop the offset — these fields
	are informational (campaign/ad set start and end).
	"""
	text = str(value or "").strip()
	if not text:
		return None
	text = text[:19].replace("T", " ")
	return text if len(text) == 19 else None


def chunked(items, size=200):
	items = list(items)
	for start in range(0, len(items), size):
		yield items[start : start + size]


# ---------------------------------------------------------------------------
# Selection (pure: no database access, unit-tested directly)
# ---------------------------------------------------------------------------
def row_is_selected(row, selected_ads, selected_ad_sets, selected_campaigns) -> bool:
	"""Decide whether a spend row is reported to ERPNext.

	The most specific selection wins, and any selected ancestor includes its
	children — selecting a campaign reports every ad under it.
	"""
	ad = row.get("ad")
	if ad and ad in selected_ads:
		return True

	ad_set = row.get("ad_set")
	if ad_set and ad_set in selected_ad_sets:
		return True

	campaign = row.get("campaign")
	if campaign and campaign in selected_campaigns:
		return True

	return False


def select_rows(rows, selected_ads, selected_ad_sets, selected_campaigns):
	return [
		row
		for row in rows
		if row_is_selected(row, selected_ads, selected_ad_sets, selected_campaigns)
	]


def booking_window(from_date, to_date, start_date=None):
	"""Clip a requested period to the account's expense start date.

	Anything before `start_date` is already in the ledger (booked manually or by
	the previous system), so it must never be booked again. Returns None when the
	whole period predates the cutover.
	"""
	start = str(from_date)[:10]
	end = str(to_date)[:10]
	if start_date and str(start_date)[:10] > start:
		start = str(start_date)[:10]
	if start > end:
		return None
	return start, end


def total_spend(rows) -> float:
	return money(sum(flt(row.get("spend")) for row in rows))


# ---------------------------------------------------------------------------
# Frappe helpers
# ---------------------------------------------------------------------------
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
