"""Seed data loader.

Insert-only and idempotent: a record that exists is never changed,
so edits made by users stay. Order: roles, UOM, currencies, VAT rates,
tax types, subconto types, chart of accounts.
"""

import json
import os

import frappe

from ua_accounting.accounting.simplified_tax import SIMPLE_CHART_ACCOUNTS
from ua_accounting.patches import seed_regulatory_forms, seed_regulatory_parameters
from ua_accounting.setup import print_formats

DATA = os.path.join(os.path.dirname(__file__), "data")
ROLES = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "UA Cashier",
         "UA HR Officer", "UA Administrator")


def run():
    create_roles()
    load_uoms()
    load_currencies()
    setup_default_currency()
    load_vat_rates()
    load_tax_types()
    load_subconto_types()
    load_chart()
    seed_regulatory_parameters.execute()
    seed_regulatory_forms.execute()
    fix_contract_titles()
    ukrainian_admin_name()
    setup_print_style()
    print_formats.run()
    add_deletion_mark()
    setup_exchange()
    frappe.db.commit()


def _read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def _insert(doctype, values):
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def create_roles():
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            _insert("Role", {"role_name": role, "desk_access": 1})


def load_uoms():
    for short_name, code, full_name, intl in _read("uoms.json"):
        if not frappe.db.exists("UA UOM", short_name):
            _insert(
                "UA UOM",
                {
                    "short_name": short_name,
                    "code": code,
                    "full_name": full_name,
                    "international_code": intl,
                },
            )


def load_currencies():
    for code, name, numeric, is_base in _read("currencies.json"):
        if not frappe.db.exists("UA Currency", code):
            _insert(
                "UA Currency",
                {
                    "currency_code": code,
                    "currency_name": name,
                    "numeric_code": numeric,
                    "is_base": is_base,
                },
            )


def setup_default_currency():
    """Make hryvnia the system currency, so amounts show "₴" and not "$"."""
    if frappe.db.exists("Currency", "UAH"):
        frappe.db.set_value(
            "Currency",
            "UAH",
            {
                "enabled": 1,
                "symbol": "₴",
                "symbol_on_right": 1,
                "number_format": "# ###,##",
            },
        )
    # one look for every currency: "1 234,56 €"
    for code in frappe.get_all("UA Currency", pluck="name"):
        if code != "UAH" and frappe.db.exists("Currency", code):
            frappe.db.set_value(
                "Currency", code, {"enabled": 1, "symbol_on_right": 1, "number_format": "# ###,##"}
            )
    frappe.db.set_default("currency", "UAH")
    if frappe.db.get_single_value("System Settings", "currency") != "UAH":
        frappe.db.set_single_value("System Settings", "currency", "UAH")
    # uk look for numbers and dates: "1 234,56" and "21.10.2026"
    # set only while the value is still empty or a Frappe default, so user changes stay
    frappe_defaults = {
        "number_format": (None, "", "#,###.##"),
        "date_format": (None, "", "mm-dd-yyyy", "yyyy-mm-dd"),
    }
    for key, value in (("number_format", "# ###,##"), ("date_format", "dd.mm.yyyy")):
        if frappe.db.get_single_value("System Settings", key) in frappe_defaults[key]:
            frappe.db.set_single_value("System Settings", key, value)
            frappe.db.set_default(key, value)
    frappe.clear_cache()


def add_deletion_mark():
    """Hidden flag "marked for deletion" on every UA document and catalog."""
    from ua_accounting.desk import DOCUMENTS, MARK_FIELD

    catalogs = frappe.get_all(
        "DocType", filters={"module": "UA Catalogs", "istable": 0, "issingle": 0}, pluck="name"
    )
    for doctype in (*DOCUMENTS, *catalogs):
        if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": MARK_FIELD}):
            continue
        frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": doctype,
                "fieldname": MARK_FIELD,
                "label": "Marked for deletion",
                "fieldtype": "Check",
                "hidden": 1,
                "no_copy": 1,
                "allow_on_submit": 1,
            }
        ).insert(ignore_permissions=True)


PRINT_STYLE = "UA"
PRINT_CSS = """
.print-format { font-size: 12px; }
.print-format table { table-layout: auto; width: 100%; }
.print-format td, .print-format th { padding: 4px 6px !important; }
.print-format td.text-right, .print-format th.text-right,
.print-format td.text-right *, .print-format th.text-right * { white-space: nowrap; }
.print-format td.text-right { font-variant-numeric: tabular-nums; }
"""


def setup_print_style():
    """Printed tables keep every amount on one line. Own style, set as the default."""
    if not frappe.db.exists("Print Style", PRINT_STYLE):
        _insert("Print Style", {"print_style_name": PRINT_STYLE, "css": PRINT_CSS, "disabled": 0})
    else:
        frappe.db.set_value("Print Style", PRINT_STYLE, "css", PRINT_CSS, update_modified=False)
    current = frappe.db.get_single_value("Print Settings", "print_style")
    # a style the user chose by hand stays; the standard styles of Frappe are replaced
    if not current or frappe.db.get_value("Print Style", current, "standard"):
        frappe.db.set_single_value("Print Settings", "print_style", PRINT_STYLE)


def ukrainian_admin_name():
    """The built-in user is shown in the top bar: give it a Ukrainian name once."""
    if frappe.db.get_value("User", "Administrator", "full_name") == "Administrator":
        frappe.db.set_value(
            "User", "Administrator", {"first_name": "Адміністратор", "full_name": "Адміністратор"}
        )


def fix_contract_titles():
    """Contracts without a number get a readable title, not the hash name."""
    from ua_accounting.ua_catalogs.doctype.ua_counterparty_contract.ua_counterparty_contract import make_title

    rows = frappe.get_all(
        "UA Counterparty Contract",
        fields=["name", "counterparty", "contract_no", "contract_date", "contract_title"],
    )
    for row in rows:
        title = make_title(frappe._dict(row))
        if row.contract_title != title:
            frappe.db.set_value("UA Counterparty Contract", row.name, "contract_title", title, update_modified=False)


def load_vat_rates():
    for code, name, rate, taxable in _read("vat_rates.json"):
        if not frappe.db.exists("UA VAT Rate", code):
            _insert(
                "UA VAT Rate",
                {"rate_code": code, "rate_name": name, "rate": rate, "is_taxable": taxable},
            )


def load_tax_types():
    for code, name in _read("tax_types.json"):
        if not frappe.db.exists("UA Tax Type", code):
            _insert("UA Tax Type", {"tax_code": code, "tax_name": name})


def load_subconto_types():
    for code, name, reference, dynamic in _read("subconto_types.json"):
        if not frappe.db.exists("UA Subconto Type", code):
            _insert(
                "UA Subconto Type",
                {
                    "subconto_code": code,
                    "subconto_name": name,
                    "reference_doctype": reference or None,
                    "is_dynamic": dynamic,
                },
            )


def load_chart():
    for node in _read("chart_of_accounts_ua.json"):
        _load_account(node, None)


def _load_account(node, parent):
    code = node["code"]
    # parents are inserted before children, so tree order stays right
    if not frappe.db.exists("UA Account", code):
        _insert(
            "UA Account",
            {
                "account_code": code,
                "account_name": node["name"],
                "parent_ua_account": parent,
                "is_group": node.get("is_group", 0),
                "account_type": node["type"],
                "off_balance": node.get("off_balance", 0),
                "currency_accounting": node.get("currency", 0),
                "quantity_accounting": node.get("quantity", 0),
                "predefined": 1,
                "in_simplified_chart": 1 if code in SIMPLE_CHART_ACCOUNTS else 0,
                "subconto": [
                    {
                        "subconto_type": t,
                        "turnover_only": to,
                        "quantity": q,
                        "currency": c,
                    }
                    for t, to, q, c in node.get("subconto", [])
                ],
            },
        )
    for child in node.get("children", []):
        _load_account(child, code)


EXCHANGE_RULES = (
    # (name, handler, direction): handlers of files are called by the API with the file; the rule is the switch and the journal key
    ("NBU rates", "nbu_rates", "Import"),
    ("NBU banks", "banks", "Import"),
    ("Bank statement import", "bank_statement", "Import"),
    ("Payment orders export", "payment_orders", "Export"),
    ("1C catalogs import", "catalogs_1c", "Import"),
    ("1C balances import", "balances_1c", "Import"),
    ("Excel catalogs import", "catalogs_excel", "Import"),
    ("Excel balances import", "balances_excel", "Import"),
    ("Classifier import", "classifier", "Import"),
    ("Tax invoices export", "tax_invoices", "Export"),
)
NBU_MAPPING = (("cc", "cc", "Upper"), ("rate", "rate", "Number"), ("exchangedate", "exchangedate", ""))


def setup_exchange_rules():
    """Rules of the core exchange framework; insert-only, so changes of an administrator stay."""
    for name, handler, direction in EXCHANGE_RULES:
        if frappe.db.exists("Exchange Rule", name):
            continue
        doc = frappe.new_doc("Exchange Rule")
        doc.update({"rule_name": name, "handler": handler, "direction": direction, "enabled": 1, "schedule": "Manual"})
        if handler == "nbu_rates":
            doc.schedule = "Daily" if frappe.db.get_single_value("UA Exchange Settings", "auto_load_rates") else "Manual"
            for source, target, transform in NBU_MAPPING:
                doc.append("mappings", {"source": source, "target": target, "transform": transform})
        doc.insert(ignore_permissions=True)


def setup_exchange():
    """Exchange settings keep their defaults once saved; the daily job follows the setting."""
    from ua_accounting.ua_core.doctype.ua_exchange_settings.ua_exchange_settings import sync_job

    if not frappe.db.sql("select 1 from `tabSingles` where doctype = %s and field = %s", ("UA Exchange Settings", "nbu_rates_url")):
        settings = frappe.get_single("UA Exchange Settings")
        settings.flags.ignore_permissions = True
        settings.save()
    setup_exchange_rules()
    sync_job(frappe.db.get_single_value("UA Exchange Settings", "auto_load_rates"))
    # items imported from 1C with «БезНДС» get this rate
    if not frappe.db.exists("UA VAT Rate", "Без ПДВ"):
        _insert("UA VAT Rate", {"rate_code": "Без ПДВ", "rate_name": "Без ПДВ", "rate": 0, "is_taxable": 0})
