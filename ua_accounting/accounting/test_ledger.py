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

TURNOVER = "UA Account Turnover"
ENTRY = "UA Accounting Entry"


def make_doc(name, org, date="2026-03-15"):
    return frappe._dict(doctype="UA Test Registrar", name=name, posting_date=date, organization=org)


def sum_entries():
    """Debit and credit sums by account from entries (for comparing with totals)."""
    res = {}
    for r in frappe.get_all(ENTRY, fields=["account_dr", "account_cr", "amount"]):
        if r.account_dr:
            res.setdefault(r.account_dr, [0, 0])[0] += r.amount
        if r.account_cr:
            res.setdefault(r.account_cr, [0, 0])[1] += r.amount
    return res


def sum_totals():
    res = {}
    for r in frappe.get_all(TURNOVER, fields=["account", "debit", "credit"]):
        item = res.setdefault(r.account, [0, 0])
        item[0] += r.debit
        item[1] += r.credit
    return res


class TestLedger(IntegrationTestCase):
    def setUp(self):
        frappe.db.delete(ENTRY)
        frappe.db.delete(TURNOVER)
        self.org = frappe.db.get_value("UA Organization", {"org_name": "Test org"}, "name")
        if not self.org:
            self.org = frappe.get_doc({"doctype": "UA Organization", "org_name": "Test org"}).insert().name
        self.cp = frappe.get_doc({"doctype": "UA Counterparty", "counterparty_name": "Test CP"}).insert()
        self.contract = frappe.get_doc(
            {
                "doctype": "UA Counterparty Contract",
                "counterparty": self.cp.name,
                "organization": self.org,
                "contract_kind": "З покупцем",
            }
        ).insert()

    def sale(self, doc, amount):
        return [
            {
                "account_dr": "361",
                "account_cr": "701",
                "amount": amount,
                "subconto_dr": {
                    "Counterparty": self.cp.name,
                    "Contract": self.contract.name,
                    "SettlementDoc": ("UA Test Registrar", doc.name),
                },
                "subconto_cr": {"VatRate": "20"},
            }
        ]

    def test_post_and_cancel_keep_totals_in_sync(self):
        d1, d2 = make_doc("D1", self.org), make_doc("D2", self.org, "2026-04-02")
        post_entries(d1, self.sale(d1, 100))
        post_entries(d2, self.sale(d2, 50))
        self.assertEqual(sum_totals(), sum_entries())
        cancel_entries(d1)
        self.assertEqual(sum_totals(), sum_entries())
        self.assertEqual(sum_totals()["361"], [50, 0])
        cancel_entries(d2)
        self.assertEqual(frappe.db.count(TURNOVER), 0)

    def test_turnover_only_slot_is_empty_in_totals(self):
        d = make_doc("D3", self.org)
        post_entries(d, self.sale(d, 10))
        row = frappe.get_all(TURNOVER, filters={"account": "701"}, fields=["subconto1", "subconto2"])[0]
        self.assertEqual((row.subconto1, row.subconto2), ("", ""))

    def test_storno(self):
        d = make_doc("D4", self.org)
        post_entries(d, self.sale(d, 100) + self.sale(d, -100))
        self.assertEqual(sum_totals()["361"], [0, 0])

    def test_off_balance_one_sided(self):
        d = make_doc("D5", self.org)
        post_entries(d, [{"account_dr": "09", "amount": 5}])
        self.assertEqual(sum_totals()["09"], [5, 0])
        with self.assertRaises(frappe.ValidationError):
            post_entries(d, [{"account_dr": "361", "amount": 5}])

    def test_errors(self):
        d = make_doc("D6", self.org)
        with self.assertRaises(frappe.ValidationError):
            post_entries(d, [{"account_dr": "36", "account_cr": "701", "amount": 1}])  # group
        with self.assertRaises(frappe.ValidationError):
            post_entries(
                d,
                [{"account_dr": "361", "account_cr": "701", "amount": 1, "subconto_dr": {"Warehouse": "x"}}],
            )

    def test_repost_and_rebuild(self):
        d = make_doc("D7", self.org)
        post_entries(d, self.sale(d, 10))
        repost_entries(d, self.sale(d, 20))
        self.assertEqual(sum_totals()["361"], [20, 0])
        before = sum_totals()
        frappe.set_user("Administrator")
        rebuild_totals()
        self.assertEqual(sum_totals(), before)
