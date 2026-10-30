"""Append only history of UA documents and catalogs.

A thin wrapper over the beeone core change log (`frappe.beeone.change_log`): the core finds the
changes, writes the Version entry and checks the read rights. This module only says which
documents are tracked and copies each entry to the Ukrainian `UA Change Log` (labels, organization).
"""

import frappe
from frappe.beeone import change_log
from frappe.utils import now_datetime

ACTIONS = {"Create": "Створення", "Update": "Зміна", "Submit": "Проведення", "Cancel": "Скасування", "Delete": "Видалення"}


def _tracked(doc):
    return doc.meta.module in {"UA Documents", "UA Catalogs", "UA Core"} and doc.doctype not in {
        "UA Change Log", "UA Change Log Row", "UA Accounting Entry", "UA Account Turnover",
        "UA VAT Liability Entry", "UA VAT Credit Entry",
    } and not doc.meta.istable and not doc.meta.issingle


is_tracked = _tracked


def on_entry(doc, entry):
    """Core sink: copy a Version entry to UA Change Log (only for the documents of this app)."""
    if not _tracked(doc):
        return
    data = frappe.parse_json(entry.data or "{}").get("change_log") or {}
    if entry.flags.get("retired_as"):
        frappe.db.set_value("UA Change Log", {"ref_doctype": doc.doctype, "ref_name": doc.name}, "ref_name",
                            entry.flags.retired_as, update_modified=False)
    log = frappe.get_doc({"doctype": "UA Change Log", "ref_doctype": doc.doctype, "ref_name": doc.name,
                          "organization": doc.name if doc.doctype == "UA Organization" else doc.get("organization"),
                          "action": ACTIONS[entry.action], "user": frappe.session.user, "timestamp": now_datetime(),
                          "rows": data.get("rows") or []})
    frappe.flags.ua_audit_write = True
    try:
        log.insert(ignore_permissions=True)
    finally:
        frappe.flags.ua_audit_write = False


def log_has_permission(doc, ptype=None, user=None, debug=False):
    """A log row is readable only with the right to read its source document."""
    from ua_accounting.administration import has_permission

    user = user or frappe.session.user
    if not has_permission(doc, ptype, user):
        return False
    if doc.is_new() or user == "Administrator":
        return True
    if not doc.ref_doctype or not frappe.db.exists("DocType", doc.ref_doctype):
        return False
    if frappe.db.exists(doc.ref_doctype, doc.ref_name):
        return bool(frappe.has_permission(doc.ref_doctype, "read", doc.ref_name, user=user))
    return change_log.can_read_deleted(doc.ref_doctype, doc.ref_name, user)


def log_permission_query(user=None, doctype=None):
    """List filter: organization scope plus the read rights on the source documents."""
    from ua_accounting.administration import permission_query

    user = user or frappe.session.user
    clauses = [permission_query(user, "UA Change Log")]
    if user == frappe.session.user and user != "Administrator":
        from frappe.permissions import get_user_permissions

        restricted = bool(get_user_permissions(user))
        for ref_doctype in frappe.get_all("UA Change Log", fields=["ref_doctype"], group_by="ref_doctype", pluck="ref_doctype"):
            escaped = frappe.db.escape(ref_doctype)
            if not frappe.db.exists("DocType", ref_doctype) or not frappe.has_permission(ref_doctype, "read"):
                clauses.append(f"`tabUA Change Log`.`ref_doctype` != {escaped}")
                continue
            if not (restricted or ref_doctype in PRIVATE_DOCTYPES):
                continue
            names = set(frappe.get_all("UA Change Log", filters={"ref_doctype": ref_doctype}, pluck="ref_name"))
            allowed = change_log.readable_names(ref_doctype, names)
            if allowed == names:
                continue
            if not allowed:
                clauses.append(f"`tabUA Change Log`.`ref_doctype` != {escaped}")
                continue
            values = ", ".join(frappe.db.escape(str(n)) for n in sorted(allowed, key=str))
            clauses.append(f"(`tabUA Change Log`.`ref_doctype` != {escaped} or `tabUA Change Log`.`ref_name` in ({values}))")
    return " and ".join(c for c in clauses if c)


PRIVATE_DOCTYPES = {"UA Report Variant"}


def log_context(doc):
    """Kept with the Delete entry: what the organization and warehouse rights need later."""
    warehouses = {doc.get(f) for f in ("warehouse", "warehouse_from", "warehouse_to") if doc.meta.has_field(f) and doc.get(f)}
    for table in doc.meta.get_table_fields():
        warehouses.update(row.get("warehouse") for row in doc.get(table.fieldname) or [] if row.get("warehouse"))
    return {"organization": doc.name if doc.doctype == "UA Organization" else doc.get("organization"),
            "warehouse": doc.name if doc.doctype == "UA Warehouse" else None,
            "warehouses": sorted(warehouses)}


def deleted_access(doctype, name, info, user):
    """Who may read the history of a deleted record: the same scope rules as for the live record."""
    from ua_accounting.administration import _scope

    if not doctype.startswith("UA ") or not frappe.has_permission(doctype, "read", user=user):
        return False
    context = info.get("context")
    if context is None:
        return False  # an entry from before the context was kept: cannot be checked
    others = frappe.get_all("User Permission", filters={"user": user, "allow": ("not in", ["UA Organization", "UA Warehouse"])},
                            limit_page_length=1)
    if others:
        return False  # a record restriction we cannot evaluate on the kept data
    if doctype in PRIVATE_DOCTYPES:
        return info.get("doc_owner") == user
    scope = _scope(user)
    if scope["organizations"] and context.get("organization") and context["organization"] not in scope["organizations"]:
        return False
    if scope["warehouses"]:
        values = set(context.get("warehouses") or []) | ({context["warehouse"]} if context.get("warehouse") else set())
        if values - set(scope["warehouses"]):
            return False
    return True


def record_change(doc, rows):
    change_log.record_change(doc, rows)


@frappe.whitelist()
def get_history(doctype, name):
    frappe.has_permission("UA Change Log", "read", throw=True)
    if not doctype.startswith("UA "):
        frappe.throw("Недопустимий тип документа", frappe.PermissionError)
    change_log.check_history_access(doctype, name)
    names = frappe.get_list("UA Change Log", filters={"ref_doctype": doctype, "ref_name": name},
                            pluck="name", order_by="timestamp desc, creation desc")
    return [frappe.get_doc("UA Change Log", key).as_dict() for key in names]
