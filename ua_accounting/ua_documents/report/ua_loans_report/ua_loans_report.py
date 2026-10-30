import frappe

from ua_accounting.reporting import settlements


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = settlements.loan_columns()
    if not (filters.organization and filters.date_to):
        return columns, []
    return columns, settlements.loan_rows(filters)
