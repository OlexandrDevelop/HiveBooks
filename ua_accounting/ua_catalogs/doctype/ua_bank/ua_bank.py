import frappe
from frappe import _
from frappe.model.document import Document


class UABank(Document):
    def validate(self):
        if self.mfo and not (self.mfo.isdigit() and len(self.mfo) == 6):
            frappe.throw(_("МФО має містити 6 цифр"))
