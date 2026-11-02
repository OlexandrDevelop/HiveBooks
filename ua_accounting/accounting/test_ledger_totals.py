"""Ledger on the core RecordSet and accounting totals adapter: atomicity, repeat calls, rebuild."""

from unittest import mock

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # older frappe
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from ua_accounting.accounting.ledger import (
    cancel_entries,
    post_entries,
    rebuild_totals,
    repost_entries,
)
from ua_accounting.accounting.test_ledger import ENTRY, TURNOVER, make_doc, sum_entries, sum_totals

KEY = ["period", "organization", "account", "subconto1", "subconto2", "subconto3", "currency"]
SUMS = ["debit", "credit", "quantity_dr", "quantity_cr", "currency_dr", "currency_cr"]


def totals_state():
    rows = frappe.get_all(TURNOVER, fields=["name", *KEY, *SUMS], order_by="name asc")
    return {r.name: tuple(str(r[f]) for f in KEY) + tuple(r[f] for f in SUMS) for r in rows}


class TestLedgerTotals(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.delete(ENTRY)
        frappe.db.delete(TURNOVER)
        self.org = frappe.db.get_value("UA Organization", {"org_name": "Test org"}, "name")
        if not self.org:
            self.org = frappe.get_doc({"doctype": "UA Organization", "org_name": "Test org"}).insert().name
        self.org2 = frappe.db.get_value("UA Organization", {"org_name": "Test org 2"}, "name")
        if not self.org2:
            self.org2 = frappe.get_doc({"doctype": "UA Organization", "org_name": "Test org 2"}).insert().name
        self.addCleanup(frappe.db.rollback)

    def sale(self, amount, cp="CP1", doc="X1"):
        return {
            "account_dr": "361",
            "account_cr": "701",
            "amount": amount,
            "subconto_dr": {"Counterparty": cp, "SettlementDoc": ("UA Test Registrar", doc)},
            "subconto_cr": {"VatRate": "20"},
        }

    def test_totals_names_and_keys_are_stable(self):
        d = make_doc("T1", self.org)
        post_entries(d, [self.sale(10)])
        state = totals_state()
        self.assertEqual(len(state), 2)
        self.assertTrue(all(len(name) == 40 for name in state))
        rebuild_totals()
        self.assertEqual(totals_state(), state)

    def test_repeat_post_appends_and_cancel_removes_all(self):
        d = make_doc("T2", self.org)
        post_entries(d, [self.sale(10)])
        post_entries(d, [self.sale(5)])
        self.assertEqual(frappe.db.count(ENTRY, {"registrar": "T2"}), 2)
        self.assertEqual(sum_totals()["361"], [15, 0])
        cancel_entries(d)
        self.assertEqual(frappe.db.count(ENTRY), 0)
        self.assertEqual(frappe.db.count(TURNOVER), 0)

    def test_repost_equals_entries_and_empty_rows_are_deleted(self):
        d1, d2 = make_doc("T3", self.org), make_doc("T4", self.org2, "2026-05-01")
        post_entries(d1, [self.sale(10)])
        post_entries(d2, [self.sale(7)])
        repost_entries(d1, [self.sale(30)])
        self.assertEqual(sum_totals(), sum_entries())
        self.assertEqual(sum_totals()["361"], [37, 0])
        repost_entries(d1, [])
        self.assertEqual(sum_totals(), sum_entries())
        self.assertEqual(sum_totals()["361"], [7, 0])

    def test_dynamic_identity_stays_distinct_and_turnover_only_is_blank(self):
        d = make_doc("T5", self.org)
        post_entries(d, [self.sale(1, doc="A"), self.sale(2, doc="B"), self.sale(4, doc="B")])
        rows = frappe.get_all(TURNOVER, filters={"account": "361"}, fields=["subconto2", "subconto3", "debit"], order_by="subconto3")
        # slot 3 is the dynamic settlement document, slot 2 an empty contract
        self.assertEqual([(r.subconto3, r.debit) for r in rows], [("A", 1), ("B", 6)])
        entries = frappe.get_all(ENTRY, filters={"account_dr": "361"}, fields=["subconto_dr3_type", "subconto_dr3"])
        self.assertTrue(all(e.subconto_dr3_type == "UA Test Registrar" for e in entries))
        credit = frappe.get_all(TURNOVER, filters={"account": "701"}, fields=["subconto1", "subconto2"])
        self.assertEqual((credit[0].subconto1, credit[0].subconto2), ("", ""))

    def test_blank_slots_are_empty_strings_not_null(self):
        d = make_doc("T6", self.org)
        post_entries(d, [{"account_dr": "361", "account_cr": "701", "amount": 3}])
        row = frappe.db.sql(
            "select subconto_dr1, subconto_dr3_type, subconto_cr3, currency_dr, content from `tabUA Accounting Entry`",
            as_dict=True,
        )[0]
        self.assertEqual(list(row.values()), ["", "", "", "", ""])

    def test_quantity_and_currency_resources(self):
        d = make_doc("T7", self.org)
        post_entries(
            d,
            [
                {"account_dr": "201", "account_cr": "631", "amount": 10, "quantity_dr": 4, "currency_cr": "USD", "currency_amount_cr": 0.25},
                {"account_dr": "09", "amount": 5},
            ],
        )
        qty = frappe.get_all(TURNOVER, filters={"account": "201"}, fields=["quantity_dr", "debit"])[0]
        self.assertEqual((qty.quantity_dr, qty.debit), (4, 10))
        cur = frappe.get_all(TURNOVER, filters={"account": "631"}, fields=["currency", "currency_cr", "credit"])[0]
        self.assertEqual((cur.currency, cur.currency_cr, cur.credit), ("USD", 0.25, 10))
        self.assertEqual(sum_totals()["09"], [5, 0])

    def test_error_after_movements_rolls_back_entries_and_totals(self):
        d = make_doc("T8", self.org)
        frappe.db.savepoint("ledger_test")
        with mock.patch("ua_accounting.accounting.ledger.tax_ledger.post_rows", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                post_entries(d, [self.sale(10)])
        frappe.db.rollback(save_point="ledger_test")
        self.assertEqual(frappe.db.count(ENTRY), 0)
        self.assertEqual(frappe.db.count(TURNOVER), 0)

    def test_filtered_rebuild_keeps_unrelated_rows(self):
        post_entries(make_doc("T9", self.org), [self.sale(10)])
        post_entries(make_doc("T10", self.org2), [self.sale(20)])
        post_entries(make_doc("T11", self.org, "2026-06-10"), [self.sale(3)])
        live = totals_state()
        frappe.db.sql(f"update `tab{TURNOVER}` set debit = debit + 1")
        rebuild_totals(organization=self.org)
        state = totals_state()
        for name, row in state.items():
            if row[1] == self.org2:
                self.assertEqual(row[7], live[name][7] + 1)
            else:
                self.assertEqual(row, live[name])
        frappe.db.sql(f"update `tab{TURNOVER}` set debit = debit + 1")
        rebuild_totals(from_period="2026-06-20")
        june = frappe.get_all(TURNOVER, filters={"period": "2026-06-01", "account": "361"}, pluck="debit")
        march = frappe.get_all(TURNOVER, filters={"period": "2026-03-01", "organization": self.org, "account": "361"}, pluck="debit")
        self.assertEqual(june, [3])
        self.assertEqual(march, [11])

    def test_unauthorized_rebuild_fails_before_writing(self):
        post_entries(make_doc("T12", self.org), [self.sale(10)])
        frappe.db.sql(f"update `tab{TURNOVER}` set debit = 999")
        frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.PermissionError):
                rebuild_totals()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(set(frappe.get_all(TURNOVER, filters={"account": "361"}, pluck="debit")), {999})

    def test_period_lock_hook_is_unchanged(self):
        from ua_accounting.accounting.ledger import get_lock_date

        self.assertIsNone(get_lock_date(frappe._dict()))
