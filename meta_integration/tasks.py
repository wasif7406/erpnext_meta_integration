"""Scheduled entry points and the per-account lock helper."""

import frappe


def sync_all_accounts():
	"""Daily: refresh campaigns/ad sets/ads and the last N days of spend."""
	for row in _enabled_accounts():
		try:
			frappe.enqueue(
				"meta_integration.sync.sync_account",
				queue="long",
				timeout=1800,
				is_async=True,
				job_name=f"meta-sync-{row.name}",
				account=row.name,
			)
		except Exception:
			frappe.log_error(
				title="Meta enqueue failed",
				message=f"{row.name}\n{frappe.get_traceback()}",
			)


def prune_logs():
	from frappe.utils import add_days, nowdate

	cutoff = add_days(nowdate(), -180)
	try:
		names = frappe.get_all(
			"Meta Sync Run", filters={"creation": ("<", cutoff)}, pluck="name", limit=5000
		)
		for name in names:
			frappe.delete_doc("Meta Sync Run", name, force=True, ignore_permissions=True)
		if names:
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="Meta log pruning failed",
			message=frappe.get_traceback(),
		)


# ---------------------------------------------------------------------------
def _enabled_accounts():
	return frappe.get_all(
		"Meta Account", filters={"enabled": 1, "enable_sync": 1}, fields=["name", "company"]
	)


def run_locked(kind, account_name, fn, **kwargs):
	"""Run `fn(account_name, **kwargs)` under a per-account, per-kind file lock."""
	from frappe.utils.synchronization import filelock

	try:
		from frappe.exceptions import LockTimeoutError
	except ImportError:  # very old Frappe
		from frappe.utils.synchronization import LockTimeoutError  # type: ignore

	try:
		with filelock(f"meta-{kind}-{account_name}", timeout=0):
			return fn(account_name, **kwargs)
	except LockTimeoutError:
		return {"status": "Skipped", "reason": f"{kind} already running for {account_name}"}
