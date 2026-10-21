import unittest
from datetime import date

from ua_accounting.reporting.filters import as_list, parse_subconto
from ua_accounting.reporting.query import split_range


class TestSplitRange(unittest.TestCase):
    def test_whole_months_use_totals_only(self):
        months, edges = split_range(date(2026, 1, 1), date(2026, 4, 1))
        self.assertEqual(months, (date(2026, 1, 1), date(2026, 4, 1)))
        self.assertEqual(edges, [])

    def test_from_start_of_books(self):
        months, edges = split_range(None, date(2026, 4, 11))
        self.assertEqual(months, (None, date(2026, 4, 1)))
        self.assertEqual(edges, [(date(2026, 4, 1), date(2026, 4, 11))])

    def test_partial_months_at_both_edges(self):
        months, edges = split_range(date(2026, 1, 10), date(2026, 3, 5))
        self.assertEqual(months, (date(2026, 2, 1), date(2026, 3, 1)))
        self.assertEqual(edges, [(date(2026, 1, 10), date(2026, 2, 1)), (date(2026, 3, 1), date(2026, 3, 5))])

    def test_inside_one_month(self):
        months, edges = split_range(date(2026, 1, 10), date(2026, 1, 20))
        self.assertIsNone(months)
        self.assertEqual(edges, [(date(2026, 1, 10), date(2026, 1, 20))])

    def test_empty_range(self):
        self.assertEqual(split_range(date(2026, 1, 10), date(2026, 1, 10)), (None, []))


class TestFilterParsing(unittest.TestCase):
    def test_as_list(self):
        self.assertEqual(as_list("a, b"), ["a", "b"])
        self.assertEqual(as_list('["a", "b"]'), ["a", "b"])
        self.assertEqual(as_list(None), [])

    def test_subconto_keeps_explicit_empty_value(self):
        parsed = parse_subconto([{"type": "Item", "values": [""]}, {"type": "X", "values": []}])
        self.assertEqual(parsed, [{"type": "Item", "values": [""]}])
