import json

import frappe

from ua_accounting.accounting import vat_assistant as va
from ua_accounting.api.helpers import check_access


@frappe.whitelist(methods=["GET", "POST"])
def get_status(organization, date_from, date_to, as_of):
    """Tax invoices to issue and to register, deadlines of the VAT return."""
    check_access(organization)
    return va.get_status(organization, date_from, date_to, as_of)


@frappe.whitelist(methods=["POST"])
def compare_with_erpn(organization, direction, rows, date_from=None, date_to=None):
    """Compare a register from ЄРПН with the tax invoices of the books."""
    check_access(organization)
    if isinstance(rows, str):
        rows = json.loads(rows or "[]")
    return va.compare_with_erpn(organization, direction, rows, date_from, date_to)
