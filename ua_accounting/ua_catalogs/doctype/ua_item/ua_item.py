import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class UAItem(NestedSet):
    nsm_parent_field = "parent_ua_item"

    def validate(self):
        check_parent_is_group(self, "UA Item")
        if not 0 <= (self.warranty_percent or 0) <= 100:
            frappe.throw(_("Гарантійні витрати мають бути від 0 до 100 %"))
        if (self.warranty_months or 0) < 0:
            frappe.throw(_("Гарантійний строк не може бути від'ємним"))


def check_parent_is_group(doc, doctype):
    """1C: only a folder can contain other records."""
    parent = doc.get(doc.nsm_parent_field)
    if parent and not frappe.db.get_value(doctype, parent, "is_group"):
        frappe.throw(_("«{0}» не є групою. Оберіть групу як батьківський елемент").format(parent))
