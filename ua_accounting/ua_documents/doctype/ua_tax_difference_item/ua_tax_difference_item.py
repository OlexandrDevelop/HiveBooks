import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from ua_accounting.accounting import tax_ledger


class UATaxDifferenceItem(Document):
    """Ручна стаття податкової різниці (без джерела в регістрі)."""

    def validate(self):
        for field in ("book_amount", "tax_amount"):
            if flt(self.get(field)) < 0:
                frappe.throw(_("Суми не можуть бути від'ємними"))
        self.article = tax_ledger.ARTICLE[self.kind]
