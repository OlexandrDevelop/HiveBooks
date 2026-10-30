import frappe
from frappe import _
from frappe.utils import getdate

from ua_accounting.accounting.documents import AccountingDocument


class UAPowerofAttorney(AccountingDocument):
    """Довіреність на отримання цінностей (форма М-2). Does not post."""

    doc_code = "POA"
    doc_title = "Довіреність"
    posts = False

    def validate(self):
        super().validate()
        if self.valid_until and getdate(self.valid_until) < getdate(self.posting_date):
            frappe.throw(_("Довіреність не може бути дійсною до дати, що раніша за дату видачі"))
