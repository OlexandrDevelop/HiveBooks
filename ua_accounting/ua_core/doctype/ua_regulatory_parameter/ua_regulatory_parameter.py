import frappe
from frappe import _
from frappe.model.document import Document


class UARegulatoryParameter(Document):
    """Dated legal parameter (minimum wage, rates, limits). Read through accounting.simplified_tax.parameter."""

    def validate(self):
        if (self.value or 0) < 0:
            frappe.throw(_("Значення не може бути від'ємним"))
        if frappe.db.exists(self.doctype, {"parameter_code": self.parameter_code,
                                           "effective_from": self.effective_from,
                                           "name": ("!=", self.name or "")}):
            frappe.throw(_("Параметр {0} на цю дату вже існує").format(self.parameter_code))
