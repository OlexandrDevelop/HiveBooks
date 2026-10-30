import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class UAProvisionSettings(Document):
    def validate(self):
        if not 0 <= flt(self.doubtful_coefficient) <= 100:
            frappe.throw(_("Коефіцієнт сумнівності має бути від 0 до 100 %"))
        if not 0 <= flt(self.esv_rate) <= 100:
            frappe.throw(_("Ставка ЄСВ має бути від 0 до 100 %"))
        for row in self.classes:
            if row.days_to and row.days_to < (row.days_from or 0):
                frappe.throw(_("Рядок {0}: кінець діапазону менший за початок").format(row.idx))
