"""Resolution of a company's Meta account and its account mapping.

Same contract as the PostEx app: nothing financial is hard-coded, and a company
may have several Meta accounts (rare) with exactly one flagged as default.
"""

import frappe
from frappe.utils import cint, flt

from .constants import (
	ACCOUNT_RULES,
	RECOGNITION_BILLING,
	BOOKING_JOURNAL_ENTRY,
	BOOKING_MODES,
	DEFAULT_API_VERSION,
	ROLE_COST_CENTER,
	ROLE_EXPENSE,
	ROLE_PAYABLE,
	ROLES,
)
from .exceptions import MetaConfigError

DOCTYPE = "Meta Account"


# ---------------------------------------------------------------------------
# Account lookup
# ---------------------------------------------------------------------------
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
	"""One enabled account is the default; several require `is_default`."""
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
		"as Default. Set one as default (or disable the extra accounts) so expense "
		"reporting is unambiguous."
	)


# ---------------------------------------------------------------------------
# Resolved configuration
# ---------------------------------------------------------------------------
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
		self.booking_mode = account.get("booking_mode") or BOOKING_JOURNAL_ENTRY
		self.expense_recognition = (
			account.get("expense_recognition") or RECOGNITION_BILLING
		)
		self.supplier = account.get("supplier") or None
		# Nothing before this date may be booked: it is already in the ledger.
		self.expense_start_date = (
			account.get("expense_start_date")
			or account.get("creation")
			or None
		)
		if self.expense_start_date:
			self.expense_start_date = str(self.expense_start_date)[:10]
		self.purchase_item = account.get("purchase_item") or None
		self.api_version = (account.get("api_version") or DEFAULT_API_VERSION).strip()
		self.ad_account_id = (account.get("ad_account_id") or "").strip()

		self._rows = {row.role: row for row in account.mapping or [] if row.role}
		self.expense_account = self._account(ROLE_EXPENSE)
		self.payable_account = self._account(ROLE_PAYABLE)
		self.cost_center = self._cost_center()

	# -- mapping -----------------------------------------------------------
	def _account(self, role, required=True):
		row = self._rows.get(role)
		value = (row.account or "").strip() if row else ""
		if not value:
			if required:
				raise MetaConfigError(
					f"Meta Account {self.name}: mapping role '{role}' has no account selected."
				)
			return None
		return value

	def _cost_center(self):
		row = self._rows.get(ROLE_COST_CENTER)
		value = (row.cost_center or "").strip() if row else ""
		if value:
			return value
		return frappe.get_cached_value("Company", self.company, "cost_center") or None

	# -- convenience -------------------------------------------------------
	def to_base(self, amount) -> float:
		return flt(flt(amount) * flt(self.exchange_rate), 2)

	def validate_for_booking(self):
		"""Everything the posting routine needs, with actionable messages."""
		if not self.ad_account_id:
			raise MetaConfigError(f"Meta Account {self.name} has no Ad Account ID.")
		if self.booking_mode not in BOOKING_MODES:
			raise MetaConfigError(f"Unknown booking mode '{self.booking_mode}'.")
		if not self.supplier:
			raise MetaConfigError(
				f"Meta Account {self.name} has no Supplier; the payable needs a party."
			)
		if self.booking_mode == "Purchase Invoice" and not self.purchase_item:
			raise MetaConfigError(
				f"Meta Account {self.name} uses Purchase Invoice mode but has no Purchase Item."
			)
		if self.currency and self.company_currency and self.currency != self.company_currency:
			if flt(self.exchange_rate) <= 1:
				raise MetaConfigError(
					f"Meta Account {self.name} is in {self.currency} but the company is in "
					f"{self.company_currency}; set an Exchange Rate on the account."
				)

	def as_dict(self) -> dict:
		return {
			"account": self.name,
			"company": self.company,
			"expense_account": self.expense_account,
			"payable_account": self.payable_account,
			"cost_center": self.cost_center,
			"supplier": self.supplier,
			"currency": self.currency,
			"exchange_rate": self.exchange_rate,
			"booking_mode": self.booking_mode,
			"expense_start_date": self.expense_start_date,
			"expense_recognition": self.expense_recognition,
		}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_mapping(doc):
	seen_roles = set()
	seen_accounts = {}
	warnings = []

	for row in doc.mapping or []:
		role = (row.role or "").strip()
		if not role:
			frappe.throw("Every mapping row needs a role.")
		if role not in ROLES:
			frappe.throw(f"Unknown mapping role '{role}'.")
		if role in seen_roles:
			frappe.throw(f"Mapping role '{role}' appears more than once.")
		seen_roles.add(role)

		values = [v for v in (row.account, row.cost_center) if (v or "").strip()]
		if len(values) != 1:
			frappe.throw(
				f"Mapping row '{role}' must set exactly one of account or cost center."
			)

		if role == ROLE_COST_CENTER:
			_validate_cost_center(row, doc.company)
			continue

		_validate_account(row, role, doc.company, seen_accounts, warnings)

	for role in (ROLE_EXPENSE, ROLE_PAYABLE):
		if role not in seen_roles:
			warnings.append(
				f"Mapping role '{role}' is not configured yet; expense reporting will "
				"refuse to run until it is set."
			)

	for message in warnings:
		frappe.msgprint(message, indicator="orange", alert=True)


def _validate_account(row, role, company, seen_accounts, warnings):
	account = row.account
	meta = frappe.db.get_value(
		"Account", account, ["company", "is_group", "root_type", "account_type"], as_dict=True
	)
	if not meta:
		frappe.throw(f"Account {account} does not exist.")
	if meta.company != company:
		frappe.throw(f"Account {account} belongs to {meta.company}, not {company}.")
	if meta.is_group:
		frappe.throw(f"Account {account} is a group account; select a leaf account.")

	root_types, account_types, allow_blank = ACCOUNT_RULES.get(role, ((), (), True))
	if root_types and meta.root_type not in root_types:
		frappe.throw(
			f"Role '{role}' needs an account of root type {' / '.join(root_types)}; "
			f"{account} is {meta.root_type}."
		)
	if account_types and meta.account_type not in account_types:
		frappe.throw(
			f"Role '{role}' needs account_type {' / '.join(account_types)}; "
			f"{account} is '{meta.account_type or 'none'}'."
		)
	if not account_types and not allow_blank and meta.account_type:
		warnings.append(f"Role '{role}': {account} has account_type '{meta.account_type}'.")

	other = seen_accounts.get(account)
	if other and other != role:
		warnings.append(
			f"Account {account} is mapped to both '{other}' and '{role}'. "
			"That is allowed but usually a mistake."
		)
	seen_accounts[account] = role

	clash = frappe.db.sql(
		"""
		select parent from `tabMeta Account Mapping`
		where account = %s and parent != %s and parenttype = 'Meta Account'
		""",
		(account, row.parent or ""),
		as_dict=True,
	)
	for other_row in clash:
		other_company = frappe.db.get_value("Meta Account", other_row.parent, "company")
		if other_company and other_company != company:
			frappe.throw(
				f"Account {account} is already used by Meta Account {other_row.parent} "
				f"of company {other_company}. Accounts cannot be shared between companies."
			)


def _validate_cost_center(row, company):
	meta = frappe.db.get_value("Cost Center", row.cost_center, ["company", "is_group"], as_dict=True)
	if not meta:
		frappe.throw(f"Cost Center {row.cost_center} does not exist.")
	if meta.company != company:
		frappe.throw(f"Cost Center {row.cost_center} belongs to {meta.company}, not {company}.")
	if meta.is_group:
		frappe.throw(f"Cost Center {row.cost_center} is a group; select a leaf cost center.")


def ensure_single_default(doc):
	if not cint(doc.is_default):
		return
	others = frappe.get_all(
		DOCTYPE,
		filters={"company": doc.company, "is_default": 1, "name": ("!=", doc.name or "")},
		pluck="name",
	)
	for name in others:
		frappe.db.set_value(DOCTYPE, name, "is_default", 0, update_modified=False)
