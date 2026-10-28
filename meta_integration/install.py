"""Install hooks. Nothing is hard-coded and no fixtures are shipped."""

import frappe

MODULE = "Meta Integration"
APP = "meta_integration"


def before_install():
	_ensure_module_def()
	frappe.db.commit()


def after_install():
	print(
		"\nMeta Integration installed (read-only: it never posts to the ledger).\n"
		"Next steps:\n"
		"  1. Create a Meta Account per company (Meta Integration > Meta Account).\n"
		"  2. Paste the access token (system user / long-lived) and the Ad Account ID.\n"
		"  3. Set the Advertising Expense account (the one you book ad spend to) and\n"
		"     'Data Starts On' — the date Meta spend becomes comparable to the books.\n"
		"  4. Click 'Sync now'; spend lands in Meta Insight for analysis.\n"
		"  5. Book the card/wallet charge yourself (manual JE) and check the month in\n"
		"     the 'Meta Spend vs Ledger' report.\n"
	)


def after_migrate():
	"""Nothing to migrate; keep it defensive so it can never abort a migrate."""
	try:
		frappe.clear_cache()
	except Exception:
		frappe.log_error(
			title="Meta: after_migrate failed",
			message=frappe.get_traceback(),
		)


# ---------------------------------------------------------------------------
def _ensure_module_def():
	if frappe.db.exists("Module Def", MODULE):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "Module Def",
				"module_name": MODULE,
				"app_name": APP,
				"custom": 0,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error("Meta: could not create Module Def", frappe.get_traceback())
