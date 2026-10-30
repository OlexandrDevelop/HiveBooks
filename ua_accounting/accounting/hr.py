"""Base of the HR documents: hiring, transfer, dismissal. They change the card of the employee and post nothing."""

import json

import frappe
from frappe import _
from frappe.utils import getdate

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.payroll import STATUS_FIRED, STATUS_WORKS

CARD_FIELDS = (
    "position", "department", "salary", "work_schedule", "hire_date", "dismissal_date", "status",
)


class HRDocument(AccountingDocument):
    posts = False

    def validate(self):
        super().validate()
        self.employee_card = self.load_employee()

    def load_employee(self):
        card = frappe.db.get_value(
            "UA Employee", self.employee, ["organization", "status", "hire_date", "salary"], as_dict=True
        )
        if not card:
            frappe.throw(_("Співробітника {0} не знайдено").format(self.employee))
        if card.organization != self.organization:
            frappe.throw(_("Співробітник працює в іншій організації"))
        return card

    def check_after_hire(self, date, label):
        hired = self.employee_card.hire_date
        if hired and getdate(date) < getdate(hired):
            frappe.throw(_("{0} не може бути раніше за дату прийняття {1}").format(label, getdate(hired).strftime("%d.%m.%Y")))

    def before_cancel(self):
        super().before_cancel()
        for doctype in ("UA Hiring", "UA Staff Transfer", "UA Dismissal"):
            later = frappe.db.exists(
                doctype,
                {"employee": self.employee, "docstatus": 1, "creation": (">", self.creation), "name": ("!=", self.name)},
            )
            if later:
                frappe.throw(_("Спочатку скасуйте пізніший кадровий документ {0}").format(later))

    def change_card(self, values):
        """Remember the old values of the card and write the new ones."""
        card = frappe.get_doc("UA Employee", self.employee)
        before = {f: (str(card.get(f)) if card.get(f) is not None else None) for f in values}
        card.update(values)
        card.save(ignore_permissions=True)
        self.db_set("previous_state", json.dumps(before, ensure_ascii=False), update_modified=False)

    def restore_card(self, only_if=None):
        """Put the old values back. With `only_if` a field is restored only while it still has the new value."""
        before = json.loads(self.previous_state or "{}")
        if not before:
            return
        card = frappe.get_doc("UA Employee", self.employee)
        for field, old in before.items():
            if only_if and str(card.get(field)) != str(only_if.get(field)):
                continue
            card.set(field, old)
        card.save(ignore_permissions=True)


__all__ = ["HRDocument", "STATUS_FIRED", "STATUS_WORKS"]
