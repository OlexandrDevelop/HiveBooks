import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class UAEmployee(Document):
    """Співробітник: a person with ІПН who works in an organization (or has a civil-law contract)."""

    def validate(self):
        person = frappe.db.get_value("UA Person", self.person, ["full_name", "ipn"], as_dict=True)
        if not person:
            frappe.throw(_("Фізичну особу {0} не знайдено").format(self.person))
        self.employee_name = person.full_name
        self.ipn = person.ipn
        if flt(self.salary) < 0:
            frappe.throw(_("Оклад не може бути від'ємним"))
        if flt(self.insured_years) < 0:
            frappe.throw(_("Страховий стаж не може бути від'ємним"))
        if self.hire_date and self.dismissal_date and getdate(self.dismissal_date) < getdate(self.hire_date):
            frappe.throw(_("Дата звільнення раніше за дату прийняття"))
