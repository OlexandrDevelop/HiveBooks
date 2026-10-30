import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from ua_accounting.accounting.accountant_tasks import AUTO, DONE, MANUAL, effective_status


class UAAccountantTask(Document):
    """Завдання бухгалтера: податок або звіт зі строком."""

    def validate(self):
        if not self.source:
            self.source = AUTO if self.rule_code else MANUAL
        if cint(self.remind_days) < 0:
            frappe.throw(_("Кількість днів для нагадування не може бути від'ємною"))
        if self.status != DONE:
            self.done_on = None
        self.status = effective_status(self.status, self.due_date, frappe.utils.nowdate())
