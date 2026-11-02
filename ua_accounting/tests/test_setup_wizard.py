"""The setup wizard of HiveBooks: steps, checks of the existing doctypes, the records it makes, a first posting."""

from unittest import mock

import frappe
from frappe.beeone import setup
from frappe.tests import IntegrationTestCase

from ua_accounting.setup import wizard

IDS = [f"ua_accounting.{name}" for name in ("organization", "policy", "bank_cash", "persons", "opening")]
ORGANIZATION = {"org_name": "ТОВ «Початок»", "edrpou": "12345678", "tax_system": "Загальна система", "vat_payer": 1,
                "ipn": "123456789012"}


def make_iban(mfo="305299", account="26001234567890123"):
    """IBAN of Ukraine with right check digits: UA + 2 digits + MFO (6) + account (19)."""
    bban = (mfo + account).ljust(25, "0")
    check = 98 - int(bban + "301000") % 97
    return f"UA{check:02d}{bban}"


class TestSetupWizard(IntegrationTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if frappe.db.count(wizard.ORG):
            self.skipTest("the site has an organization: the wizard works on a site without one")
        # the core commits after a step; the test keeps everything in its transaction
        patcher = mock.patch.object(frappe.db, "commit")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(frappe.db.rollback)

    def save(self, step, values):
        result = setup.save_step(f"ua_accounting.{step}", values)
        self.assertFalse(result.get("errors"), result)
        return result

    def fill(self):
        self.save("organization", ORGANIZATION)
        self.save("policy", {"effective_from": "2026-01-01", "taxpayer_type": "Юридична особа",
                             "cost_method": "Середньозважена"})
        self.save("bank_cash", {"mfo": "305299", "bank_name": "АТ КБ «ПриватБанк»", "iban": make_iban(),
                                "account_name": "Основний рахунок", "cash_desk_name": "Основна каса"})
        self.save("persons", {"director": "Петренко Іван Степанович", "chief_accountant": "Коваль Ольга Петрівна"})

    def test_steps_are_in_the_wizard_after_the_regional_one(self):
        ids = [step["id"] for step in setup.get_steps()]
        self.assertEqual(ids[0], "frappe.regional")
        self.assertEqual([i for i in ids if i.startswith("ua_accounting.")], IDS)

    def test_wizard_text_is_ukrainian_only(self):
        for step in wizard.beeone_setup_steps():
            for text in (step["title"], step["description"], *[f.get("label", "") for f in step["fields"]],
                         *[f.get("description", "") for f in step["fields"]]):
                self.assertFalse(any("a" <= c.lower() <= "z" for c in text.replace("IBAN", "").replace("UA", "")), text)

    def test_organization_checks_are_those_of_the_doctype_and_tax_rules(self):
        errors = wizard.check_organization({**ORGANIZATION, "edrpou": "123"})
        self.assertEqual(list(errors), ["edrpou"])
        self.assertIn("ЄДРПОУ", errors["edrpou"])
        self.assertEqual(list(wizard.check_organization({**ORGANIZATION, "ipn": ""})), ["ipn"])
        self.assertEqual(list(wizard.check_organization({**ORGANIZATION, "ipn": "12AB"})), ["ipn"])
        self.assertEqual(wizard.check_organization(ORGANIZATION), {})

    def test_step_refuses_wrong_values_and_saves_nothing(self):
        result = setup.save_step("ua_accounting.organization", {**ORGANIZATION, "edrpou": "123"})
        self.assertIn("edrpou", result["errors"])
        self.assertEqual(frappe.db.count(wizard.ORG), 0)
        missing = setup.save_step("ua_accounting.organization", {"org_name": "X"})
        self.assertIn("edrpou", missing["errors"])

    def test_iban_checks(self):
        values = {"mfo": "305299", "iban": make_iban()}
        self.save("organization", ORGANIZATION)
        self.assertEqual(wizard.check_bank_cash(values), {})
        self.assertEqual(list(wizard.check_bank_cash({**values, "iban": "UA12" + "0" * 25})), ["iban"])
        self.assertEqual(list(wizard.check_bank_cash({**values, "iban": "PL" + "1" * 27})), ["iban"])
        self.assertEqual(list(wizard.check_bank_cash({**values, "mfo": "12"})), ["mfo"])

    def test_policy_rules_of_the_single_tax_apply(self):
        self.save("organization", {**ORGANIZATION, "vat_payer": 0, "ipn": "", "tax_system": "Єдиний податок, 1 група"})
        errors = wizard.check_policy({"effective_from": "2026-01-01", "taxpayer_type": "Юридична особа",
                                      "cost_method": "ФІФО"})
        self.assertEqual(list(errors), ["taxpayer_type"])
        self.assertEqual(wizard.check_policy({"effective_from": "2026-01-01", "taxpayer_type": "ФОП",
                                              "cost_method": "ФІФО"}), {})

    def test_steps_need_the_organization_first(self):
        with self.assertRaises(frappe.ValidationError):
            wizard.save_policy({"effective_from": "2026-01-01", "taxpayer_type": "ФОП", "cost_method": "ФІФО"})

    def test_wizard_creates_the_records_with_links(self):
        self.fill()
        org = frappe.get_doc(wizard.ORG, wizard._organization())
        self.assertEqual((org.org_name, org.edrpou, org.vat_payer), (ORGANIZATION["org_name"], "12345678", 1))
        self.assertEqual(frappe.db.get_value(wizard.PERSON, org.director, "full_name"), "Петренко Іван Степанович")
        self.assertEqual(frappe.db.get_value(wizard.PERSON, org.chief_accountant, "full_name"), "Коваль Ольга Петрівна")
        policy = frappe.get_doc(wizard.POLICY, wizard._wizard_policy(org.name))
        self.assertEqual((str(policy.effective_from), policy.vat_payer), ("2026-01-01", 1))
        account = frappe.get_doc(wizard.BANK_ACCOUNT, wizard._bank_account(org.name))
        self.assertEqual((account.iban, account.bank, account.is_default), (make_iban(), "305299", 1))
        self.assertTrue(wizard._cash_desk(org.name))

    def test_saving_a_step_again_changes_the_same_records(self):
        self.fill()
        counts = {dt: frappe.db.count(dt) for dt in (wizard.ORG, wizard.POLICY, wizard.BANK_ACCOUNT, wizard.CASH_DESK,
                                                     wizard.PERSON, wizard.BANK)}
        self.save("organization", {**ORGANIZATION, "org_name": "ТОВ «Інша назва»", "vat_payer": 0, "ipn": ""})
        self.save("persons", {"director": "Петренко І. С."})
        self.save("bank_cash", {"mfo": "305299", "bank_name": "АТ КБ «ПриватБанк»", "iban": make_iban(),
                                "account_name": "Рахунок", "cash_desk_name": "Каса"})
        for doctype in (wizard.ORG, wizard.POLICY, wizard.BANK_ACCOUNT, wizard.CASH_DESK, wizard.BANK):
            self.assertEqual(frappe.db.count(doctype), counts[doctype], doctype)
        org = frappe.get_doc(wizard.ORG, wizard._organization())
        self.assertEqual(org.org_name, "ТОВ «Інша назва»")
        self.assertFalse(org.chief_accountant)
        # the policy follows the tax data of the organization
        self.assertEqual(frappe.db.get_value(wizard.POLICY, wizard._wizard_policy(org.name), "vat_payer"), 0)

    def test_opening_balances_are_posted_and_can_be_changed(self):
        self.fill()
        self.save("opening", {"posting_date": "2026-01-01", "cash": 5000, "bank": 120000})
        name = wizard._opening_document(wizard._organization()).name
        self.assertEqual(frappe.db.get_value(wizard.OPENING, name, "docstatus"), 1)
        self.assertTrue(frappe.db.exists("UA Accounting Entry", {"registrar": name}))
        self.assertEqual(wizard.load_opening()["bank"], 120000)
        self.save("opening", {"posting_date": "2026-01-01", "cash": 7000})
        document = wizard._opening_document(wizard._organization())
        self.assertEqual(sorted(row.amount for row in document.rows), [7000])

    def test_opening_is_the_only_step_that_can_be_skipped(self):
        by_id = {step["id"]: step for step in wizard.beeone_setup_steps()}
        self.assertEqual([i for i, s in by_id.items() if s.get("optional")], ["ua_accounting.opening"])

    def test_first_document_can_be_posted_after_the_wizard(self):
        self.fill()
        organization = wizard._organization()
        desk = wizard._cash_desk(organization)
        document = frappe.get_doc(
            {
                "doctype": "UA Journal Operation",
                "organization": organization,
                "posting_date": "2026-01-15",
                "content": "Перший документ",
                "entries": [{"account_dr": "301", "account_cr": "401", "amount": 100, "subconto_dr1": desk,
                             "subconto_dr1_type": "UA Cash Desk", "content": "Перший документ"}],
            }
        )
        document.insert()
        document.submit()
        self.assertEqual(document.docstatus, 1)
        self.assertTrue(frappe.db.exists("UA Accounting Entry", {"registrar": document.name}))

    def test_demo_is_offered_only_on_an_empty_site(self):
        allowed, _reason = setup.demo_allowed()
        self.assertTrue(allowed)
        self.save("organization", ORGANIZATION)
        allowed, reason = setup.demo_allowed()
        self.assertFalse(allowed)
        self.assertTrue(reason)
