"""Billing-driven expense: one entry per card / wallet charge.

Meta exposes no invoices or payment transactions for card-funded accounts
(`adspaymentcycles`, `adspaymentcycle`, `transactions`, `invoices` all return
HTTP 400 — verified against the live account), so the card statement is the
billing evidence. Two shapes, chosen per entry:

  Already paid (default)  Dr Advertising Expense / Cr <card|wallet|owner account>
                          One Journal Entry. Money already left, so no payable
                          and no Payment Entry are needed.

  On credit               Purchase Invoice -> Creditors (party = supplier), then a
                          Payment Entry when the invoice is actually paid.

Daily spend stays in `Meta Insight` for analytics only; nothing here reads it.
"""

import frappe
from frappe.utils import flt, nowdate

from .config import AccountConfig
from .exceptions import MetaConfigError

BILLING = "Meta Billing"

DIRECT = "Already paid (direct)"
CREDIT = "On credit (Purchase Invoice)"

STATUS_POSTED = "Posted"
STATUS_INVOICED = "Invoiced"


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
	"""Create a draft Meta Billing entry for one charge."""
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
			"payment_mode": payment_mode or DIRECT,
			"paid_from": paid_from or config.default_paid_from,
			"remarks": remarks,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


def post_billing(billing: str) -> dict:
	"""Post the entry: Journal Entry (already paid) or Purchase Invoice (on credit)."""
	doc = frappe.get_doc(BILLING, billing)
	if doc.journal_entry:
		return {"status": "Skipped", "reason": f"already posted ({doc.journal_entry})"}
	if doc.purchase_invoice:
		return {"status": "Skipped", "reason": f"already invoiced ({doc.purchase_invoice})"}

	config = AccountConfig(doc.meta_account)
	if doc.payment_mode == CREDIT:
		return _post_purchase_invoice(config, doc)
	return _post_direct(config, doc)


# ---------------------------------------------------------------------------
def _post_direct(config, doc) -> dict:
	"""The charge already left an account: Dr Expense / Cr that account."""
	if not doc.paid_from:
		raise MetaConfigError(
			"Set 'Paid From' on the billing entry — the card, wallet or owner account "
			"the charge actually left."
		)

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": config.company,
			"posting_date": doc.billing_date,
			"user_remark": (
				f"Meta ads charge {doc.billing_date}"
				+ (f" ({doc.period_from}..{doc.period_to})" if doc.period_from else "")
				+ f" - {config.name}"
				+ (f" - ref {doc.reference}" if doc.reference else "")
			),
			"accounts": [
				{
					"account": config.expense_account,
					"debit_in_account_currency": doc.base_amount,
					"cost_center": config.cost_center,
				},
				{
					"account": doc.paid_from,
					"credit_in_account_currency": doc.base_amount,
					"cost_center": config.cost_center,
				},
			],
		}
	)
	je.flags.ignore_permissions = True
	je.insert(ignore_permissions=True)
	je.submit()

	doc.db_set("journal_entry", je.name)
	doc.db_set("status", STATUS_POSTED)
	frappe.db.commit()
	return {
		"status": STATUS_POSTED,
		"billing": doc.name,
		"journal_entry": je.name,
		"amount": je.total_debit,
	}


def _post_purchase_invoice(config, doc) -> dict:
	"""Facebook/agency granted terms: bill it, settle later with a Payment Entry."""
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
	doc.db_set("status", STATUS_INVOICED)
	frappe.db.commit()
	return {
		"status": STATUS_INVOICED,
		"billing": doc.name,
		"purchase_invoice": pi.name,
		"grand_total": pi.grand_total,
	}
