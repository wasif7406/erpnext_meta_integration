"""Install hooks. Nothing is hard-coded and no fixtures are shipped."""

import frappe

MODULE = "Meta Integration"
APP = "meta_integration"


def before_install():
	_ensure_module_def()
	frappe.db.commit()


def after_install():
	print(
		"\nMeta Integration installed.\n"
		"Next steps:\n"
		"  1. Create a Meta Account per company (Meta Integration > Meta Account).\n"
		"     Rarely a company needs several (one ad account each).\n"
		"  2. Map the Advertising Expense and Payable accounts, pick a Supplier,\n"
		"     and set the exchange rate if the ad account currency differs.\n"
		"  3. Paste the access token (system user / long-lived token) and Ad Account ID.\n"
		"  4. Click 'Sync now' on the account, then tick the campaigns / ad sets /\n"
		"     ads whose spend should be reported to ERPNext.\n"
		"  5. Use 'Book expenses' to post the selected spend as expense + payable.\n"
	)


def after_migrate():
	frappe.clear_cache()


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
