import frappe

from ua_accounting.accounting import monitor
from ua_accounting.api.helpers import MANAGER_ROLES, check_access


@frappe.whitelist(methods=["GET", "POST"])
def get_widgets(organization, date_from, date_to):
    """Money, debts, sales and profit for the head of the company."""
    check_access(organization, MANAGER_ROLES)
    return monitor.get_widgets(organization, date_from, date_to)
