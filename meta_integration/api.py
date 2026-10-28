"""Whitelisted endpoints used by buttons and bench execute."""

import frappe
from frappe import _

from . import billing as billing_module
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


@frappe.whitelist()
def record_billing(
	account,
	billing_date=None,
	amount=0,
	currency=None,
	exchange_rate=None,
	reference=None,
	period_from=None,
	period_to=None,
	payment_mode=None,
	paid_from=None,
	remarks=None,
):
	"""Record one Meta card / wallet charge (billing recognition)."""
	frappe.only_for(WRITE_ROLES)
	_get(account)
	name = billing_module.record_billing(
		account,
		billing_date=billing_date,
		amount=amount,
		currency=currency,
		exchange_rate=exchange_rate,
		reference=reference,
		period_from=period_from,
		period_to=period_to,
		payment_mode=payment_mode,
		paid_from=paid_from,
		remarks=remarks,
	)
	return {"billing": name}


@frappe.whitelist()
def post_billing(billing):
	"""Post a Meta Billing entry: Journal Entry (already paid) or Purchase Invoice (credit)."""
	frappe.only_for(WRITE_ROLES)
	return billing_module.post_billing(billing)


@frappe.whitelist()
def health():
	"""Which code is this site actually running? (deploy verification)"""
	import meta_integration as package

	from .constants import BUILD

	return {
		"app": "meta_integration",
		"version": package.__version__,
		"build": BUILD,
	}


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
