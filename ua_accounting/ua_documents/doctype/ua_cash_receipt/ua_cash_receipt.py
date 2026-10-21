import frappe
from frappe import _

from ua_accounting.accounting.cash import CashDocument
from ua_accounting.accounting.documents import EVENT_PAYMENT, TAX_VAT

OP_BUYER = "Оплата від покупця"
ST_ADVANCE = "Передоплата (аванс)"


class UACashReceipt(CashDocument):
    """Надходження коштів.

    Payment from buyer: Dt 311/301 Ct 361 (or Ct 681 for an advance).
    VAT of an advance: Dt 643 Ct 641 (first event is the payment).
    Other: Dt 311/301 Ct <account of the document>.
    """

    doc_code = "CR"
    doc_title = "Надходження коштів"

    def is_settlement(self):
        return self.operation_type == OP_BUYER

    def is_advance(self):
        return self.settlement_type == ST_ADVANCE

    def validate(self):
        super().validate()
        if self.sales_invoice and not self.is_advance() and self.is_settlement():
            sale = frappe.db.get_value("UA Sales Invoice", self.sales_invoice, ["counterparty", "docstatus"], as_dict=True)
            if sale.docstatus != 1 or sale.counterparty != self.counterparty:
                frappe.throw(_("Реалізація {0} не підходить до цієї оплати").format(self.sales_invoice))

    def build(self):
        amount = self.amount_uah
        entries, liabilities = [], []
        if not self.is_settlement():
            entries.append(
                self.entry(
                    self.cash_account,
                    self.other_account,
                    amount,
                    self.cash_sub,
                    self.other_sub,
                    cur_amount=self.amount,
                )
            )
            return entries, [], []

        sub = dict(self.settle_sub)
        if self.is_advance():
            credit = "681"
        else:
            credit = "362" if self.is_foreign else "361"
            if self.sales_invoice:
                sub["SettlementDoc"] = ("UA Sales Invoice", self.sales_invoice)
        entries.append(self.entry(self.cash_account, credit, amount, self.cash_sub, sub, cur_amount=self.amount))

        if self.is_advance() and self.vat_uah:
            entries.append(self.entry("643", "641", self.vat_uah, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT}))
            liabilities.append(
                self.vat_row(self.vat_rate, amount - self.vat_uah, self.vat_uah, EVENT_PAYMENT)
            )
        return entries, liabilities, []
