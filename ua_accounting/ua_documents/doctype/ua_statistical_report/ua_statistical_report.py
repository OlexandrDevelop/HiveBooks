import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from ua_accounting.accounting import statistics
from ua_accounting.accounting.documents import make_doc_name


class UAStatisticalReport(Document):
    """Статистична звітність (1-підприємництво, 1-ПВ): lines come from the ledger and can be edited by hand."""

    doc_code = "SR"

    def autoname(self):
        self.name = make_doc_name(self, self.period_to)

    def validate(self):
        if getdate(self.period_to) < getdate(self.period_from):
            frappe.throw(_("Кінець періоду не може бути раніше початку"))
        statistics.check_period(self)
        self.status = self.status or statistics.DRAFT
        for row in self.lines:
            # a value typed in the form is a manual value
            if not row.manual and flt(row.value, 2) != flt(row.computed_value, 2):
                row.manual = 1
