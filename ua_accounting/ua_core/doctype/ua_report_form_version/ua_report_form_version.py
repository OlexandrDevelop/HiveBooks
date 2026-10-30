import frappe
from frappe import _
from frappe.model.document import Document


class UAReportFormVersion(Document):
    """Version of a report form / XSD with the first reporting period it applies to."""

    def validate(self):
        if frappe.db.exists(self.doctype, {"form_code": self.form_code, "effective_from": self.effective_from,
                                           "name": ("!=", self.name or "")}):
            frappe.throw(_("Версія форми {0} на цю дату вже існує").format(self.form_code))
