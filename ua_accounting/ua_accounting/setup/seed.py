"""Seed data loader.

Insert-only and idempotent: a record that exists is never changed,
so edits made by users stay. Order: roles, UOM, currencies, VAT rates,
tax types, subconto types, chart of accounts.
"""

import json
import os

import frappe

DATA = os.path.join(os.path.dirname(__file__), "data")
ROLES = ("UA Accountant", "UA Accounting Manager")


def run():
    create_roles()
    load_uoms()
    load_currencies()
    load_vat_rates()
    load_tax_types()
    load_subconto_types()
    load_chart()
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
