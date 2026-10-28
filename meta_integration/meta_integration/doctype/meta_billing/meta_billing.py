import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class MetaBilling(Document):
	def validate(self):
		from meta_integration.config import AccountConfig

		config = AccountConfig(self.meta_account)
		self.company = config.company
		self.expense_account = config.expense_account
		self.payable_account = config.payable_account
		self.supplier = config.supplier
		self.cost_center = config.cost_center
		if not self.currency:
			self.currency = config.currency
		if not flt(self.exchange_rate):
			self.exchange_rate = config.exchange_rate or 1
		self.base_amount = flt(flt(self.amount) * flt(self.exchange_rate), 2)

	def on_trash(self):
		if self.purchase_invoice:
			frappe.throw(
				_("Cancel {0} before deleting this billing entry.").format(self.purchase_invoice)
			)
