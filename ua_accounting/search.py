"""Link field search of the app.

Frappe shows the internal name under every result of a link search. Catalogs of this app
have hash names, so the user would see "gve4rnp7g2". Here the name is removed
from the description; the title (the bold line) stays.
"""

import frappe
from frappe.desk.search import search_link as frappe_search_link


@frappe.whitelist()
def search_link(
    doctype: str,
    txt: str,
    query: str | None = None,
    filters: str | dict | list | None = None,
    page_length: int = 10,
    searchfield: str | None = None,
    reference_doctype: str | None = None,
    ignore_user_permissions: bool = False,
    *,
    link_fieldname: str | None = None,
):
    results = frappe_search_link(
        doctype,
        txt,
        query=query,
        filters=filters,
        page_length=page_length,
        searchfield=searchfield,
        reference_doctype=reference_doctype,
        ignore_user_permissions=ignore_user_permissions,
        link_fieldname=link_fieldname,
    )
    if frappe.get_meta(doctype).autoname == "hash":
        results = [hide_name(row) for row in results]
    return results


def hide_name(row):
    row = dict(row)
    parts = [p for p in (row.get("description") or "").split(", ") if p and p != row.get("value")]
    row["description"] = ", ".join(parts)
    return row
