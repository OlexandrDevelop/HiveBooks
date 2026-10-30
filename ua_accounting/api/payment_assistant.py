import frappe

from ua_accounting.accounting import payment_assistant as pa
from ua_accounting.api.helpers import check_access


@frappe.whitelist(methods=["GET", "POST"])
def get_proposals(organization, date, horizon_days=0, bank_account=None):
    """Supplier invoices and taxes that are due: what to pay."""
    check_access(organization)
    return pa.get_proposals(organization, date, horizon_days, bank_account)


@frappe.whitelist(methods=["POST"])
def create_orders(organization, bank_account, items, date, auto_submit=0):
    """Payment orders from the proposal rows. Rows that cannot be paid are skipped with a reason."""
    check_access(organization)
    return pa.create_orders(organization, bank_account, items, date, auto_submit)
