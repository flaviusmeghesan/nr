import unittest
from datetime import date

from tracker import weeks


class WeeksTests(unittest.TestCase):
    def test_week_of_date(self):
        self.assertEqual(weeks.week_of(date(2026, 9, 17)), "2026-W38")

    def test_week_of_string_variants(self):
        self.assertEqual(weeks.week_of("2026-09-17"), "2026-W38")
        self.assertEqual(weeks.week_of("2026-09-17T10:30:00Z"), "2026-W38")

    def test_week_bounds(self):
        monday, sunday = weeks.week_bounds("2026-W38")
        self.assertEqual(monday, date(2026, 9, 14))
        self.assertEqual(sunday, date(2026, 9, 20))

    def test_week_bounds_invalid(self):
        with self.assertRaises(ValueError):
            weeks.week_bounds("nu-e-saptamana")

    def test_shift_week(self):
        self.assertEqual(weeks.shift_week("2026-W38", -1), "2026-W37")
        self.assertEqual(weeks.shift_week("2026-W38", 1), "2026-W39")
        self.assertEqual(weeks.shift_week("2026-W01", -1), "2025-W52")

    def test_is_week(self):
        self.assertTrue(weeks.is_week("2026-W38"))
        self.assertFalse(weeks.is_week("2026-38"))
        self.assertFalse(weeks.is_week(""))

    def test_days_left(self):
        self.assertEqual(weeks.days_left("2026-W38", date(2026, 9, 17)), 4)
        self.assertEqual(weeks.days_left("2026-W38", date(2026, 9, 21)), 0)

    def test_parse_date_iso(self):
        self.assertEqual(weeks.parse_date("2026-09-17"), date(2026, 9, 17))
        self.assertEqual(weeks.parse_date("2026-09-17T10:30:00Z"), date(2026, 9, 17))

    def test_parse_date_common_export_formats(self):
        cases = {
            "09/15/2026": date(2026, 9, 15),
            "09/15/2026 3:45 PM": date(2026, 9, 15),
            "15.09.2026": date(2026, 9, 15),
            "September 15, 2026": date(2026, 9, 15),
            "Sep 15, 2026 3:45 PM": date(2026, 9, 15),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(weeks.parse_date(text), expected)

    def test_parse_date_invalid(self):
        self.assertIsNone(weeks.parse_date(""))
        self.assertIsNone(weeks.parse_date(None))
        self.assertIsNone(weeks.parse_date("nu e o data"))

    def test_week_label(self):
        self.assertEqual(weeks.week_label("2026-W38"), "14 - 20 sep 2026")


if __name__ == "__main__":
    unittest.main()
