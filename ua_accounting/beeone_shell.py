"""HiveBooks navigation supplied to the country-neutral BeeOne desktop shell."""

import frappe


def sections(user=None):
    """Return the accounting catalog for BeeOne's multi-window desktop."""
    user = user or frappe.session.user
    if user == "Guest":
        return []

    docs = []
    refs = []
    for row in frappe.get_all(
        "DocType",
        filters={"name": ("like", "UA %"), "istable": 0},
        fields=["name", "module"],
        order_by="name asc",
    ):
        item = {"type": "doctype", "target": row.name, "label": frappe._(row.name)}
        if "Catalog" in (row.module or ""):
            refs.append(item)
        else:
            docs.append(item)

    commands = [
        {"column": "docs", "type": "page", "target": "ua-home", "label": "Головне", "main": True},
        *[{**item, "column": "refs"} for item in refs],
        *[{**item, "column": "docs"} for item in docs],
    ]
    return [
        {
            "id": "hivebooks",
            "label": "HiveBooks",
            "description": "Український бухгалтерський облік",
            "icon": "book",
            "order": 10,
            "commands": commands,
            "create": [],
        }
    ]
