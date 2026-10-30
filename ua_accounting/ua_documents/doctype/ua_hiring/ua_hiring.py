import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.hr import HRDocument
from ua_accounting.accounting.payroll import STATUS_FIRED, STATUS_WORKS


class UAHiring(HRDocument):
    """Прийом на роботу: fills the card of the employee. No entries."""

    doc_code = "HR"
    doc_title = "Прийом на роботу"

    def validate(self):
        super().validate()
        if flt(self.salary) <= 0:
            frappe.throw(_("Оклад має бути більше нуля"))
        card = self.employee_card
        if card.hire_date and card.status != STATUS_FIRED:
            frappe.throw(_("Співробітник уже працює з {0}").format(card.hire_date))

    def on_submit(self):
        self.change_card(
            {
                "hire_date": self.start_date,
                "position": self.position,
                "department": self.department,
                "salary": self.salary,
                "work_schedule": self.work_schedule,
                "status": STATUS_WORKS,
                "dismissal_date": None,
            }
        )

    def on_cancel(self):
        self.restore_card()
