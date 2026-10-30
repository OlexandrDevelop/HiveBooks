import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_last_day

from ua_accounting.accounting import month_closing
from ua_accounting.accounting.utils import first_of_month


class UAMonthClosing(Document):
    """Закриття місяця: the list of routine operations of one organization and month.

    The operations are run by ua_accounting.api.month_closing (accounting/month_closing.py).
    """

    def validate(self):
        if not self.is_new():
            old = self.get_doc_before_save()
            if old and (old.organization != self.organization or str(first_of_month(self.period)) != str(old.period)):
                frappe.throw(_("Організацію та місяць закриття змінювати не можна"))
        self.period = first_of_month(self.period)
        # the unique key makes the one-closing-per-month rule hold under concurrent inserts
        self.closing_key = f"{self.organization}|{self.period}"
        self.period_end = get_last_day(self.period)
        if frappe.db.exists(
            "UA Month Closing",
            {"organization": self.organization, "period": self.period, "name": ("!=", self.name)},
        ):
            frappe.throw(_("Закриття цього місяця вже існує"), frappe.DuplicateEntryError)
        if self.is_new():
            self.status = month_closing.TODO
            self.set("steps", [])
            for step in month_closing.new_steps():
                self.append("steps", step)

    def on_trash(self):
        if any(row.status == month_closing.DONE for row in self.steps):
            frappe.throw(_("Спочатку скасуйте виконані операції закриття місяця"))
