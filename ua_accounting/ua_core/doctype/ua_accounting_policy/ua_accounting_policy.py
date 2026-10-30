import frappe
from frappe.model.document import Document

from ua_accounting.accounting import simplified_tax


class UAAccountingPolicy(Document):
    def before_validate(self):
        # `effective_date` is a synonym of `effective_from`
        if not self.effective_from and self.effective_date:
            self.effective_from = self.effective_date
        self.effective_date = self.effective_from

    def validate(self):
        if frappe.db.exists(self.doctype, {
            "organization": self.organization, "effective_from": self.effective_from,
            "name": ("!=", self.name or ""),
        }):
            frappe.throw("Облікова політика на цю дату вже існує")
        simplified_tax.validate_policy(self)
