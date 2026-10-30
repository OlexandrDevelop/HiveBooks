"""Відомість спецодягу в експлуатації по працівниках: items in use by person and department on a date."""

import frappe
from frappe.utils import today

from ua_accounting.accounting.special_wear import in_use_rows


def execute(filters=None):
    filters = frappe._dict(filters or {})
    columns = [
        {"fieldname": "person", "label": "Працівник", "fieldtype": "Link", "options": "UA Person", "width": 200},
        {"fieldname": "department", "label": "Підрозділ", "fieldtype": "Link", "options": "UA Department", "width": 180},
        {"fieldname": "item", "label": "Номенклатура", "fieldtype": "Link", "options": "UA Item", "width": 240},
        {"fieldname": "quantity", "label": "Кількість", "fieldtype": "Float", "width": 100},
        {"fieldname": "cost", "label": "Вартість", "fieldtype": "Currency", "width": 120},
        {"fieldname": "issue_date", "label": "Дата передачі", "fieldtype": "Date", "width": 110},
        {"fieldname": "written_off", "label": "Списано", "fieldtype": "Currency", "width": 120},
        {"fieldname": "remaining", "label": "Залишок вартості", "fieldtype": "Currency", "width": 120},
        {"fieldname": "issue", "label": "Документ передачі", "fieldtype": "Link", "options": "UA Special Wear Issue", "width": 160},
    ]
    if not filters.organization:
        return columns, []
    rows = in_use_rows(filters.organization, filters.date_to or today(), filters.person, filters.department)
    return columns, rows
