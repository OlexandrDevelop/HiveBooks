from frappe.utils import flt

from ua_accounting.accounting import provisions as prov
from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    EXPENSE_ACCOUNT,
    TAX_VAT,
    VAT_NONE,
    TradeDocument,
)

VAT_ACCOUNT = "641"
VAT_CREDIT_ACCOUNT = "644"


class UAServiceReceipt(TradeDocument):
    """Отримання послуг сторонніх організацій.

    Dt 92 (93, 23...) Ct 631   services without VAT
    Dt 644 Ct 631              VAT in the debt to the supplier
    Dt 641 Ct 644              VAT credit, if the tax invoice is received
    """

    doc_code = "SRC"
    doc_title = "Отримання послуг"

    def build(self):
        settle = "632" if self.is_foreign else "631"
        entries, credits = [], []
        groups = {}
        warranty_used = 0.0
        for row, _kind in self.lines():
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            amount = gross if self.vat_mode == VAT_NONE else net
            cur_amount = row.total if self.vat_mode == VAT_NONE else row.total - row.vat_amount
            sub = {"ExpenseItem": row.expense_item, "Department": row.department, "Item": row.item}
            account = row.account or EXPENSE_ACCOUNT
            if row.get("warranty_repair"):
                # warranty repair is paid from the provision 473 first, the excess goes to expense (93)
                account = row.account or prov.SALES_EXPENSE_ACCOUNT
                available = max(0.0, prov.credit_balance(self.organization, prov.WARRANTY_ACCOUNT, self.posting_date))
                used = flt(min(amount, available - warranty_used), 2)
                warranty_used = flt(warranty_used + used, 2)
                if used > 0:
                    used_cur = flt(cur_amount * used / amount, 2)
                    entries.append(
                        self.entry(prov.WARRANTY_ACCOUNT, settle, used, {}, self.settle_sub, cur_amount=used_cur)
                    )
                    amount, cur_amount = flt(amount - used, 2), flt(cur_amount - used_cur, 2)
            entries.append(self.entry(account, settle, amount, sub, self.settle_sub, cur_amount=cur_amount))
        vat_total = flt(sum(g["vat"] for g in groups.values()), 2)
        if vat_total:
            entries.append(
                self.entry(
                    VAT_CREDIT_ACCOUNT, settle, vat_total, {"TaxType": TAX_VAT}, self.settle_sub,
                    cur_amount=flt(vat_total / self.exchange_rate, 2),
                )
            )
            if self.tax_invoice_received and self.vat_mode != VAT_NONE:
                entries.append(
                    self.entry(VAT_ACCOUNT, VAT_CREDIT_ACCOUNT, vat_total, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT})
                )
        if self.tax_invoice_received and self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                if g["taxable"] and g["vat"] > 0:
                    credits.append(self.vat_row(key, g["net"], g["vat"], EVENT_SHIPMENT))
        return entries, [], credits
