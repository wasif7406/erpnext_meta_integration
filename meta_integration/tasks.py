"""Scheduled entry points and the per-account lock helper."""

import frappe


def sync_all_accounts():
	"""Daily: refresh campaigns/ad sets/ads and the last N days of spend."""
	_enqueue_for_all("meta_integration.sync.sync_account", "meta-sync")


def book_previous_month():
	"""Monthly (1st): book last month for accounts that opted in."""
	from .reporting import book_all

	try:
		book_all()
	except Exception:
		frappe.log_error(
			title="Meta monthly booking failed",
			message=frappe.get_traceback(),
		)


def prune_logs():
	from frappe.utils import add_days, nowdate

	cutoff = add_days(nowdate(), -180)
	for doctype in ("Meta Sync Run",):
		try:
			names = frappe.get_all(
				doctype, filters={"creation": ("<", cutoff)}, pluck="name", limit=5000
			)
			for name in names:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			if names:
				frappe.db.commit()
		except Exception:
			frappe.log_error(
				title="Meta log pruning failed",
				message=f"{doctype}\n{frappe.get_traceback()}",
			)


# ---------------------------------------------------------------------------
def _enabled_accounts():
	return frappe.get_all(
		"Meta Account",
		filters={"enabled": 1, "enable_sync": 1},
		fields=["name", "company"],
	)


def _enqueue_for_all(method, job_prefix):
	for row in _enabled_accounts():
		try:
			frappe.enqueue(
				method,
				queue="long",
				timeout=1800,
				is_async=True,
				job_name=f"{job_prefix}-{row.name}",
				account=row.name,
			)
		except Exception:
			frappe.log_error(
				title="Meta enqueue failed",
				message=f"{method} / {row.name}\n{frappe.get_traceback()}",
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
