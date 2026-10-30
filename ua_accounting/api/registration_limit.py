"""Registration limit of tax invoices (СЕА): local estimate, no query to ДПС."""

import frappe
from frappe.utils import flt

from ua_accounting.accounting import vat_calc


@frappe.whitelist(methods=["POST"])
def get(organization, as_of):
    frappe.has_permission("UA Tax Invoice", "read", throw=True)
    return vat_calc.registration_limit(organization, as_of)


@frappe.whitelist(methods=["POST"])
def check(organization, as_of, vat_amount):
    frappe.has_permission("UA Tax Invoice", "read", throw=True)
    available = vat_calc.registration_limit(organization, as_of)["available"]
    amount = flt(vat_amount, 2)
    return {"ok": amount <= available, "available": available, "shortfall": max(flt(amount - available, 2), 0.0)}
