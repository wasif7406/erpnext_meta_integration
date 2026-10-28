"""Monthly reconciliation: spend pulled from Meta vs charges actually posted.

This is a control, not accounting: it answers "did every month's spend get
charged, and did we miss a charge?". Nothing here posts to the ledger.
"""

from frappe.utils import flt


# A cent-level tolerance absorbs rounding between daily spend and a charge.
DEFAULT_TOLERANCE = 1.0

STATUS_OK = "OK"
STATUS_MISSING_CHARGE = "Spend not charged"
STATUS_OVER_CHARGED = "Charged > spend"
STATUS_DRAFT = "Draft entries"
STATUS_CHARGE_ONLY = "Charge without spend"


def merge_reconciliation(spend_rows, charge_rows, tolerance=DEFAULT_TOLERANCE):
	"""Merge per-(month, account) spend and charges into report rows.

	Both inputs are iterables of dicts with `month`, `meta_account` and either
	`spend` or `charged` (+ optional `drafts`). Amounts must already be in the
	company currency.
	"""
	buckets = {}

	def bucket(month, account):
		key = (str(month), account or "")
		if key not in buckets:
			buckets[key] = {
				"month": str(month),
				"meta_account": account,
				"insight_spend": 0.0,
				"charged": 0.0,
				"drafts": 0,
			}
		return buckets[key]

	for row in spend_rows or []:
		target = bucket(row.get("month"), row.get("meta_account"))
		target["insight_spend"] = flt(target["insight_spend"]) + flt(row.get("spend"))

	for row in charge_rows or []:
		target = bucket(row.get("month"), row.get("meta_account"))
		target["charged"] = flt(target["charged"]) + flt(row.get("charged"))
		target["drafts"] = int(target["drafts"]) + int(row.get("drafts") or 0)

	rows = []
	for key in sorted(buckets):
		row = buckets[key]
		row["insight_spend"] = flt(row["insight_spend"], 2)
		row["charged"] = flt(row["charged"], 2)
		row["difference"] = flt(row["charged"] - row["insight_spend"], 2)
		row["status"] = _status(row, tolerance)
		rows.append(row)
	return rows


def _status(row, tolerance) -> str:
	spend = flt(row["insight_spend"])
	charged = flt(row["charged"])
	diff = charged - spend

	if abs(diff) <= flt(tolerance):
		return STATUS_DRAFT if row.get("drafts") else STATUS_OK
	if spend <= 0 and charged > 0:
		return STATUS_CHARGE_ONLY
	if diff < 0:
		# charged less than the spend we recorded: a missing charge, or the last
		# days of the month not billed yet.
		return STATUS_DRAFT if row.get("drafts") else STATUS_MISSING_CHARGE
	return STATUS_OVER_CHARGED
