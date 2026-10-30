"""Organization and warehouse access, and the accounting period lock."""

import frappe
from frappe.utils import getdate


def _scope(user):
    rows = frappe.get_all(
        "User Permission", filters={"user": user, "allow": ("in", ["UA Organization", "UA Warehouse"])},
        fields=["allow", "for_value"],
    )
    return {
        "organizations": [r.for_value for r in rows if r.allow == "UA Organization"] or None,
        "warehouses": [r.for_value for r in rows if r.allow == "UA Warehouse"] or None,
    }


TRANSFER_FIELDS = ("warehouse_from", "warehouse_to")


def _permitted(doc, scope):
    orgs, warehouses = scope["organizations"], scope["warehouses"]
    org = doc.name if doc.doctype == "UA Organization" else doc.get("organization") if doc.meta.has_field("organization") else None
    if orgs and org is not None and org not in orgs:
        return False
    if warehouses:
        value = doc.name if doc.doctype == "UA Warehouse" else doc.get("warehouse") if doc.meta.has_field("warehouse") else None
        if value and value not in warehouses:
            return False
        for field in TRANSFER_FIELDS:
            if doc.meta.has_field(field) and doc.get(field) and doc.get(field) not in warehouses:
                return False
        for table in doc.meta.get_table_fields():
            for row in doc.get(table.fieldname) or []:
                if row.get("warehouse") and row.warehouse not in warehouses:
                    return False
    return True


def has_permission(doc, ptype=None, user=None, debug=False):
    return _permitted(doc, _scope(user or frappe.session.user))


def permission_query(user=None, doctype=None):
    user = user or frappe.session.user
    scope = _scope(user)
    meta = frappe.get_meta(doctype)
    clauses = []
    if scope["organizations"]:
        column = "name" if doctype == "UA Organization" else "organization" if meta.has_field("organization") else None
        if column:
            values = ", ".join(frappe.db.escape(value) for value in scope["organizations"])
            clauses.append(f"`tab{doctype}`.`{column}` in ({values})")
    if scope["warehouses"]:
        column = "name" if doctype == "UA Warehouse" else "warehouse" if meta.has_field("warehouse") else None
        if column:
            values = ", ".join(frappe.db.escape(value) for value in scope["warehouses"])
            clauses.append(f"`tab{doctype}`.`{column}` in ({values})")
        values = ", ".join(frappe.db.escape(value) for value in scope["warehouses"])
        for field in TRANSFER_FIELDS:
            if meta.has_field(field):
                clauses.append(f"`tab{doctype}`.`{field}` in ({values})")
        for table in meta.get_table_fields():
            if frappe.get_meta(table.options).has_field("warehouse"):
                clauses.append(
                    f"not exists (select 1 from `tab{table.options}` child where child.parent = `tab{doctype}`.name "
                    f"and child.parenttype = {frappe.db.escape(doctype)} and child.parentfield = {frappe.db.escape(table.fieldname)} "
                    f"and ifnull(child.warehouse, '') != '' and child.warehouse not in ({values}))"
                )
    return " and ".join(clauses)


QUERY_DOCTYPES = (
    "UA Organization", "UA Warehouse", "UA Bank Account", "UA Cash Desk", "UA Counterparty Contract",
    "UA Fixed Asset", "UA Intangible Asset", "UA Low Value Asset", "UA Accounting Policy",
    "UA Numbering Setting", "UA Change Log", "UA Cash Receipt", "UA Cash Payment",
    "UA Sales Invoice", "UA Purchase Receipt", "UA Customer Order", "UA Supplier Order",
    "UA Payment Invoice", "UA Supplier Invoice", "UA Sales Return", "UA Purchase Return", "UA Service Act",
    "UA Service Receipt", "UA Debt Adjustment", "UA Reconciliation Act", "UA Power of Attorney", "UA Customs Import",
    "UA Journal Operation", "UA Month Closing", "UA Accounting Entry", "UA Account Turnover",
    "UA VAT Liability Entry", "UA VAT Credit Entry",
    "UA Employee", "UA Hiring", "UA Staff Transfer", "UA Dismissal", "UA Timesheet", "UA Payroll", "UA Salary Payment",
    "UA Stock Transfer", "UA Stock Writeoff", "UA Stock Surplus", "UA Stock Inventory",
    "UA Stock Assembly", "UA Low Value Issue", "UA Requirement Invoice",
    "UA Retail Sales Report", "UA Retail Return", "UA Retail Revaluation", "UA Cash Collection",
    "UA Acquiring Settlement", "UA Cash Register", "UA Fiscal Receipt", "UA Z Report",
    "UA Commission Receipt", "UA Commission Transfer", "UA Commission Agent Report", "UA Principal Report",
    "UA Commission Return", "UA Tolling Transfer", "UA Tolling Receipt", "UA Tolling Intake", "UA Tolling Output",
    "UA Packaging Return",
    "UA Special Wear Issue", "UA Special Wear Monthly Writeoff", "UA Special Wear Return", "UA Special Wear Writeoff",
    "UA Production Report", "UA Production Month Closing", "UA Own Work Act", "UA Planned Price",
    "UA Tax Ledger Entry", "UA Tax Difference Item", "UA Regulated Report",
    "UA Statistical Report", "UA Signed Document", "UA E-Reporting Setting", "UA Exchange Log",
    "UA Payment Order", "UA Tax Payment Account", "UA Accountant Task",
)


for _doctype in QUERY_DOCTYPES:
    _name = "query_" + _doctype.lower().replace(" ", "_")
    def _query(user=None, doctype=_doctype):
        return permission_query(user, doctype)
    _query.__name__ = _name
    globals()[_name] = _query


@frappe.whitelist()
def get_user_scope():
    return _scope(frappe.session.user)


def check_access(doc, method=None):
    if not doc.doctype.startswith("UA ") or not _permitted(doc, _scope(frappe.session.user)):
        if doc.doctype.startswith("UA "):
            frappe.throw("Немає доступу до організації або складу", frappe.PermissionError)
        return
    if doc.doctype == "UA Organization" and not doc.is_new():
        old = doc.get_doc_before_save()
        if old and str(old.edit_lock_date or "") != str(doc.edit_lock_date or ""):
            roles = set(frappe.get_roles())
            if not roles.intersection({"UA Accounting Manager", "UA Chief Accountant", "System Manager"}):
                frappe.throw("Немає прав змінювати дату заборони", frappe.PermissionError)
    check_period(doc)


def check_period(doc, method=None):
    if doc.meta.module != "UA Documents" or frappe.flags.get("ua_month_closing"):
        return
    # the settings DocType can be absent (fresh site): no bypass roles then, the lock still applies
    allowed = set()
    if frappe.db.exists("DocType", "UA Accounting Settings"):
        allowed = {r.role for r in frappe.get_single("UA Accounting Settings").get("lock_allowed_roles") or []}
    assigned = set(frappe.get_all("Has Role", filters={"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))
    if allowed.intersection(assigned):
        return
    pairs = [(doc.get("organization"), doc.get("posting_date"))]
    if not doc.is_new():
        fields = [f for f in ("organization", "posting_date") if doc.meta.has_field(f)]
        old = frappe.db.get_value(doc.doctype, doc.name, fields, as_dict=True) if fields else None
        if old:
            pairs.append((old.get("organization"), old.get("posting_date")))
    for organization, posting_date in pairs:
        if not organization or not posting_date:
            continue
        locked = frappe.db.get_value("UA Organization", organization, "edit_lock_date")
        if locked and getdate(posting_date) <= getdate(locked):
            frappe.throw(f"Період закрито: дата заборони редагування {getdate(locked).strftime('%d.%m.%Y')}")


def set_status(doctype, name, status):
    """Change the status of a submitted order with the period lock and the change log."""
    old = frappe.db.get_value(doctype, name, "status")
    if old == status:
        return
    doc = frappe.get_doc(doctype, name)
    check_period(doc)
    frappe.db.set_value(doctype, name, "status", status, update_modified=False)
    from ua_accounting import audit

    audit.record_change(doc, [{"field": "status", "old_value": str(old or ""), "new_value": status}])


def report_scope(organization, warehouse=None):
    """Check the organization and warehouse of a report for the current user.

    Returns the warehouses the report is limited to (None = no limit).
    """
    scope = _scope(frappe.session.user)
    if scope["organizations"] and organization not in scope["organizations"]:
        frappe.throw("Немає доступу до організації або складу", frappe.PermissionError)
    allowed = scope["warehouses"]
    if allowed and warehouse and warehouse not in allowed:
        frappe.throw("Немає доступу до організації або складу", frappe.PermissionError)
    return None if warehouse else allowed
