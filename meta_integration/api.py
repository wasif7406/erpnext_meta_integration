"""Read-only endpoints. This app never posts to the ledger."""

import frappe
from frappe import _

from . import sync
from .config import get_account
from .tasks import run_locked

ROLES = ("System Manager", "Accounts Manager", "Accounts User")


@frappe.whitelist()
def sync_now(account=None, company=None, days=None, background=0):
	"""Refresh campaigns/ad sets/ads and daily spend. Nothing is posted."""
	frappe.only_for(ROLES)
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
def health():
	"""Which code is this site actually running? (deploy verification)"""
	import meta_integration as package

	from .constants import BUILD

	return {
		"app": "meta_integration",
		"version": package.__version__,
		"build": BUILD,
		"read_only": True,
	}


# ---------------------------------------------------------------------------
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
