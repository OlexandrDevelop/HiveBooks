from frappe.model.document import Document


class UASubcontoType(Document):
    def validate(self):
        # The value types mirror the reference catalog; the ledger still reads reference_doctype.
        self.value_types = []
        if self.reference_doctype and not self.is_dynamic:
            self.append("value_types", {"value_type": self.reference_doctype})
