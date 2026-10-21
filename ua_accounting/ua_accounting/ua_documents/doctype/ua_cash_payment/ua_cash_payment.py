import frappe
from frappe import _

from ua_accounting.accounting.cash import CashDocument
from ua_accounting.accounting.documents import EVENT_PAYMENT, TAX_VAT

OP_SUPPLIER = "Оплата постачальнику"
ST_ADVANCE = "Передоплата (аванс)"


class UACashPayment(CashDocument):
    """Витрата коштів.

    Payment to supplier: Dt 631 Ct 311/301 (or Dt 371 for an advance).
    VAT credit of an advance: Dt 641 Ct 644 (first event is the payment).
    Other: Dt <account of the document> Ct 311/301.
    """

    doc_code = "CP"
    doc_title = "Витрата коштів"

    def is_settlement(self):
        return self.operation_type == OP_SUPPLIER

    def is_advance(self):
        return self.settlement_type == ST_ADVANCE

    def validate(self):
        super().validate()
        if self.purchase_receipt and self.is_settlement() and not self.is_advance():
            row = frappe.db.get_value(
                "UA Purchase Receipt", self.purchase_receipt, ["counterparty", "docstatus"], as_dict=True
            )
            if row.docstatus != 1 or row.counterparty != self.counterparty:
                frappe.throw(_("Надходження {0} не підходить до цієї оплати").format(self.purchase_receipt))

    def build(self):
        amount = self.amount_uah
        entries, credits = [], []
        if not self.is_settlement():
            entries.append(
                self.entry(
                    self.other_account,
                    self.cash_account,
                    amount,
                    self.other_sub,
                    self.cash_sub,
                    cur_amount=self.amount,
                )
            )
            return entries, [], []

        sub = dict(self.settle_sub)
        if self.is_advance():
            debit = "371"
        else:
            debit = "632" if self.is_foreign else "631"
            if self.purchase_receipt:
                sub["SettlementDoc"] = ("UA Purchase Receipt", self.purchase_receipt)
        entries.append(self.entry(debit, self.cash_account, amount, sub, self.cash_sub, cur_amount=self.amount))

        if self.is_advance() and self.vat_uah and self.tax_invoice_received:
            entries.append(self.entry("641", "644", self.vat_uah, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT}))
            credits.append(self.vat_row(self.vat_rate, amount - self.vat_uah, self.vat_uah, EVENT_PAYMENT))
        return entries, [], credits
