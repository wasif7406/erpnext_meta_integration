import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from meta_integration.billing import CREDIT
from meta_integration.config import AccountConfig


class MetaBilling(Document):
	def validate(self):
		config = AccountConfig(self.meta_account)
		self.company = config.company
		self.expense_account = config.expense_account
		self.payable_account = config.payable_account
		self.supplier = config.supplier
		self.cost_center = config.cost_center
		if not self.payment_mode:
			self.payment_mode = "Already paid (direct)"
		if not self.paid_from and self.payment_mode != CREDIT:
			self.paid_from = config.default_paid_from
		if not self.currency:
			self.currency = config.currency
		if not flt(self.exchange_rate):
			self.exchange_rate = config.exchange_rate or 1
		self.base_amount = flt(flt(self.amount) * flt(self.exchange_rate), 2)
		self.validate_paid_from()

	def validate_paid_from(self):
		if self.payment_mode == CREDIT or not self.paid_from:
			return
		meta = frappe.db.get_value(
			"Account", self.paid_from, ["company", "is_group"], as_dict=True
		)
		if not meta:
			frappe.throw(_("Paid From account {0} does not exist.").format(self.paid_from))
		if meta.company != self.company:
			frappe.throw(
				_("Paid From account {0} belongs to {1}, not {2}.").format(
					self.paid_from, meta.company, self.company
				)
			)
		if meta.is_group:
			frappe.throw(_("Paid From must be a leaf account."))

	def on_trash(self):
		if self.journal_entry or self.purchase_invoice:
			frappe.throw(
				_("Cancel {0} before deleting this billing entry.").format(
					self.journal_entry or self.purchase_invoice
				)
			)
