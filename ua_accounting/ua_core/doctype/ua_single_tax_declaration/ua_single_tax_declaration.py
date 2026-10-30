from ua_accounting.accounting import simplified_tax
from ua_accounting.accounting.documents import AccountingDocument


class UASingleTaxDeclaration(AccountingDocument):
    """Декларація платника єдиного податку. Filled by simplified_tax.fill_declaration."""

    doc_code = "ED"
    doc_title = "Декларація платника єдиного податку"

    def post_document(self):
        # only a legal entity posts: Дт 981 Кт 641. A ФОП has no entries.
        entries = self.build()[0]
        if entries:
            from ua_accounting.accounting import ledger

            ledger.post_entries(self, entries)

    def build(self):
        return simplified_tax.declaration_entries(self), [], []
