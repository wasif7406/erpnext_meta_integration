"""Meta returns ISO-8601 timestamps with a numeric offset; MySQL Datetime does
not accept them, which made every campaign/ad set insert fail while ads (no
datetime fields) succeeded."""

import unittest

from meta_integration.utils import meta_datetime


class TestMetaDatetime(unittest.TestCase):
	def test_iso_with_numeric_offset(self):
		self.assertEqual(meta_datetime("2026-09-27T16:29:59+0500"), "2026-09-27 16:29:59")

	def test_iso_with_colon_offset(self):
		self.assertEqual(meta_datetime("2026-09-27T16:29:59+05:00"), "2026-09-27 16:29:59")

	def test_iso_utc_z(self):
		self.assertEqual(meta_datetime("2026-09-27T16:29:59Z"), "2026-09-27 16:29:59")

	def test_already_frappe_format(self):
		self.assertEqual(meta_datetime("2026-09-27 16:29:59"), "2026-09-27 16:29:59")

	def test_empty(self):
		self.assertIsNone(meta_datetime(None))
		self.assertIsNone(meta_datetime(""))

	def test_garbage(self):
		self.assertIsNone(meta_datetime("not a date"))
		self.assertIsNone(meta_datetime("2026-09-27"))


if __name__ == "__main__":
	unittest.main()
