import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from ua_accounting.accounting.hr import HRDocument
from ua_accounting.accounting.payroll import STATUS_FIRED, salary_changes, salary_on


class UAStaffTransfer(HRDocument):
    """Кадрове переміщення: new position, department and salary from the transfer date. No entries."""

    doc_code = "TR"
    doc_title = "Кадрове переміщення"

    def validate(self):
        super().validate()
        if flt(self.new_salary) <= 0:
            frappe.throw(_("Новий оклад має бути більше нуля"))
        if self.employee_card.status == STATUS_FIRED:
            frappe.throw(_("Співробітник звільнений"))
        self.check_after_hire(self.transfer_date, _("Дата переведення"))

    def before_submit(self):
        # the salary before the transfer: the month is split by this date when the pay is calculated
        card = self.employee_card
        self.old_salary = float(salary_on(card.salary, salary_changes(self.employee), add_days(getdate(self.transfer_date), -1)))

    def on_submit(self):
        self.change_card(
            {"position": self.new_position, "department": self.new_department, "salary": self.new_salary}
        )

    def on_cancel(self):
        self.restore_card(only_if={"position": self.new_position, "department": self.new_department, "salary": self.new_salary})
