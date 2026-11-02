"""VAT, tax ledger and income book registers on the core RecordSet: meta, write path, repeat calls, rollback."""

import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # older frappe
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from ua_accounting.accounting import simplified_tax, tax_ledger, vat
from ua_accounting.accounting.test_ledger import make_doc
from ua_accounting.accounting.utils import register_append

REGISTERS = (vat.LIABILITY, vat.CREDIT, tax_ledger.LEDGER, simplified_tax.BOOK)


class TestTaxRegisters(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.org = frappe.db.get_value("UA Organization", {"org_name": "Test org"}, "name")
        if not self.org:
            self.org = frappe.get_doc({"doctype": "UA Organization", "org_name": "Test org"}).insert().name
        for doctype in REGISTERS:
            frappe.db.delete(doctype)
        self.addCleanup(frappe.db.rollback)

    def vat_row(self, base=100, **extra):
        return {"vat_rate": "20", "base_amount": base, "vat_amount": base / 5, **extra}

    def test_registers_are_described_in_core_meta(self):
        for doctype in REGISTERS:
            reg = frappe.get_doc("Register", doctype)
            self.assertEqual(reg.register_doctype, doctype)
            self.assertEqual(reg.registrar_field, "registrar")
            self.assertEqual(reg.date_field, "posting_date")
            roles = {row.fieldname: row.role for row in reg.fields}
            self.assertEqual(roles["organization"], "Dimension")
            self.assertIn("Resource", roles.values())

    def test_vat_post_repeat_and_cancel(self):
        d = make_doc("TV1", self.org)
        vat.post_vat_entries(d, [self.vat_row()], [self.vat_row(50)])
        vat.post_vat_entries(d, [self.vat_row(10)])
        self.assertEqual(frappe.db.count(vat.LIABILITY, {"registrar": "TV1"}), 2)
        self.assertEqual(frappe.db.count(vat.CREDIT, {"registrar": "TV1"}), 1)
        row = frappe.get_all(vat.LIABILITY, filters={"registrar": "TV1"}, fields=["*"], order_by="creation asc")[0]
        self.assertEqual(row.counterparty or "", "")
        self.assertEqual(row.event, "Інше")
        self.assertEqual(str(row.period), str(frappe.utils.get_first_day(d.posting_date)))
        vat.cancel_vat_entries(d)
        self.assertEqual(frappe.db.count(vat.LIABILITY), 0)
        self.assertEqual(frappe.db.count(vat.CREDIT), 0)

    def test_vat_validation_stops_before_any_row(self):
        d = make_doc("TV2", self.org)
        with self.assertRaises(frappe.ValidationError):
            vat.post_vat_entries(d, [self.vat_row(), {"base_amount": 1}])
        self.assertEqual(frappe.db.count(vat.LIABILITY), 0)

    def test_direct_write_is_rejected(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {"doctype": simplified_tax.BOOK, "organization": self.org, "posting_date": "2025-01-01", "income_amount": 1}
            ).insert()

    def test_register_append_other_registrar_untouched(self):
        a, b = make_doc("TV3", self.org), make_doc("TV4", self.org)
        vat.post_vat_entries(a, [self.vat_row()])
        vat.post_vat_entries(b, [self.vat_row()])
        vat.cancel_vat_entries(a)
        self.assertEqual(frappe.db.count(vat.LIABILITY, {"registrar": "TV4"}), 1)
        self.assertEqual(frappe.db.count(vat.LIABILITY, {"registrar": "TV3"}), 0)

    def test_income_book_and_tax_ledger_rows(self):
        d = make_doc("TV5", self.org)
        row = {
            "posting_date": d.posting_date,
            "period": frappe.utils.get_first_day(d.posting_date),
            "organization": self.org,
            "registrar_type": d.doctype,
            "registrar": d.name,
            "line_no": 1,
            "income_amount": 80,
            "vat_amount": 20,
            "document_description": "x",
            "content": "",
        }
        register_append(simplified_tax.BOOK, d, [row])
        self.assertEqual(simplified_tax.income_between(self.org, d.posting_date, d.posting_date), 80)
        simplified_tax.cancel_income(d)
        self.assertEqual(frappe.db.count(simplified_tax.BOOK), 0)
