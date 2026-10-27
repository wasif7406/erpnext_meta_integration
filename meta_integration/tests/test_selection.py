"""Unit tests for selection, aggregation and date/currency helpers.

These do not need a site: they exercise the pure logic that decides what gets
reported to ERPNext and how the amount is converted.
"""

import unittest

from meta_integration.utils import (
	base_amount,
	insight_key,
	month_bounds,
	previous_month_bounds,
	row_is_selected,
	select_rows,
	sync_window,
	total_spend,
)


def rows():
	return [
		{"name": "a1", "ad": "A1", "ad_set": "S1", "campaign": "C1", "spend": 10},
		{"name": "a2", "ad": "A2", "ad_set": "S1", "campaign": "C1", "spend": 5},
		{"name": "a3", "ad": "A3", "ad_set": "S2", "campaign": "C1", "spend": 2.5},
		{"name": "a4", "ad": "A4", "ad_set": "S2", "campaign": "C2", "spend": 7.25},
	]


class TestSelection(unittest.TestCase):
	def test_nothing_selected_books_nothing(self):
		self.assertEqual(select_rows(rows(), set(), set(), set()), [])

	def test_campaign_selection_includes_all_its_ads(self):
		selected = select_rows(rows(), set(), set(), {"C1"})
		self.assertEqual([row["name"] for row in selected], ["a1", "a2", "a3"])

	def test_ad_set_selection_includes_only_its_ads(self):
		selected = select_rows(rows(), set(), {"S1"}, set())
		self.assertEqual([row["name"] for row in selected], ["a1", "a2"])

	def test_ad_selection_is_the_narrowest(self):
		self.assertTrue(row_is_selected(rows()[3], {"A4"}, set(), set()))
		self.assertFalse(row_is_selected(rows()[0], {"A4"}, set(), set()))

	def test_overlapping_selections_do_not_duplicate(self):
		# campaign C1 + ad set S1 + ad A1 all selected -> every C1 row exactly once
		selected = select_rows(rows(), {"A1"}, {"S1"}, {"C1"})
		self.assertEqual([row["name"] for row in selected], ["a1", "a2", "a3"])

	def test_unknown_entity_is_not_selected(self):
		self.assertFalse(row_is_selected({"ad": "X", "ad_set": None, "campaign": None}, {"A1"}, {"S1"}, {"C1"}))

	def test_total_spend_rounds(self):
		selected = select_rows(rows(), set(), set(), {"C1", "C2"})
		self.assertEqual(total_spend(selected), 24.75)


class TestHelpers(unittest.TestCase):
	def test_insight_key(self):
		self.assertEqual(insight_key("123", "2026-10-27"), "123-2026-10-27")
		self.assertEqual(insight_key("123", "2026-10-27 00:00:00"), "123-2026-10-27")

	def test_base_amount_uses_rate(self):
		self.assertEqual(base_amount(100, 1), 100)
		self.assertEqual(base_amount(100, 278.5), 27850)
		self.assertEqual(base_amount(10.005, 1), 10.01)
		self.assertEqual(base_amount(10.005, 1.5), 15.01)

	def test_month_bounds(self):
		self.assertEqual(month_bounds("2026-02-14"), ("2026-02-01", "2026-02-28"))
		self.assertEqual(month_bounds("2026-12-31"), ("2026-12-01", "2026-12-31"))

	def test_previous_month_bounds(self):
		self.assertEqual(previous_month_bounds("2026-01-05"), ("2025-12-01", "2025-12-31"))
		self.assertEqual(previous_month_bounds("2026-03-31"), ("2026-02-01", "2026-02-28"))

	def test_sync_window(self):
		self.assertEqual(sync_window(7, "2026-10-27"), ("2026-10-21", "2026-10-27"))
		self.assertEqual(sync_window(1, "2026-10-27"), ("2026-10-27", "2026-10-27"))
		# 0 falls back to the default window
		self.assertEqual(sync_window(0, "2026-10-27"), ("2026-10-21", "2026-10-27"))


if __name__ == "__main__":
	unittest.main()
