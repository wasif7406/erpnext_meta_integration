"""Whitelisted endpoints used by buttons and bench execute."""

import frappe
from frappe import _

from . import reporting, sync
from .config import get_account
from .exceptions import MetaConfigError
from .tasks import run_locked

WRITE_ROLES = ("System Manager", "Accounts Manager", "Accounts User")


@frappe.whitelist()
def sync_now(account=None, company=None, days=None, background=0):
	"""Refresh entities + spend for one account, or every account of a company."""
	frappe.only_for(WRITE_ROLES)
	accounts = _resolve_accounts(account, company)
	if not accounts:
		frappe.throw(_("No enabled Meta Account found for the given company/account."))

	if frappe.utils.cint(background):
		for name in accounts:
			frappe.enqueue(
				"meta_integration.sync.sync_account",
				queue="long",
				timeout=1800,
				job_name=f"meta-sync-{name}",
				account=name,
				days=days,
			)
		return {"queued": accounts}

	results = {}
	for name in accounts:
		results[name] = run_locked("sync", name, sync.sync_account, days=days)
	return results


@frappe.whitelist()
def preview_expenses(account, from_date, to_date):
	"""Totals for the booking dialog: what would be posted, nothing is written."""
	frappe.only_for(WRITE_ROLES)
	_get(account)
	try:
		data = reporting.preview(account, from_date, to_date)
	except MetaConfigError as exc:
		return {"error": str(exc)}
	data["campaigns"] = reporting.open_period_summary(account, from_date, to_date)[:25]
	return data


@frappe.whitelist()
def book_expenses(account, from_date, to_date, posting_date=None, dry_run=0):
	"""Create the expense entry (and its voucher) for the selected spend."""
	frappe.only_for(WRITE_ROLES)
	_get(account)
	return run_locked(
		"book",
		account,
		reporting.book_expenses,
		from_date=from_date,
		to_date=to_date,
		posting_date=posting_date,
		dry_run=bool(frappe.utils.cint(dry_run)),
	)


@frappe.whitelist()
def book_previous_month(account, posting_date=None):
	"""Convenience wrapper for the account form button."""
	frappe.only_for(WRITE_ROLES)
	_get(account)
	from .utils import previous_month_bounds

	from_date, to_date = previous_month_bounds()
	return run_locked(
		"book",
		account,
		reporting.book_expenses,
		from_date=from_date,
		to_date=to_date,
		posting_date=posting_date or to_date,
	)


@frappe.whitelist()
def release_entry(entry):
	"""Un-stamp a booked period whose voucher was cancelled (then re-book it)."""
	frappe.only_for(WRITE_ROLES)
	return reporting.release_entry(entry)


# ---------------------------------------------------------------------------
def _get(account):
	if not account:
		frappe.throw(_("A Meta Account is required."))
	return get_account(account)


def _resolve_accounts(account, company):
	if account:
		return [get_account(account).name]
	if company:
		return frappe.get_all(
			"Meta Account",
			filters={"company": company, "enabled": 1},
			pluck="name",
			order_by="is_default desc",
		)
	return frappe.get_all("Meta Account", filters={"enabled": 1}, pluck="name")
