"""Account resolution for the read-only Meta integration.

This app does not post to the ledger. The only accounting knowledge it keeps is
which expense account the spend belongs to (so the report can compare spend with
what was booked manually) and from which date the books are complete.
"""

import frappe
from frappe.utils import cint, flt

from .constants import DEFAULT_API_VERSION
from .exceptions import MetaConfigError

DOCTYPE = "Meta Account"


def get_account(account: str) -> "frappe.Document":
	if not account:
		raise MetaConfigError("No Meta Account given.")
	if not frappe.db.exists(DOCTYPE, account):
		raise MetaConfigError(f"Meta Account {account} does not exist.")
	return frappe.get_doc(DOCTYPE, account)


def accounts_for_company(company: str, only_enabled: bool = True) -> list:
	filters = {"company": company}
	if only_enabled:
		filters["enabled"] = 1
	return frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=["name", "account_name", "is_default", "enabled", "enable_sync"],
		order_by="is_default desc, creation asc",
	)


def default_account(company: str) -> "frappe.Document":
	rows = accounts_for_company(company)
	if not rows:
		raise MetaConfigError(
			f"Company {company} has no enabled Meta Account. "
			"Create one under Meta Integration > Meta Account."
		)
	if len(rows) == 1:
		return get_account(rows[0].name)

	flagged = [row for row in rows if cint(row.is_default)]
	if flagged:
		return get_account(flagged[0].name)

	raise MetaConfigError(
		f"Company {company} has {len(rows)} enabled Meta Accounts and none is marked "
		"as Default. Set one as default (or disable the extra accounts) so the "
		"report is unambiguous."
	)


class AccountConfig:
	def __init__(self, account):
		if isinstance(account, str):
			account = get_account(account)
		self.account = account
		self.name = account.name
		self.company = account.company
		self.company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.currency = (account.get("currency") or self.company_currency or "").strip()
		self.exchange_rate = flt(account.get("exchange_rate")) or 1.0
		self.expense_account = account.get("expense_account") or None
		self.expense_start_date = account.get("expense_start_date")
		if self.expense_start_date:
			self.expense_start_date = str(self.expense_start_date)[:10]
		self.api_version = (account.get("api_version") or DEFAULT_API_VERSION).strip()
		self.ad_account_id = (account.get("ad_account_id") or "").strip()

	def validate(self):
		"""The report needs one thing from the settings: the expense account."""
		if not self.expense_account:
			raise MetaConfigError(
				f"Meta Account {self.name} has no Advertising Expense account; "
				"the monthly report cannot compare spend with the ledger without it."
			)
		meta = frappe.db.get_value(
			"Account", self.expense_account, ["company", "is_group"], as_dict=True
		)
		if not meta:
			raise MetaConfigError(f"Account {self.expense_account} does not exist.")
		if meta.company != self.company:
			raise MetaConfigError(
				f"Account {self.expense_account} belongs to {meta.company}, "
				f"not {self.company}."
			)
		if meta.is_group:
			raise MetaConfigError(
				f"Account {self.expense_account} is a group account; pick a leaf."
			)

	def to_base(self, amount) -> float:
		return flt(flt(amount) * flt(self.exchange_rate), 2)

	def as_dict(self) -> dict:
		return {
			"account": self.name,
			"company": self.company,
			"currency": self.currency,
			"exchange_rate": self.exchange_rate,
			"expense_account": self.expense_account,
			"expense_start_date": self.expense_start_date,
		}


def ensure_single_default(doc):
	"""Only one default Meta Account per company."""
	if not cint(doc.is_default):
		return
	others = frappe.get_all(
		DOCTYPE,
		filters={"company": doc.company, "is_default": 1, "name": ("!=", doc.name or "")},
		pluck="name",
	)
	for name in others:
		frappe.db.set_value(DOCTYPE, name, "is_default", 0, update_modified=False)
