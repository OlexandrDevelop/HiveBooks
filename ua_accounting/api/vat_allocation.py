import frappe

from ua_accounting.accounting import vat_calc


@frappe.whitelist(methods=["POST"])
def calculate(organization, period_from, period_to, taxable_ops=None, exempt_ops=None, **kwargs):
    """Share of taxable operations and the allowed / not allowed part of the VAT credit.

    The credit is always taken from the VAT credit register (a value passed by the caller is ignored).
    """
    frappe.has_permission("UA VAT Allocation", "read", throw=True)
    return vat_calc.allocate(organization, period_from, period_to, taxable_ops, exempt_ops)
