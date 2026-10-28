import frappe
from frappe import _
from frappe.utils import flt, getdate

from meta_integration.reconciliation import merge_reconciliation


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or frappe.utils.add_months(frappe.utils.nowdate(), -6))
	to_date = getdate(filters.get("to_date") or frappe.utils.nowdate())
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	rows = merge_reconciliation(
		_spend_rows(filters, from_date, to_date), _charge_rows(filters, from_date, to_date)
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
			"width": 160,
		},
		{
			"label": _("Insight Spend"),
			"fieldname": "insight_spend",
			"fieldtype": "Currency",
			"width": 140,
		},
		{"label": _("Charges Posted"), "fieldname": "charged", "fieldtype": "Currency", "width": 140},
		{"label": _("Difference"), "fieldname": "difference", "fieldtype": "Currency", "width": 130},
		{"label": _("Draft Entries"), "fieldname": "drafts", "fieldtype": "Int", "width": 110},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 150},
	]


def _spend_rows(filters, from_date, to_date):
	conditions = ["date between %(from_date)s and %(to_date)s"]
	if filters.get("meta_account"):
		conditions.append("meta_account = %(meta_account)s")
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
		{"from_date": from_date, "to_date": to_date, "meta_account": filters.get("meta_account")},
		as_dict=True,
	)

	rates = _account_rates()

	out = []
	for row in rows:
		currency, rate = rates.get(row.meta_account, (None, 1.0))
		rate = flt(rate) or 1.0
		out.append({"month": row.month, "meta_account": row.meta_account, "spend": flt(row.spend) * rate})
	return out


def _charge_rows(filters, from_date, to_date):
	conditions = ["billing_date between %(from_date)s and %(to_date)s"]
	if filters.get("meta_account"):
		conditions.append("meta_account = %(meta_account)s")
	if filters.get("company"):
		conditions.append("company = %(company)s")
	where = " and ".join(conditions)

	return frappe.db.sql(
		f"""
		select date_format(billing_date, '%%Y-%%m') as month,
		       meta_account,
		       sum(case when status in ('Posted', 'Invoiced') then base_amount else 0 end) as charged,
		       sum(case when status = 'Draft' then 1 else 0 end) as drafts
		from `tabMeta Billing`
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


def _account_rates():
	"""Spend is in the ad-account currency; convert it to company currency."""
	rows = frappe.get_all(
		"Meta Account", fields=["name", "currency", "exchange_rate"], limit=200
	)
	return {row.name: (row.currency, row.exchange_rate or 1) for row in rows}
