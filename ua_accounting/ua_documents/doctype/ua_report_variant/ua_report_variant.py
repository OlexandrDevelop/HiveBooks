import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class UAReportVariant(Document):
    """Варіант звіту: the saved settings of the universal report (ua_accounting.reporting.builder).

    A personal variant is seen by its owner only; a shared one is read by all, changed by the owner.
    """

    def validate(self):
        self.variant_name = (self.variant_name or "").strip()
        if not self.variant_name:
            frappe.throw(_("Вкажіть назву варіанту"))
        self.is_shared = cint(self.is_shared)
        self.is_default = cint(self.is_default)


def _manager(user):
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def has_permission(doc, ptype=None, user=None, debug=False):
    user = user or frappe.session.user
    if ptype == "create" or doc.owner == user or _manager(user):
        return True
    return ptype in ("read", "select") and bool(cint(doc.is_shared))


def permission_query(user=None, doctype=None):
    user = user or frappe.session.user
    if _manager(user):
        return ""
    return f"(`tabUA Report Variant`.`owner` = {frappe.db.escape(user)} or `tabUA Report Variant`.`is_shared` = 1)"
