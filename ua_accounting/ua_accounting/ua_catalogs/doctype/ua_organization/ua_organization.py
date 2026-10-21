import re

from frappe.model.document import Document


class UAOrganization(Document):
    def validate(self):
        # the prefix is a part of document numbers: letters and digits only
        self.doc_prefix = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]", "", self.doc_prefix or "").upper()
