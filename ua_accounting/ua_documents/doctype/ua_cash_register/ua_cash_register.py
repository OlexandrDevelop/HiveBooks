import frappe
from frappe import _
from frappe.model.document import Document

from ua_accounting.accounting.retail import is_retail


class UACashRegister(Document):
    """ПРРО: a cash register of a retail warehouse, connected to Checkbox or Вчасно.Каса."""

    def validate(self):
        if not is_retail(self.warehouse):
            frappe.throw(_("Склад ПРРО має бути роздрібним"))
        for doctype, field in (("UA Warehouse", "warehouse"), ("UA Cash Desk", "cash_desk"), ("UA Bank Account", "bank_account")):
            value = self.get(field)
            if value and frappe.db.get_value(doctype, value, "organization") != self.organization:
                frappe.throw(_("{0} належить іншій організації").format(self.meta.get_label(field)))
