import re

import frappe
from frappe import _
from frappe.model.document import Document

IBAN_UA = re.compile(r"^UA\d{27}$")


class UABankAccount(Document):
    def validate(self):
        if bool(self.organization) == bool(self.counterparty):
            frappe.throw(_("Вкажіть або організацію, або контрагента (одне з двох)"))
        if self.iban:
            self.iban = self.iban.replace(" ", "").upper()
            if not IBAN_UA.match(self.iban):
                frappe.throw(_("IBAN має починатися з UA і містити 29 символів"))
