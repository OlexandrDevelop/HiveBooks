import frappe

from ua_accounting.reporting import settlements


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = settlements.founder_columns()
    if not (filters.organization and filters.date_from and filters.date_to):
        return columns, []
    return columns, settlements.founder_rows(filters)
