import frappe
from frappe.model.document import Document


class UANumberingSetting(Document):
    def validate(self):
        if self.digits < 1 or self.digits > 12:
            frappe.throw("Кількість цифр має бути від 1 до 12")
        if frappe.db.exists(self.doctype, {
            "organization": self.organization, "ref_doctype": self.ref_doctype,
            "name": ("!=", self.name or ""),
        }):
            frappe.throw("Налаштування нумерації вже існує")
