"""Monthly spend-vs-ledger reconciliation (pure logic, no site needed)."""

import unittest

from meta_integration.reconciliation import (
	STATUS_LEDGER_HIGHER,
	STATUS_LEDGER_ONLY,
	STATUS_NOT_BOOKED,
	STATUS_OK,
	STATUS_PARTIAL,
	merge_reconciliation,
)


def spend(month, amount, account="A"):
	return {"month": month, "meta_account": account, "spend": amount}


def booked(month, amount, account="A"):
	return {"month": month, "meta_account": account, "booked": amount}


class TestMergeReconciliation(unittest.TestCase):
	def test_matching_month_is_ok(self):
		rows = merge_reconciliation([spend("2026-10", 5000)], [booked("2026-10", 5000)])
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["status"], STATUS_OK)
		self.assertEqual(rows[0]["difference"], 0)

	def test_small_rounding_is_ok(self):
		rows = merge_reconciliation([spend("2026-10", 5000)], [booked("2026-10", 4999.40)])
		self.assertEqual(rows[0]["status"], STATUS_OK)

	def test_spend_not_in_ledger(self):
		rows = merge_reconciliation([spend("2026-10", 5000)], [booked("2026-10", 4000)])
		self.assertEqual(rows[0]["status"], STATUS_NOT_BOOKED)
		self.assertEqual(rows[0]["difference"], -1000)

	def test_ledger_higher_than_spend(self):
		rows = merge_reconciliation([spend("2026-10", 5000)], [booked("2026-10", 5800)])
		self.assertEqual(rows[0]["status"], STATUS_LEDGER_HIGHER)
		self.assertEqual(rows[0]["difference"], 800)

	def test_ledger_without_spend(self):
		rows = merge_reconciliation([], [booked("2026-10", 1200)])
		self.assertEqual(rows[0]["status"], STATUS_LEDGER_ONLY)
		self.assertEqual(rows[0]["insight_spend"], 0)

	def test_spend_only_month_is_reported(self):
		rows = merge_reconciliation([spend("2026-10", 2500)], [])
		self.assertEqual(rows[0]["booked"], 0)
		self.assertEqual(rows[0]["status"], STATUS_NOT_BOOKED)

	def test_cumulative_offsets_monthly_noise(self):
		# October under-booked by 1,000 because billing closed after month end,
		# November catches up: the running difference returns to zero.
		rows = merge_reconciliation(
			[spend("2026-10", 5000), spend("2026-11", 3000)],
			[booked("2026-10", 4000), booked("2026-11", 4000)],
		)
		self.assertEqual([r["difference"] for r in rows], [-1000, 1000])
		self.assertEqual([r["cumulative_difference"] for r in rows], [-1000, 0])

	def test_cumulative_is_kept_per_account(self):
		rows = merge_reconciliation(
			[spend("2026-10", 1000, "A"), spend("2026-10", 1000, "B")],
			[booked("2026-10", 1000, "A")],
		)
		by_account = {r["meta_account"]: r["cumulative_difference"] for r in rows}
		self.assertEqual(by_account["A"], 0)
		self.assertEqual(by_account["B"], -1000)

	def test_rows_are_sorted_by_month(self):
		rows = merge_reconciliation(
			[spend("2026-11", 10), spend("2026-09", 10)], []
		)
		self.assertEqual([r["month"] for r in rows], ["2026-09", "2026-11"])

	def test_cutover_month_is_flagged_partial(self):
		rows = merge_reconciliation(
			[spend("2026-10", 500), spend("2026-11", 3000)],
			[booked("2026-10", 500), booked("2026-11", 3000)],
			cutovers={"A": "2026-10-21"},
		)
		by_month = {r["month"]: r["status"] for r in rows}
		self.assertEqual(by_month["2026-10"], STATUS_PARTIAL)
		self.assertEqual(by_month["2026-11"], STATUS_OK)

	def test_cutover_month_still_flags_a_real_gap(self):
		# Both sides are clipped to the cutover date, so a difference in that month
		# is a genuine missing booking and must not hide behind "Partial month".
		rows = merge_reconciliation(
			[spend("2026-10", 52203.93)],
			[],
			cutovers={"A": "2026-10-21"},
		)
		self.assertEqual(rows[0]["status"], STATUS_NOT_BOOKED)
		self.assertEqual(rows[0]["difference"], -52203.93)

	def test_cutover_on_the_first_is_a_normal_month(self):
		rows = merge_reconciliation(
			[spend("2026-11", 3000)], [booked("2026-11", 3000)], cutovers={"A": "2026-11-01"}
		)
		self.assertEqual(rows[0]["status"], STATUS_OK)


if __name__ == "__main__":
	unittest.main()
