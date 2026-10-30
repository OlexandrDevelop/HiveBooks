import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import make_doc_name


class UARegulatedReport(Document):
    """Регламентований звіт: lines are filled from the ledger (fill_report) and can be edited by hand."""

    doc_code = "RR"

    def autoname(self):
        self.name = make_doc_name(self, self.period_to)

    def validate(self):
        if getdate(self.period_to) < getdate(self.period_from):
            frappe.throw(_("Кінець періоду не може бути раніше початку"))
        self.status = self.status or "Чернетка"
        for row in self.lines:
            # a value typed in the form is a manual value
            if not row.manual and flt(row.value, 2) != flt(row.computed_value, 2):
                row.manual = 1
