import frappe
from frappe import _
from frappe.model.document import Document

from meta_integration.config import AccountConfig, ensure_single_default


class MetaAccount(Document):
	def validate(self):
		self.validate_company()
		self.validate_name_per_company()
		ensure_single_default(self)
		self.validate_warnings()

	def validate_company(self):
		if not self.company:
			frappe.throw(_("Company is required."))
		if not frappe.db.exists("Company", self.company):
			frappe.throw(_("Company {0} does not exist.").format(self.company))

	def validate_name_per_company(self):
		duplicate = frappe.db.get_value(
			"Meta Account",
			{
				"company": self.company,
				"account_name": self.account_name,
				"name": ("!=", self.name or ""),
			},
			"name",
		)
		if duplicate:
			frappe.throw(
				_("Account name {0} already exists for {1} ({2}).").format(
					self.account_name, self.company, duplicate
				)
			)

	def validate_warnings(self):
		if self.expense_account:
			try:
				AccountConfig(self).validate()
			except Exception as exc:
				frappe.throw(str(exc))
		else:
			frappe.msgprint(
				_(
					"No Advertising Expense account set: the Spend vs Ledger report "
					"cannot compare anything without it."
				),
				indicator="orange",
				alert=True,
			)

		if self.enabled and not self.get_password("access_token", raise_exception=False):
			frappe.msgprint(
				_("No access token set: the sync will be skipped."),
				indicator="orange",
				alert=True,
			)

	def on_trash(self):
		in_use = frappe.db.count("Meta Insight", {"meta_account": self.name})
		if in_use:
			frappe.throw(
				_(
					"Meta Account {0} has {1} spend rows. Disable it instead of deleting it."
				).format(self.name, in_use)
			)
