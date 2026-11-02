import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import simplified_tax
from ua_accounting.accounting.cash import CashDocument
from ua_accounting.accounting.bank_cash import check_cash_balance
from ua_accounting.accounting import invoice as invoices
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
        self.refresh_invoices()

    def before_cancel(self):
        super().before_cancel()
        if self.cash_type == "Каса" and not self.is_foreign:
            check_cash_balance(self.organization, self.cash_desk, self.posting_date, -self.amount_uah, check_limit=False)

    def on_cancel(self):
        super().on_cancel()
        simplified_tax.cancel_income(self)
        self.refresh_invoices()

    def refresh_invoices(self):
        invoices.refresh_many(row.invoice for row in self.get("allocations") or [])

    def validate(self):
        super().validate()
        if self.sales_invoice and not self.is_advance() and self.is_settlement():
            sale = frappe.db.get_value("UA Sales Invoice", self.sales_invoice, ["counterparty", "docstatus"], as_dict=True)
            if sale.docstatus != 1 or sale.counterparty != self.counterparty:
                frappe.throw(_("Реалізація {0} не підходить до цієї оплати").format(self.sales_invoice))
        if self.sales_invoice and not self.get("allocations") and frappe.db.get_value(
            "UA Sales Invoice", self.sales_invoice, "invoice"
        ):
            frappe.throw(_("Оплату реалізації за інвойсом розподіляють за інвойсом: заповніть таблицю «Інвойси»"))
        self.check_allocations()

    def check_allocations(self):
        rows = self.get("allocations") or []
        if not rows:
            return
        if not self.is_settlement():
            frappe.throw(_("Розподіл за інвойсами є лише в оплаті від покупця"))
        if self.sales_invoice:
            frappe.throw(_("Оплату розподіляють або за реалізацією, або за інвойсами"))
        total = 0.0
        for row in rows:
            inv = frappe.db.get_value(
                invoices.INVOICE, row.invoice, ["docstatus", "counterparty", "contract", "currency"], as_dict=True
            )
            if not inv or inv.docstatus != 1:
                frappe.throw(_("Рядок {0}: інвойс {1} не підтверджений").format(row.idx, row.invoice))
            if (inv.counterparty, inv.contract) != (self.counterparty, self.contract) or inv.currency != self.currency:
                frappe.throw(_("Рядок {0}: інвойс {1} має інших контрагента, договір або валюту").format(row.idx, row.invoice))
            if flt(row.amount) <= 0:
                frappe.throw(_("Рядок {0}: сума має бути більше нуля").format(row.idx))
            total += flt(row.amount)
        if flt(total, 2) > flt(self.amount, 2):
            frappe.throw(_("Сума розподілу {0} перевищує суму оплати {1}").format(flt(total, 2), flt(self.amount, 2)))

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

        if self.get("allocations"):
            alloc_entries, alloc_liabilities, allocated = self.allocation_postings()
            entries.extend(alloc_entries)
            liabilities.extend(alloc_liabilities)
            amount = flt(amount - allocated, 2)
            if amount <= 0:
                return entries, liabilities, []

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

    def allocation_postings(self):
        """Payment allocated to Invoices: the debt of the Invoice is paid first, the rest is its advance.

        Both parts carry the Invoice as the settlement document; the advance part has the VAT liability
        of the first event (the payment). Returns (entries, VAT rows, allocated amount in UAH).
        """
        entries, liabilities, allocated = [], [], 0.0
        credit = "362" if self.is_foreign else "361"
        rate = flt(self.exchange_rate) or 1
        for row in self.allocations:
            part = flt(flt(row.amount) * rate, 2)
            sub = {
                "Counterparty": self.counterparty,
                "Contract": self.contract,
                "SettlementDoc": (invoices.INVOICE, row.invoice),
            }
            debt = 0.0
            if not self.is_advance():
                debt = max(invoices.settlement_debt(credit, row.invoice, self.posting_date, self._ctx), 0)
            paid = min(part, debt)
            advance = flt(part - paid, 2)
            if paid:
                entries.append(
                    self.entry(self.cash_account, credit, paid, self.cash_sub, sub, cur_amount=flt(paid / rate, 2))
                )
            if advance:
                entries.append(
                    self.entry(self.cash_account, "681", advance, self.cash_sub, sub, cur_amount=flt(advance / rate, 2))
                )
                vat = self.vat_of(advance)
                if vat:
                    entries.append(self.entry("643", "641", vat, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT}))
                    liabilities.append(self.vat_row(self.vat_rate, advance - vat, vat, EVENT_PAYMENT))
                row.db_set("vat_amount", flt(vat / rate, 2), update_modified=False)
            allocated += part
        return entries, liabilities, flt(allocated, 2)
