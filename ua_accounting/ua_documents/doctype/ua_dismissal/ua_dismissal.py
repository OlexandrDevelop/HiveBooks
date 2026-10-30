import frappe
from frappe import _

from ua_accounting.accounting.hr import HRDocument
from ua_accounting.accounting.payroll import STATUS_FIRED, STATUS_WORKS


class UADismissal(HRDocument):
    """Звільнення: status «Звільнений» and the last working day. No entries."""

    doc_code = "DS"
    doc_title = "Звільнення"

    def validate(self):
        super().validate()
        if self.employee_card.status == STATUS_FIRED:
            frappe.throw(_("Співробітника вже звільнено"))
        self.check_after_hire(self.dismissal_date, _("Дата звільнення"))

    def on_submit(self):
        self.change_card({"status": STATUS_FIRED, "dismissal_date": self.dismissal_date})

    def on_cancel(self):
        self.restore_card()
