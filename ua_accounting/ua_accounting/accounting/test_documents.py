from frappe.tests import UnitTestCase

from ua_accounting.accounting.documents import (
    VAT_INCLUDED,
    VAT_NONE,
    VAT_ON_TOP,
    allocate_advance,
    calc_line,
)


class TestDocumentMath(UnitTestCase):
    def test_vat_on_top(self):
        self.assertEqual(calc_line(2, 100, 20, VAT_ON_TOP), (200, 40, 240))

    def test_vat_included(self):
        self.assertEqual(calc_line(1, 120, 20, VAT_INCLUDED), (120, 20, 120))

    def test_no_vat(self):
        self.assertEqual(calc_line(1, 120, 20, VAT_NONE), (120, 0, 120))
        self.assertEqual(calc_line(1, 120, 0, VAT_ON_TOP), (120, 0, 120))

    def test_advance_is_spread_by_rate_and_sums_up(self):
        groups = {
            "20": {"gross": 120.0, "percent": 20, "taxable": True},
            "0": {"gross": 80.0, "percent": 0, "taxable": True},
        }
        result = allocate_advance(groups, 100, VAT_ON_TOP)
        self.assertEqual(round(sum(g for g, _v in result.values()), 2), 100)
        self.assertEqual(result["0"][1], 0)
        self.assertEqual(result["20"], (60.0, 10.0))

    def test_advance_without_vat(self):
        groups = {"20": {"gross": 120.0, "percent": 20, "taxable": True}}
        self.assertEqual(allocate_advance(groups, 50, VAT_NONE)["20"], (50.0, 0.0))
