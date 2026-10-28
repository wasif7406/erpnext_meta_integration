"""Turn selected daily Meta spend into an expense and a payable.

One `Meta Expense Entry` per account + period. It links the accounting voucher
(Journal Entry or Purchase Invoice) and stamps every included `Meta Insight`
with its name, which is what makes a second run a no-op.

    Dr  Advertising Expense        (mapped)
    Cr  Payable account (Supplier) (mapped, party = account supplier)
"""

import frappe
from frappe.utils import getdate

from .config import AccountConfig
from .constants import (
	BOOKING_PURCHASE_INVOICE,
	STATUS_BOOKED,
	STATUS_DRAFT,
	STATUS_FAILED,
	STATUS_SKIPPED,
)
from .exceptions import MetaConfigError
from .utils import (
	base_amount,
	booking_window,
	chunked,
	log_error,
	money,
	select_rows,
	total_spend,
)

ENTRY = "Meta Expense Entry"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def selected_entities(account) -> tuple[set, set, set]:
	"""Names of ads / ad sets / campaigns the user flagged for reporting."""
	ads = set(
		frappe.get_all(
			"Meta Ad",
			filters={"meta_account": account, "report_to_erpnext": 1},
			pluck="name",
		)
	)
	ad_sets = set(
		frappe.get_all(
			"Meta Ad Set",
			filters={"meta_account": account, "report_to_erpnext": 1},
			pluck="name",
		)
	)
	campaigns = set(
		frappe.get_all(
			"Meta Campaign",
			filters={"meta_account": account, "report_to_erpnext": 1},
			pluck="name",
		)
	)
	return ads, ad_sets, campaigns


def unbooked_insights(account, from_date, to_date) -> list:
	return frappe.get_all(
		"Meta Insight",
		filters={
			"meta_account": account,
			"date": ("between", [str(from_date)[:10], str(to_date)[:10]]),
			"expense_entry": ("is", "not set"),
		},
		fields=["name", "date", "ad", "ad_name", "ad_set", "campaign", "spend"],
		order_by="date asc",
		limit=5000,
	)


def selected_insights(account, from_date, to_date, start_date=None) -> list:
	window = booking_window(from_date, to_date, start_date)
	if not window:
		return []
	rows = unbooked_insights(account, *window)
	ads, ad_sets, campaigns = selected_entities(account)
	return select_rows(rows, ads, ad_sets, campaigns)


# ---------------------------------------------------------------------------
# Preview (used by the desk dialog)
# ---------------------------------------------------------------------------
def preview(account, from_date, to_date) -> dict:
	config = AccountConfig(account)
	window = booking_window(from_date, to_date, config.expense_start_date)
	rows = selected_insights(account, from_date, to_date, config.expense_start_date)
	total = total_spend(rows)
	existing = _existing_entry(account, from_date, to_date)

	return {
		"account": config.name,
		"company": config.company,
		"from_date": str(from_date)[:10],
		"to_date": str(to_date)[:10],
		"currency": config.currency,
		"exchange_rate": config.exchange_rate,
		"company_currency": config.company_currency,
		"unbooked_rows": len(unbooked_insights(account, *(window or (from_date, to_date)))),
		"selected_rows": len(rows),
		"total": total,
		"base_total": base_amount(total, config.exchange_rate),
		"booking_mode": config.booking_mode,
		"expense_start_date": config.expense_start_date,
		"effective_from": window[0] if window else None,
		"expense_account": config.expense_account,
		"payable_account": config.payable_account,
		"supplier": config.supplier,
		"already_booked": existing,
	}


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
def book_expenses(account, from_date, to_date, posting_date=None, dry_run=False) -> dict:
	from_date = str(from_date)[:10]
	to_date = str(to_date)[:10]
	result = {
		"account": account,
		"from_date": from_date,
		"to_date": to_date,
		"status": STATUS_DRAFT,
		"entry": None,
		"voucher": None,
	}

	try:
		config = AccountConfig(account)
	except MetaConfigError as exc:
		result.update({"status": STATUS_FAILED, "error": str(exc)})
		return result

	if getdate(to_date) < getdate(from_date):
		result.update({"status": STATUS_FAILED, "error": "to_date is before from_date"})
		return result

	existing = _existing_entry(account, from_date, to_date)
	if existing:
		result.update(
			{
				"status": STATUS_SKIPPED,
				"entry": existing,
				"reason": f"period already booked ({existing})",
			}
		)
		return result

	window = booking_window(from_date, to_date, config.expense_start_date)
	if not window:
		result.update(
			{
				"status": STATUS_SKIPPED,
				"reason": f"period ends before the expense start date ({config.expense_start_date})",
			}
		)
		return result
	rows = selected_insights(account, from_date, to_date, config.expense_start_date)
	total = total_spend(rows)
	result["selected_rows"] = len(rows)
	result["total"] = total

	if not rows or total <= 0:
		result.update(
			{
				"status": STATUS_SKIPPED,
				"reason": "no selected, unbooked spend for this period",
			}
		)
		return result

	base_total = base_amount(total, config.exchange_rate)
	result["base_total"] = base_total
	result["currency"] = config.currency

	if dry_run:
		result.update({"status": STATUS_SKIPPED, "reason": "dry run"})
		return result

	try:
		config.validate_for_booking()
	except MetaConfigError as exc:
		result.update({"status": STATUS_FAILED, "error": str(exc)})
		return result

	entry = _create_entry(config, rows, from_date, to_date, posting_date, total, base_total)
	result["entry"] = entry.name

	try:
		voucher = _post_voucher(config, entry)
		entry.db_set("status", STATUS_BOOKED)
		entry.db_set("journal_entry" if voucher["doctype"] == "Journal Entry" else "purchase_invoice", voucher["name"])
		entry.db_set("insight_count", len(rows))
		entry.db_set("total_spend", total)
		entry.db_set("base_amount", base_total)
		_mark_insights(entry.name, [row.name for row in rows])
		frappe.db.commit()
		result.update({"status": STATUS_BOOKED, "voucher": voucher["name"], "voucher_doctype": voucher["doctype"]})
	except Exception as exc:
		frappe.db.rollback()
		_rollback_entry(entry, exc)
		result.update({"status": STATUS_FAILED, "error": str(exc)[:300]})
		log_error(
			"Meta expense booking failed",
			f"{account} {from_date}..{to_date}: {exc}\n{frappe.get_traceback()}",
			ENTRY,
			entry.name,
		)

	return result


def book_all(company=None, month=None) -> dict:
	"""Monthly sweep for accounts that opted in (`enable_auto_booking`)."""
	from .utils import previous_month_bounds

	accounts = frappe.get_all(
		"Meta Account",
		filters={
			"enabled": 1,
			"enable_auto_booking": 1,
			**({"company": company} if company else {}),
		},
		pluck="name",
	)
	from_date, to_date = previous_month_bounds(month)
	out = {"period": [from_date, to_date], "accounts": len(accounts), "results": {}}
	for name in accounts:
		try:
			out["results"][name] = book_expenses(name, from_date, to_date, posting_date=to_date)
		except Exception:
			log_error("Meta monthly booking failed", f"{name}\n{frappe.get_traceback()}")
			out["results"][name] = {"status": STATUS_FAILED}
	return out


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _existing_entry(account, from_date, to_date):
	return frappe.db.get_value(
		ENTRY,
		{
			"meta_account": account,
			"from_date": from_date,
			"to_date": to_date,
			"status": STATUS_BOOKED,
		},
		"name",
	)


def _create_entry(config, rows, from_date, to_date, posting_date, total, base_total):
	entry = frappe.new_doc(ENTRY)
	entry.update(
		{
			"meta_account": config.name,
			"company": config.company,
			"from_date": from_date,
			"to_date": to_date,
			"posting_date": posting_date or to_date,
			"status": STATUS_DRAFT,
			"currency": config.currency,
			"exchange_rate": config.exchange_rate,
			"total_spend": total,
			"base_amount": base_total,
			"expense_account": config.expense_account,
			"payable_account": config.payable_account,
			"supplier": config.supplier,
			"cost_center": config.cost_center,
			"booking_mode": config.booking_mode,
			"insight_count": len(rows),
			"remarks": (
				f"Meta ads spend {from_date} to {to_date} for {config.name} "
				f"({len(rows)} ad-day rows)"
			),
		}
	)
	for row in rows:
		entry.append(
			"insights",
			{
				"date": row.get("date"),
				"ad_id": row.get("ad"),
				"ad_name": row.get("ad_name"),
				"campaign": row.get("campaign"),
				"spend": row.get("spend"),
			},
		)
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	frappe.db.commit()
	return entry


def _post_voucher(config, entry) -> dict:
	if config.booking_mode == BOOKING_PURCHASE_INVOICE:
		return {"doctype": "Purchase Invoice", "name": _make_purchase_invoice(config, entry)}
	return {"doctype": "Journal Entry", "name": _make_journal_entry(config, entry)}


def _make_journal_entry(config, entry) -> str:
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = config.company
	je.posting_date = entry.posting_date
	je.user_remark = (
		f"Meta ads spend {entry.from_date} to {entry.to_date} "
		f"({entry.insight_count} ad-day rows) - {config.name}"
	)
	je.append(
		"accounts",
		{
			"account": config.expense_account,
			"debit_in_account_currency": entry.base_amount,
			"cost_center": config.cost_center,
		},
	)
	je.append(
		"accounts",
		{
			"account": config.payable_account,
			"credit_in_account_currency": entry.base_amount,
			"party_type": "Supplier",
			"party": config.supplier,
			"cost_center": config.cost_center,
		},
	)
	je.flags.ignore_permissions = True
	je.insert(ignore_permissions=True)
	je.submit()
	return je.name


def _make_purchase_invoice(config, entry) -> str:
	pi = frappe.new_doc("Purchase Invoice")
	pi.company = config.company
	pi.supplier = config.supplier
	pi.posting_date = entry.posting_date
	pi.credit_to = config.payable_account
	pi.bill_no = f"{entry.name} ({entry.from_date}..{entry.to_date})"
	pi.bill_date = entry.to_date
	pi.currency = config.company_currency
	pi.remarks = (
		f"Meta ads spend {entry.from_date} to {entry.to_date} "
		f"({entry.insight_count} ad-day rows) - {config.name}"
	)
	pi.append(
		"items",
		{
			"item_code": config.purchase_item,
			"qty": 1,
			"rate": entry.base_amount,
			"expense_account": config.expense_account,
			"cost_center": config.cost_center,
			"description": f"Meta ads spend {entry.from_date} to {entry.to_date}",
		},
	)
	pi.flags.ignore_permissions = True
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi.name


def _mark_insights(entry_name, insight_names):
	"""Stamp the rows we booked; conditional so a second run cannot re-book."""
	for batch in chunked(insight_names, 200):
		placeholders = ", ".join(["%s"] * len(batch))
		frappe.db.sql(
			f"""
			update `tabMeta Insight`
			set expense_entry = %s
			where name in ({placeholders})
			  and (expense_entry is null or expense_entry = '')
			""",
			[entry_name, *batch],
		)


def _rollback_entry(entry, exc):
	try:
		frappe.db.set_value(
			ENTRY,
			entry.name,
			{
				"status": STATUS_FAILED,
				"remarks": f"{entry.remarks}\nFailed: {str(exc)[:400]}",
			},
			update_modified=False,
		)
		frappe.db.commit()
	except Exception:
		log_error("Meta: could not mark expense entry failed", f"{entry.name}\n{frappe.get_traceback()}")


# ---------------------------------------------------------------------------
def account_has_selection(account) -> bool:
	ads, ad_sets, campaigns = selected_entities(account)
	return bool(ads or ad_sets or campaigns)


def release_entry(entry_name: str) -> dict:
	"""Un-stamp an entry whose voucher was cancelled, so the period can be re-booked.

	Cancelling a Journal Entry reverses the GL but does not tell us anything, so
	this is the explicit step: the voucher must be cancelled first.
	"""
	entry = frappe.get_doc(ENTRY, entry_name)
	if entry.status != STATUS_BOOKED:
		return {"status": STATUS_SKIPPED, "reason": f"entry is {entry.status}"}

	voucher_doctype = "Journal Entry" if entry.journal_entry else "Purchase Invoice"
	voucher = entry.journal_entry or entry.purchase_invoice
	if voucher:
		docstatus = frappe.db.get_value(voucher_doctype, voucher, "docstatus")
		if docstatus != 2:
			frappe.throw(
				f"{voucher_doctype} {voucher} is not cancelled. Cancel it first, "
				"then release the entry."
			)

	frappe.db.sql(
		"update `tabMeta Insight` set expense_entry = null where expense_entry = %s",
		entry.name,
	)
	entry.db_set("status", STATUS_DRAFT)
	entry.db_set("journal_entry", None)
	entry.db_set("purchase_invoice", None)
	entry.db_set(
		"remarks",
		f"{entry.remarks}\nReleased for re-booking after cancelling {voucher or 'the voucher'}.",
	)
	frappe.db.commit()
	return {"status": STATUS_DRAFT, "entry": entry.name}


def open_period_summary(account, from_date, to_date) -> list:
	"""Spend grouped by campaign, for the preview dialog."""
	config = AccountConfig(account)
	rows = selected_insights(account, from_date, to_date, config.expense_start_date)
	grouped = {}
	for row in rows:
		key = row.get("campaign") or "-"
		grouped[key] = money(grouped.get(key, 0) + (row.get("spend") or 0))
	return [
		{"campaign": key, "spend": value}
		for key, value in sorted(grouped.items(), key=lambda item: -item[1])
	]
