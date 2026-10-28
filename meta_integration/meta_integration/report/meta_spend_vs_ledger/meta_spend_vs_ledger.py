import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, nowdate

from meta_integration.reconciliation import merge_reconciliation


def execute(filters=None):
	filters = frappe._dict(filters or {})
	to_date = getdate(filters.get("to_date") or nowdate())
	from_date = getdate(filters.get("from_date") or add_months(to_date, -6))
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	accounts = _accounts(filters)
	if not accounts:
		return get_columns(), []

	rates = {a.name: (flt(a.exchange_rate) or 1.0) for a in accounts}
	cutovers = {
		a.name: str(a.expense_start_date)[:10] for a in accounts if a.get("expense_start_date")
	}

	spend = _spend_rows(filters, from_date, to_date, rates, cutovers)
	booked = _ledger_rows(filters, from_date, to_date)
	rows = merge_reconciliation(spend, booked, cutovers=cutovers)

	if not rows:
		frappe.msgprint(
			_(
				"No spend and no ledger entries in this period. Check the dates, or set "
				"the account's Expense Start Date to when Meta data begins."
			),
			indicator="orange",
			alert=True,
		)
	return get_columns(), rows


def get_columns():
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 90},
		{
			"label": _("Meta Account"),
			"fieldname": "meta_account",
			"fieldtype": "Link",
			"options": "Meta Account",
			"width": 170,
		},
		{
			"label": _("Meta Spend"),
			"fieldname": "insight_spend",
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"label": _("Booked in Ledger"),
			"fieldname": "booked",
			"fieldtype": "Currency",
			"width": 150,
		},
		{"label": _("Difference"), "fieldname": "difference", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Cumulative Difference"),
			"fieldname": "cumulative_difference",
			"fieldtype": "Currency",
			"width": 175,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 170},
	]


# ---------------------------------------------------------------------------
def _accounts(filters):
	conditions = {"enabled": 1}
	if filters.get("company"):
		conditions["company"] = filters.get("company")
	if filters.get("meta_account"):
		conditions["name"] = filters.get("meta_account")
	return frappe.get_all(
		"Meta Account",
		filters=conditions,
		fields=["name", "company", "currency", "exchange_rate", "expense_account", "expense_start_date"],
		limit=200,
	)


def _spend_rows(filters, from_date, to_date, rates, cutovers):
	conditions = ["date between %(from_date)s and %(to_date)s"]
	if filters.get("meta_account"):
		conditions.append("meta_account = %(meta_account)s")
	if filters.get("company"):
		conditions.append("company = %(company)s")
	where = " and ".join(conditions)

	rows = frappe.db.sql(
		f"""
		select date_format(date, '%%Y-%%m') as month,
		       meta_account,
		       sum(spend) as spend
		from `tabMeta Insight`
		where {where}
		group by month, meta_account
		""",
		{
			"from_date": from_date,
			"to_date": to_date,
			"meta_account": filters.get("meta_account"),
			"company": filters.get("company"),
		},
		as_dict=True,
	)

	out = []
	for row in rows:
		cutover = cutovers.get(row.meta_account)
		if cutover and str(row.month) < str(cutover)[:7]:
			continue  # months the books already cover elsewhere
		rate = rates.get(row.meta_account, 1.0)
		out.append(
			{
				"month": row.month,
				"meta_account": row.meta_account,
				"spend": flt(row.spend) * rate,
			}
		)
	return out


def _ledger_rows(filters, from_date, to_date):
	"""Anything that hit the mapped advertising expense account counts as booked."""
	conditions = [
		"gl.is_cancelled = 0",
		"gl.posting_date between %(from_date)s and %(to_date)s",
		"acc.expense_account is not null",
		"acc.expense_account != ''",
	]
	if filters.get("meta_account"):
		conditions.append("acc.name = %(meta_account)s")
	if filters.get("company"):
		conditions.append("acc.company = %(company)s")
	where = " and ".join(conditions)

	return frappe.db.sql(
		f"""
		select date_format(gl.posting_date, '%%Y-%%m') as month,
		       acc.name as meta_account,
		       sum(gl.debit - gl.credit) as booked
		from `tabGL Entry` gl
		join `tabMeta Account` acc
		  on acc.expense_account = gl.account and acc.company = gl.company
		where {where}
		group by month, acc.name
		""",
		{
			"from_date": from_date,
			"to_date": to_date,
			"meta_account": filters.get("meta_account"),
			"company": filters.get("company"),
		},
		as_dict=True,
	)
