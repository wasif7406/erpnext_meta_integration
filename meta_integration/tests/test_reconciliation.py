"""Monthly spend-vs-charge reconciliation (pure logic, no site needed)."""

import unittest

from meta_integration.reconciliation import (
	STATUS_CHARGE_ONLY,
	STATUS_DRAFT,
	STATUS_MISSING_CHARGE,
	STATUS_OK,
	STATUS_OVER_CHARGED,
	merge_reconciliation,
)


class TestMergeReconciliation(unittest.TestCase):
	def test_matching_month_is_ok(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 5000}],
			[{"month": "2026-10", "meta_account": "A", "charged": 5000}],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["status"], STATUS_OK)
		self.assertEqual(rows[0]["difference"], 0)

	def test_small_rounding_is_ok(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 5000}],
			[{"month": "2026-10", "meta_account": "A", "charged": 4999.40}],
		)
		self.assertEqual(rows[0]["status"], STATUS_OK)

	def test_missing_charge(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 5000}],
			[{"month": "2026-10", "meta_account": "A", "charged": 4000}],
		)
		self.assertEqual(rows[0]["status"], STATUS_MISSING_CHARGE)
		self.assertEqual(rows[0]["difference"], -1000)

	def test_over_charged(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 5000}],
			[{"month": "2026-10", "meta_account": "A", "charged": 5800}],
		)
		self.assertEqual(rows[0]["status"], STATUS_OVER_CHARGED)
		self.assertEqual(rows[0]["difference"], 800)

	def test_charge_without_spend(self):
		rows = merge_reconciliation(
			[],
			[{"month": "2026-10", "meta_account": "A", "charged": 1200}],
		)
		self.assertEqual(rows[0]["status"], STATUS_CHARGE_ONLY)
		self.assertEqual(rows[0]["insight_spend"], 0)

	def test_drafts_take_precedence_over_ok(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 5000}],
			[{"month": "2026-10", "meta_account": "A", "charged": 5000, "drafts": 1}],
		)
		self.assertEqual(rows[0]["status"], STATUS_DRAFT)

	def test_spend_only_month_is_reported(self):
		rows = merge_reconciliation(
			[{"month": "2026-10", "meta_account": "A", "spend": 2500}], []
		)
		self.assertEqual(rows[0]["charged"], 0)
		self.assertEqual(rows[0]["status"], STATUS_MISSING_CHARGE)

	def test_multiple_accounts_are_kept_apart(self):
		rows = merge_reconciliation(
			[
				{"month": "2026-10", "meta_account": "A", "spend": 1000},
				{"month": "2026-10", "meta_account": "B", "spend": 2000},
			],
			[
				{"month": "2026-10", "meta_account": "A", "charged": 1000},
				{"month": "2026-10", "meta_account": "B", "charged": 1500},
			],
		)
		self.assertEqual(len(rows), 2)
		self.assertEqual([r["status"] for r in rows], [STATUS_OK, STATUS_MISSING_CHARGE])

	def test_rows_are_sorted_by_month(self):
		rows = merge_reconciliation(
			[
				{"month": "2026-11", "meta_account": "A", "spend": 10},
				{"month": "2026-09", "meta_account": "A", "spend": 10},
			],
			[],
		)
		self.assertEqual([r["month"] for r in rows], ["2026-09", "2026-11"])


if __name__ == "__main__":
	unittest.main()
