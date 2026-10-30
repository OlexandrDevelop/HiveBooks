"""Reads of registers as the system, without the rights of the user."""

from contextlib import contextmanager

import frappe


@contextmanager
def system_reads():
    """Dated parameters and rates are facts of the whole base: every caller may use them, whatever its role."""
    user = frappe.session.user
    if user == "Administrator":
        yield
        return
    frappe.set_user("Administrator")
    try:
        yield
    finally:
        frappe.set_user(user)
