"""Monthly control: spend pulled from Meta vs what was booked in the ledger.

The app never posts; this only compares. Any voucher that debited the mapped
advertising expense account counts as "booked" — a manual Journal Entry, a
Purchase Invoice, an Expense Claim, whatever you used.
"""

from frappe.utils import flt

DEFAULT_TOLERANCE = 1.0

STATUS_OK = "OK"
STATUS_NOT_BOOKED = "Spend not in ledger"
STATUS_LEDGER_HIGHER = "Ledger > spend"
STATUS_LEDGER_ONLY = "Ledger without spend"
STATUS_PARTIAL = "Partial month"


def merge_reconciliation(spend_rows, ledger_rows, tolerance=DEFAULT_TOLERANCE, cutovers=None):
	"""Merge per-(month, account) spend and ledger amounts into report rows.

	Inputs are dicts with `month`, `meta_account` and `spend` / `booked`, both in
	company currency. `cutovers` maps an account to its cutover date
	(YYYY-MM-DD): that month is only partly covered by the books, so it is flagged
	rather than judged.
	"""
	buckets = {}

	def bucket(month, account):
		key = (str(month), account or "")
		if key not in buckets:
			buckets[key] = {
				"month": str(month),
				"meta_account": account,
				"insight_spend": 0.0,
				"booked": 0.0,
			}
		return buckets[key]

	for row in spend_rows or []:
		target = bucket(row.get("month"), row.get("meta_account"))
		target["insight_spend"] = flt(target["insight_spend"]) + flt(row.get("spend"))

	for row in ledger_rows or []:
		target = bucket(row.get("month"), row.get("meta_account"))
		target["booked"] = flt(target["booked"]) + flt(row.get("booked"))

	cutovers = cutovers or {}

	rows = []
	running = {}
	for key in sorted(buckets):
		row = buckets[key]
		row["insight_spend"] = flt(row["insight_spend"], 2)
		row["booked"] = flt(row["booked"], 2)
		row["difference"] = flt(row["booked"] - row["insight_spend"], 2)
		row["status"] = _status(row, tolerance)

		cutover = cutovers.get(row["meta_account"])
		if cutover:
			cutover = str(cutover)[:10]
			if row["month"] == cutover[:7] and cutover[8:10] != "01":
				# The books only cover part of this month; comparing it is noise.
				row["status"] = STATUS_PARTIAL

		account = row["meta_account"] or ""
		running[account] = flt(running.get(account, 0.0) + row["difference"], 2)
		row["cumulative_difference"] = running[account]
		rows.append(row)
	return rows


def _status(row, tolerance) -> str:
	spend = flt(row["insight_spend"])
	booked = flt(row["booked"])
	diff = booked - spend

	if abs(diff) <= flt(tolerance):
		return STATUS_OK
	if spend <= 0 and booked != 0:
		return STATUS_LEDGER_ONLY
	if diff < 0:
		# Less booked than spent: a charge not recorded yet, or the tail of the
		# month that is billed in the next cycle.
		return STATUS_NOT_BOOKED
	return STATUS_LEDGER_HIGHER
