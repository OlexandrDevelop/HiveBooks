"""Read-only data for the desk screens (T-433).

get_doc_side(doctype, name) -> the side card of a document form:
    settlement: balance with the counterparty before the document and after posting
    related:    documents this one is based on, and documents made from it
Every read checks the user's permissions.
"""

import frappe
from frappe.utils import flt

DOCUMENTS = (
    "UA Sales Invoice",
    "UA Purchase Receipt",
    "UA Customer Order",
    "UA Supplier Order",
    "UA Cash Receipt",
    "UA Cash Payment",
    "UA Journal Operation",
)

# effect of a posted document on "the counterparty owes us" (debit side of the settlement)
SIGN = {
    "UA Sales Invoice": ("total_amount", 1),
    "UA Purchase Receipt": ("total_amount", -1),
    "UA Cash Receipt": ("amount", -1),
    "UA Cash Payment": ("amount", 1),
}


def _counterparty_balance(organization, counterparty, until, exclude=None):
    """Debit minus credit of all entries with the counterparty as a subconto, up to the day."""
    params = {"cp": counterparty, "until": until, "org": organization, "ex": exclude or ""}
    side = lambda s: " OR ".join(
        f"(subconto_{s}{i}_type = 'UA Counterparty' AND subconto_{s}{i} = %(cp)s)" for i in (1, 2, 3)
    )
    row = frappe.db.sql(
        f"""SELECT
            COALESCE(SUM(CASE WHEN {side("dr")} THEN amount ELSE 0 END), 0) AS dr,
            COALESCE(SUM(CASE WHEN {side("cr")} THEN amount ELSE 0 END), 0) AS cr
        FROM `tabUA Accounting Entry`
        WHERE posting_date <= %(until)s AND organization = %(org)s AND registrar != %(ex)s
            AND (({side("dr")}) OR ({side("cr")}))""",
        params,
        as_dict=True,
    )[0]
    return flt(flt(row.dr) - flt(row.cr), 2)


def _settlement(doc):
    cp = doc.get("counterparty")
    if not cp or not doc.get("organization") or not doc.get("posting_date"):
        return None
    if not frappe.has_permission("UA Accounting Entry", "read"):
        return None
    before = _counterparty_balance(doc.organization, cp, doc.posting_date, exclude=doc.name)
    out = {"before": before, "after": None}
    if doc.doctype in SIGN and doc.docstatus < 2:
        field, sign = SIGN[doc.doctype]
        out["after"] = flt(before + sign * flt(doc.get("base_total") or doc.get(field)), 2)
    return out


def _related(doc):
    found = []
    meta = frappe.get_meta(doc.doctype)
    # documents this one is based on (its link fields to other documents)
    for df in meta.fields:
        if df.fieldtype == "Link" and df.options in DOCUMENTS and doc.get(df.fieldname):
            if frappe.has_permission(df.options, "read", doc=doc.get(df.fieldname)):
                found.append({"doctype": df.options, "name": doc.get(df.fieldname), "role": "basis"})
    # documents made from this one (their link fields point here)
    for doctype in DOCUMENTS:
        if not frappe.has_permission(doctype, "read"):
            continue
        for df in frappe.get_meta(doctype).fields:
            if df.fieldtype != "Link" or df.options != doc.doctype or df.fieldname == "amended_from":
                continue
            for r in frappe.get_list(
                doctype, filters={df.fieldname: doc.name, "docstatus": ("<", 2)}, fields=["name"], limit=5
            ):
                found.append({"doctype": doctype, "name": r.name, "role": "derived"})
    for r in found:
        d = frappe.db.get_value(r["doctype"], r["name"], ["posting_date", "docstatus"], as_dict=True) or {}
        r["posting_date"] = str(d.get("posting_date") or "")
        r["docstatus"] = d.get("docstatus")
    return found


@frappe.whitelist()
def get_doc_side(doctype, name):
    if doctype not in DOCUMENTS and frappe.db.get_value("DocType", doctype, "module") != "UA Documents" \
            and doctype != "UA Single Tax Declaration":
        frappe.throw(frappe._("Невідомий документ"))
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    if doctype not in DOCUMENTS:
        # tax invoices, reports and declarations have no settlement with a counterparty: the card stays empty
        return {"settlement": None, "related": [], "modified": str(doc.modified)}
    return {"settlement": _settlement(doc), "related": _related(doc), "modified": str(doc.modified)}


MARK_FIELD = "marked_for_deletion"


def _markable(doctype):
    """Documents and catalogs of the app; they get the mark field in seed."""
    return doctype in DOCUMENTS or frappe.db.get_value("DocType", doctype, "module") == "UA Catalogs"


@frappe.whitelist()
def mark_for_deletion(doctype, names, mark=1):
    """1C style mark: set or clear the flag. Nothing is deleted; posted documents are refused."""
    if not _markable(doctype) or not frappe.get_meta(doctype).has_field(MARK_FIELD):
        frappe.throw(frappe._("Для цього об’єкта мітка недоступна"))
    names = frappe.parse_json(names)
    mark = 1 if frappe.utils.cint(mark) else 0
    changed = 0
    for name in names:
        doc = frappe.get_doc(doctype, name)
        doc.check_permission("write")
        if doc.get("docstatus") == 1:
            frappe.throw(frappe._("Проведений документ {0} не можна позначити. Спочатку скасуйте проведення.").format(name))
        doc.db_set(MARK_FIELD, mark)
        changed += 1
    return changed
