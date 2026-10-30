import frappe
from frappe.model.document import Document


class UAChangeLog(Document):
    def before_insert(self):
        if not getattr(frappe.flags, "ua_audit_write", False):
            frappe.throw("Журнал змін заповнюється системою")

    def validate(self):
        if not self.is_new():
            frappe.throw("Журнал змін не можна редагувати")

    def on_trash(self):
        frappe.throw("Журнал змін не можна видаляти")
