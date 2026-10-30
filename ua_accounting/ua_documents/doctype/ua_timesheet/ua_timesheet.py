import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.payroll import employee_info, month_bounds, working_days


class UATimesheet(AccountingDocument):
    """Табель: worked days of the employees in a month. The salary is paid for these days. No entries."""

    doc_code = "TS"
    doc_title = "Табель"
    posts = False

    def autoname(self):
        self.posting_date = self.month_start
        super().autoname()

    def validate(self):
        super().validate()
        self.month_start = get_first_day(getdate(self.month_start))
        self.posting_date = self.month_start
        first, last = month_bounds(self.month_start)
        seen = set()
        for row in self.rows:
            if row.employee in seen:
                frappe.throw(_("Рядок {0}: співробітник уже є в табелі").format(row.idx))
            seen.add(row.employee)
            emp = employee_info(row.employee)
            if emp.organization != self.organization:
                frappe.throw(_("Рядок {0}: співробітник працює в іншій організації").format(row.idx))
            norm = working_days(emp.days_per_week, first, last)
            if flt(row.worked_days) < 0:
                frappe.throw(_("Рядок {0}: відпрацьовані дні не можуть бути від'ємними").format(row.idx))
            if flt(row.worked_days) > norm:
                frappe.throw(_("Рядок {0}: відпрацьовано {1} дн., а норма місяця {2}").format(row.idx, row.worked_days, norm))
        other = frappe.db.sql(
            """select t.name from `tabUA Timesheet Row` r join `tabUA Timesheet` t
            on t.name = r.parent and r.parenttype = 'UA Timesheet'
            where t.docstatus = 1 and t.organization = %s and t.month_start = %s and t.name != %s
            and r.employee in %s limit 1""",
            (self.organization, self.month_start, self.name or "", tuple(seen) or ("",)),
        )
        if other:
            frappe.throw(_("За цей місяць уже є табель {0} з тими самими співробітниками").format(other[0][0]))
