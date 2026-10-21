import frappe
from frappe.utils import get_first_day, getdate, now


def first_of_month(date):
    return get_first_day(getdate(date))


def std_columns():
    """Standard columns for rows written with raw SQL / bulk_insert."""
    return {
        "owner": frappe.session.user,
        "modified_by": frappe.session.user,
        "creation": now(),
        "modified": now(),
        "docstatus": 0,
        "idx": 0,
    }


def pick(doc, entry, key):
    """Value from the entry dict, or from the registrar document."""
    value = entry.get(key)
    if value in (None, ""):
        value = doc.get(key)
    return value
