"""The cutover window: nothing before the account's expense start date may be
booked, because that spend is already in the ledger from the previous system."""

import unittest

from meta_integration.utils import clamp_window


class TestBookingWindow(unittest.TestCase):
	def test_no_cutover_keeps_the_period(self):
		self.assertEqual(
			clamp_window("2026-10-01", "2026-10-31"), ("2026-10-01", "2026-10-31")
		)

	def test_cutover_inside_the_period_clips_the_start(self):
		self.assertEqual(
			clamp_window("2026-10-01", "2026-10-31", "2026-10-21"),
			("2026-10-21", "2026-10-31"),
		)

	def test_cutover_before_the_period_changes_nothing(self):
		self.assertEqual(
			clamp_window("2026-10-01", "2026-10-31", "2026-09-01"),
			("2026-10-01", "2026-10-31"),
		)

	def test_cutover_after_the_period_books_nothing(self):
		self.assertIsNone(clamp_window("2026-10-01", "2026-10-20", "2026-10-21"))

	def test_single_day_period_on_the_cutover(self):
		self.assertEqual(
			clamp_window("2026-10-01", "2026-10-21", "2026-10-21"),
			("2026-10-21", "2026-10-21"),
		)

	def test_datetime_strings_are_truncated(self):
		self.assertEqual(
			clamp_window("2026-10-01 10:00:00", "2026-10-31 23:59:59", "2026-10-21 00:00:00"),
			("2026-10-21", "2026-10-31"),
		)


if __name__ == "__main__":
	unittest.main()
