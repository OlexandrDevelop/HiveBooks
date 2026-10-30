import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class UACounterparty(NestedSet):
    nsm_parent_field = "parent_ua_counterparty"

    def validate(self):
        check_parent_is_group(self, "UA Counterparty")
        if (self.country or "Україна") == "Україна":
            check_edrpou(self.edrpou)


def check_parent_is_group(doc, doctype):
    """1C: only a folder can contain other records."""
    parent = doc.get(doc.nsm_parent_field)
    if parent and not frappe.db.get_value(doctype, parent, "is_group"):
        frappe.throw(_("«{0}» не є групою. Оберіть групу як батьківський елемент").format(parent))


def check_edrpou(value):
    if value and not (value.isdigit() and len(value) in (8, 10)):
        frappe.throw(_("ЄДРПОУ має містити 8 або 10 цифр"))
