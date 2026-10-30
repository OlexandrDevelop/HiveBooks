"""Write the rows of every `UA Currency.rates` to the rate register (UA Exchange Rate). Idempotent."""

import frappe

from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import sync_rates


def execute():
    for name in frappe.get_all("UA Currency", pluck="name"):
        sync_rates(frappe.get_doc("UA Currency", name))
