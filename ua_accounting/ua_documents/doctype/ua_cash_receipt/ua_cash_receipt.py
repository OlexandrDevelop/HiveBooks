import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import simplified_tax
from ua_accounting.accounting.cash import CashDocument
from ua_accounting.accounting.bank_cash import check_cash_balance
from ua_accounting.accounting.documents import EVENT_PAYMENT, TAX_VAT, settlement_balance, vat_info

OP_BUYER = "Оплата від покупця"
ST_ADVANCE = "Передоплата (аванс)"


class UACashReceipt(CashDocument):
    """Надходження коштів.

    Payment from buyer: Dt 311/301 Ct 361 (or Ct 681 for an advance).
    Payment above the debt: the rest goes to Ct 681.
    VAT of an advance: Dt 643 Ct 641 (first event is the payment).
    Other: Dt 311/301 Ct <account of the document>.
    """

    doc_code = "CR"
    doc_title = "Надходження коштів"

    def is_settlement(self):
        return self.operation_type == OP_BUYER

    def is_advance(self):
        return self.settlement_type == ST_ADVANCE

    def on_submit(self):
        if self.cash_type == "Каса" and not self.is_foreign:
            check_cash_balance(self.organization, self.cash_desk, self.posting_date, self.amount_uah)
        super().on_submit()
        simplified_tax.post_income(self)

    def before_cancel(self):
        super().before_cancel()
        if self.cash_type == "Каса" and not self.is_foreign:
            check_cash_balance(self.organization, self.cash_desk, self.posting_date, -self.amount_uah, check_limit=False)

    def on_cancel(self):
        super().on_cancel()
        simplified_tax.cancel_income(self)

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
            account = {
                "Повернення від постачальника": "631",
                "Отримання від підзвітної особи": "372",
            }.get(self.operation_type, self.other_account)
            entries.append(
                self.entry(
                    self.cash_account,
                    account,
                    amount,
                    self.cash_sub,
                    self.other_sub,
                    cur_amount=self.amount,
                )
            )
            return entries, [], []

        sub = dict(self.settle_sub)
        advance_part, advance_vat = amount, self.vat_uah
        if self.is_advance():
            entries.append(self.entry(self.cash_account, "681", amount, self.cash_sub, sub, cur_amount=self.amount))
        else:
            credit = "362" if self.is_foreign else "361"
            if self.sales_invoice:
                sub["SettlementDoc"] = ("UA Sales Invoice", self.sales_invoice)
            debt = max(settlement_balance(self.organization, credit, self.counterparty, self.contract, "dr", self.posting_date, self._ctx), 0)
            # the part above the debt is an advance
            # (only when there is a debt: a payment with no debt at all stays on the buyer account)
            advance_part = max(flt(amount - debt, 2), 0) if debt > 0 else 0.0
            advance_vat = self.vat_of(advance_part)
            paid = flt(amount - advance_part, 2)
            if paid:
                entries.append(
                    self.entry(self.cash_account, credit, paid, self.cash_sub, sub, cur_amount=flt(paid / self.exchange_rate, 2))
                )
            if advance_part:
                entries.append(
                    self.entry(
                        self.cash_account,
                        "681",
                        advance_part,
                        self.cash_sub,
                        self.settle_sub,
                        cur_amount=flt(advance_part / self.exchange_rate, 2),
                    )
                )

        if advance_part and advance_vat:
            entries.append(self.entry("643", "641", advance_vat, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT}))
            liabilities.append(self.vat_row(self.vat_rate, advance_part - advance_vat, advance_vat, EVENT_PAYMENT))
        return entries, liabilities, []

    def vat_of(self, gross):
        """VAT inside `gross` (UAH) by the rate of the document."""
        if not (gross and self.vat_rate):
            return 0.0
        percent, taxable = vat_info(self.vat_rate, {})
        return flt(gross * percent / (100 + percent), 2) if taxable and percent else 0.0
