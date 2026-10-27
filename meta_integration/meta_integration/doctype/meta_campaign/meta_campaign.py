import frappe
from frappe.model.document import Document


class MetaCampaign(Document):
	def validate(self):
		if self.meta_account:
			self.company = frappe.db.get_value("Meta Account", self.meta_account, "company")
