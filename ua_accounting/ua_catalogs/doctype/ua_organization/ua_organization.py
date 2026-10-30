import re

import frappe
from frappe import _
from frappe.model.document import Document


class UAOrganization(Document):
    def validate(self):
        # the prefix is a part of document numbers: letters and digits only
        self.doc_prefix = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]", "", self.doc_prefix or "").upper()
        if self.edrpou and not (self.edrpou.isdigit() and len(self.edrpou) in (8, 10)):
            frappe.throw(_("ЄДРПОУ має містити 8 або 10 цифр"))
