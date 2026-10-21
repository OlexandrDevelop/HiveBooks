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

    def test_classes_and_off_balance(self):
        for cls in "0123456789":
            self.assertTrue(frappe.db.exists("UA Account", cls))
        self.assertEqual(frappe.db.get_value("UA Account", "09", "off_balance"), 1)

    def test_no_erpnext_dependency(self):
        hooks = frappe.get_hooks(app_name="ua_accounting")
        self.assertFalse(hooks.get("required_apps"))
