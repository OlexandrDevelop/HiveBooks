import frappe
from frappe import _
from frappe.model.document import Document

from ua_accounting.accounting.bank_documents import valid_ua_iban


class UATaxPaymentAccount(Document):
    """Рахунок для сплати податку: куди платити і з яким КБК."""

    def validate(self):
        self.iban = (self.iban or "").replace(" ", "").upper()
        if not valid_ua_iban(self.iban):
            frappe.throw(_("IBAN {0} неправильний").format(self.iban))
        if frappe.db.exists(
            self.doctype,
            {"organization": self.organization, "tax_type": self.tax_type, "budget_code": self.budget_code, "name": ("!=", self.name)},
        ):
            frappe.throw(_("Такий рахунок для цього податку і КБК вже є"))
