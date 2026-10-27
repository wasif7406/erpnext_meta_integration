import frappe
from frappe.model.document import Document


class MetaInsight(Document):
	def validate(self):
		if self.ad and self.date and not self.insight_key:
			self.insight_key = f"{self.ad}:{self.date}"
		if self.meta_account:
			self.company = frappe.db.get_value("Meta Account", self.meta_account, "company")
