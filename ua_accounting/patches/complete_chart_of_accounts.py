"""Bring the chart of accounts of existing sites to the current edition of order 291.

The seed loader only inserts, so this patch runs once and:
1. inserts the accounts that are missing;
2. moves the old entries of account 40 to 401 (40 is now a group, like in 1C);
3. fixes names, types, group and currency flags of accounts that were wrong.

An account with entries gets only a new name and type. Its group flag,
currency flag and subconto stay, because they are part of the totals keys.
The only exception is the currency flag of 361: it is cleared when no entry
of 361 has a currency amount, so the totals keys do not change.
"""

import frappe

from ua_accounting.setup import seed
from ua_accounting.ua_core.doctype.ua_account.ua_account import has_entries

# accounts that exist in the old seed and changed: code -> fields to bring to the seed value
FIXES = {
    "18": ("group",),
    "021": ("name",),
    "022": ("name",),
    "023": ("name",),
    "024": ("name",),
    "33": ("name",),
    "331": ("name",),
    "332": ("name",),
    "361": ("currency",),
    "40": ("name", "group"),
    "41": ("name", "group"),
    "71": ("group",),
    "73": ("group",),
    "80": ("name", "group"),
    "81": ("group",),
    "82": ("group",),
    "83": ("group",),
    "84": ("group",),
    "704": ("type",),
}


def execute():
    nodes = {}

    def collect(node):
        nodes[node["code"]] = node
        for child in node.get("children", []):
            collect(child)

    for node in seed._read("chart_of_accounts_ua.json"):
        collect(node)

    # new accounts first: 401 must exist before the entries of 40 move to it
    seed.load_chart()
    move_account("40", "401")

    for code, fields in FIXES.items():
        if frappe.db.exists("UA Account", code):
            fix_account(frappe.get_doc("UA Account", code), nodes[code], fields)
    frappe.db.commit()


def move_account(old, new):
    """Point every link to the old account at the new one (entries, totals, document rows)."""
    if not (frappe.db.exists("UA Account", old) and frappe.db.exists("UA Account", new)):
        return
    if frappe.db.exists("UA Account Turnover", {"account": new}):
        print(f"UA Account {new} already has totals: entries of {old} not moved")
        return
    links = frappe.db.sql(
        """select parent, fieldname from `tabDocField`
        where fieldtype = 'Link' and options = 'UA Account' and parent != 'UA Account'""",
        as_dict=True,
    )
    for link in links:
        table = f"tab{link.parent}"
        if frappe.db.table_exists(link.parent):
            frappe.db.sql(f"update `{table}` set `{link.fieldname}` = %s where `{link.fieldname}` = %s", (new, old))


def fix_account(doc, node, fields):
    posted = has_entries(doc.name)
    if "name" in fields:
        doc.account_name = node["name"]
    if "type" in fields:
        doc.account_type = node["type"]
    if "group" in fields and not posted:
        doc.is_group = node.get("is_group", 0)
        doc.subconto = []
    elif "group" in fields:
        print(f"UA Account {doc.name} has entries: group flag not changed")
    if "currency" in fields:
        if not posted:
            doc.currency_accounting = node.get("currency", 0)
        elif not has_currency_amounts(doc.name):
            frappe.db.set_value("UA Account", doc.name, "currency_accounting", node.get("currency", 0), update_modified=False)
            doc.currency_accounting = node.get("currency", 0)
        else:
            print(f"UA Account {doc.name} has currency entries: currency flag not changed")
    doc.flags.ignore_permissions = True
    doc.save()


def has_currency_amounts(account):
    for side in ("dr", "cr"):
        if frappe.db.sql(
            f"select 1 from `tabUA Accounting Entry` where account_{side} = %s "
            f"and (ifnull(currency_{side}, '') != '' or ifnull(currency_amount_{side}, 0) != 0) limit 1",
            account,
        ):
            return True
    return bool(
        frappe.db.sql(
            "select 1 from `tabUA Account Turnover` where account = %s and ifnull(currency, '') != '' limit 1",
            account,
        )
    )
