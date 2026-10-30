"""Access checks shared by the accountant helper methods."""

import frappe
from frappe import _

from ua_accounting.administration import report_scope

ACCOUNTANT_ROLES = {"UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager"}
MANAGER_ROLES = {"UA Accounting Manager", "UA Chief Accountant", "System Manager"}


def check_access(organization, roles=ACCOUNTANT_ROLES):
    """The user has one of the roles and may use the organization."""
    if not roles.intersection(frappe.get_roles()):
        frappe.throw(_("Немає прав для цієї дії"), frappe.PermissionError)
    if organization:
        report_scope(organization)
