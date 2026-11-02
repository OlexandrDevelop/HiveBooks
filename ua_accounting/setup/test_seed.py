import frappe

try:
    from frappe.tests import IntegrationTestCase
except ImportError:  # older frappe
    from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

from ua_accounting.setup import seed


class TestSeed(IntegrationTestCase):
    def test_chart_loads_twice_without_duplicates(self):
        count = frappe.db.count("UA Account")
        seed.run()
        self.assertEqual(frappe.db.count("UA Account"), count)

    def test_361_has_three_subconto(self):
        acc = frappe.get_doc("UA Account", "361")
        self.assertEqual(
            [r.subconto_type for r in acc.subconto], ["Counterparty", "Contract", "SettlementDoc"]
        )

    def test_chart_of_accounts_registers_generic_metadata(self):
        chart = frappe.get_doc("Chart of Accounts", "UA Account")
        self.assertEqual(chart.account_doctype, "UA Account")
        self.assertEqual(chart.code_field, "account_code")
        self.assertEqual(chart.subconto_type_doctype, "UA Subconto Type")
        self.assertEqual(chart.subconto_turnover_only_field, "turnover_only")

    def test_subconto_types_are_characteristics(self):
        from frappe.beeone import characteristic_chart as chart

        self.assertTrue(frappe.db.exists("Characteristic Chart", "UA Subconto Type"))
        ref = frappe.db.get_value("UA Subconto Type", "Counterparty", "reference_doctype")
        self.assertEqual(chart.get_allowed_doctypes("UA Subconto Type", "Counterparty"), [ref])
        self.assertTrue(chart.is_predefined("UA Subconto Type", "Counterparty"))
        self.assertRaises(frappe.ValidationError, frappe.delete_doc, "UA Subconto Type", "Counterparty")

    def test_classes_and_off_balance(self):
        for cls in "0123456789":
            self.assertTrue(frappe.db.exists("UA Account", cls))
        self.assertEqual(frappe.db.get_value("UA Account", "09", "off_balance"), 1)

    def test_no_erpnext_dependency(self):
        hooks = frappe.get_hooks(app_name="ua_accounting")
        self.assertFalse(hooks.get("required_apps"))
