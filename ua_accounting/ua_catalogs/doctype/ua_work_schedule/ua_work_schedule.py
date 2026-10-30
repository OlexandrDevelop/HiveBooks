import frappe
from frappe import _
from frappe.model.document import Document


class UAWorkSchedule(Document):
    def validate(self):
        if not 1 <= int(self.days_per_week or 0) <= 7:
            frappe.throw(_("Робочих днів на тиждень має бути від 1 до 7"))
        if not 0 < (self.hours_per_day or 0) <= 24:
            frappe.throw(_("Годин на день має бути від 0 до 24"))
