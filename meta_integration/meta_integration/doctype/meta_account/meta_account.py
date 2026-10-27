import frappe
from frappe import _
from frappe.model.document import Document

from meta_integration.config import ensure_single_default, validate_mapping


class MetaAccount(Document):
	def validate(self):
		self.validate_company()
		self.validate_name_per_company()
		ensure_single_default(self)
		validate_mapping(self)
		self.validate_warnings()

	def on_update(self):
		frappe.clear_cache()

	def on_trash(self):
		in_use = frappe.db.count("Meta Insight", {"meta_account": self.name})
		if in_use:
			frappe.throw(
				_(
					"Meta Account {0} has {1} spend rows. Disable it instead of deleting it."
				).format(self.name, in_use)
			)

	# ------------------------------------------------------------------
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
		if self.enabled and not self.is_default and not self._company_has_default():
			frappe.msgprint(
				_(
					"{0} now has several enabled Meta Accounts and none is Default. "
					"Automatic flows will refuse to run until one is flagged."
				).format(self.company),
				indicator="orange",
				alert=True,
			)
		if self.enabled and not self.get_password("access_token", raise_exception=False):
			frappe.msgprint(
				_("No access token set: sync and booking will be skipped."),
				indicator="orange",
				alert=True,
			)
		if self.booking_mode == "Purchase Invoice" and not self.purchase_item:
			frappe.msgprint(
				_("Purchase Invoice mode needs a Purchase Item."), indicator="orange", alert=True
			)
		if not self.supplier:
			frappe.msgprint(
				_("No Supplier set: the payable line cannot be posted."),
				indicator="orange",
				alert=True,
			)

	def _company_has_default(self) -> bool:
		return bool(
			frappe.db.exists(
				"Meta Account",
				{
					"company": self.company,
					"enabled": 1,
					"is_default": 1,
					"name": ("!=", self.name or ""),
				},
			)
		)
