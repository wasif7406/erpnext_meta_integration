"""Billing-driven expense: the card charge becomes a Purchase Invoice.

Meta does not expose invoices or payment cycles for card-funded ad accounts
(verified: `adspaymentcycles`, `transactions` and `invoices` all return 400), so
the billing evidence is the card / statement line. The flow is therefore:

    Meta Billing  ->  Purchase Invoice   (Dr Advertising Expense / Cr Creditors)
                  ->  Payment Entry      (settled from the bank or wallet feed)

Daily spend stays in `Meta Insight` for analytics only.
"""

import frappe
from frappe.utils import flt, nowdate

from .config import AccountConfig
from .constants import RECOGNITION_BILLING
from .exceptions import MetaConfigError

BILLING = "Meta Billing"


def record_billing(
	account,
	billing_date=None,
	amount=0,
	currency=None,
	exchange_rate=None,
	reference=None,
	period_from=None,
	period_to=None,
	remarks=None,
):
	"""Create a draft Meta Billing entry for one card charge / invoice."""
	config = AccountConfig(account)
	doc = frappe.get_doc(
		{
			"doctype": BILLING,
			"meta_account": config.name,
			"company": config.company,
			"billing_date": str(billing_date or nowdate())[:10],
			"amount": flt(amount),
			"currency": currency or config.currency,
			"exchange_rate": flt(exchange_rate or config.exchange_rate) or 1,
			"reference": reference,
			"period_from": period_from,
			"period_to": period_to,
			"remarks": remarks,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def post_purchase_invoice(billing: str) -> dict:
	"""Create and submit the Purchase Invoice for a billing entry."""
	doc = frappe.get_doc(BILLING, billing)
	if doc.purchase_invoice:
		return {"status": "Skipped", "reason": f"already billed ({doc.purchase_invoice})"}

	config = AccountConfig(doc.meta_account)
	config.validate_for_booking()
	if not config.purchase_item:
		raise MetaConfigError(
			"Set a Purchase Item (a non-stock service item) on the Meta Account first; "
			"a Purchase Invoice needs a line item."
		)

	pi = frappe.get_doc(
		{
			"doctype": "Purchase Invoice",
			"company": config.company,
			"supplier": config.supplier,
			"posting_date": doc.billing_date,
			"credit_to": config.payable_account,
			"bill_no": doc.reference or doc.name,
			"bill_date": doc.billing_date,
			"currency": config.company_currency,
			"remarks": (
				f"Meta ads charge {doc.billing_date}"
				+ (f" ({doc.period_from}..{doc.period_to})" if doc.period_from else "")
				+ f" - {config.name}"
				+ (f" - ref {doc.reference}" if doc.reference else "")
			),
		}
	)
	pi.append(
		"items",
		{
			"item_code": config.purchase_item,
			"qty": 1,
			"rate": doc.base_amount,
			"expense_account": config.expense_account,
			"cost_center": config.cost_center,
			"description": f"Meta ads charge {doc.billing_date}",
		},
	)
	pi.flags.ignore_permissions = True
	pi.insert(ignore_permissions=True)
	pi.submit()

	doc.db_set("purchase_invoice", pi.name)
	doc.db_set("status", "Billed")
	frappe.db.commit()

	if config.expense_recognition and config.expense_recognition != RECOGNITION_BILLING:
		frappe.msgprint(
			f"Note: {config.name} is set to accrual recognition; this invoice is still posted.",
			indicator="orange",
			alert=True,
		)

	return {
		"status": "Billed",
		"billing": doc.name,
		"purchase_invoice": pi.name,
		"grand_total": pi.grand_total,
	}
