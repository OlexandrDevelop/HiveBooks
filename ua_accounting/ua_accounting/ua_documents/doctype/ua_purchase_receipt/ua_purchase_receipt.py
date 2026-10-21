import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    EXPENSE_ACCOUNT,
    STOCK_ACCOUNT,
    TAX_VAT,
    VAT_NONE,
    TradeDocument,
    allocate_advance,
    new_from_basis,
    settlement_balance,
)

ADVANCE_ACCOUNT = "371"
VAT_ACCOUNT = "641"
VAT_CREDIT_ACCOUNT = "644"


class UAPurchaseReceipt(TradeDocument):
    """Надходження товарів та послуг.

    Dt 281 (201, 26, 92) Ct 631   goods and services without VAT
    Dt 644 Ct 631                 VAT in the debt to the supplier
    Dt 641 Ct 644                 VAT credit, if the tax invoice is received
    Dt 631 Ct 371                 offset of the prepayment
    The VAT of the prepayment was credited when it was paid (first event rule).
    """

    doc_code = "PR"
    doc_title = "Надходження товарів та послуг"

    def validate(self):
        super().validate()
        if self.supplier_order and frappe.db.get_value("UA Supplier Order", self.supplier_order, "docstatus") == 2:
            frappe.throw(_("Замовлення {0} скасоване").format(self.supplier_order))

    def build(self):
        settle = "632" if self.is_foreign else "631"
        entries, credits = [], []
        groups = {}

        for row, kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            if kind == "goods":
                account = row.account or STOCK_ACCOUNT.get(info.item_type, "281")
                dr_sub = {"Item": row.item, "Warehouse": row.warehouse or self.warehouse}
                extra = {"quantity_dr": flt(row.quantity, 3)}
            else:
                account = row.account or EXPENSE_ACCOUNT
                dr_sub = {"ExpenseItem": row.expense_item, "Department": row.department, "Item": row.item}
                extra = {}
            entries.append(
                self.entry(
                    account,
                    settle,
                    net,
                    dr_sub,
                    self.settle_sub,
                    cur_amount=row.total - row.vat_amount,
                    **extra,
                )
            )

        vat_total = flt(sum(g["vat"] for g in groups.values()), 2)
        gross_total = flt(sum(g["gross"] for g in groups.values()), 2)
        if vat_total:
            entries.append(
                self.entry(
                    VAT_CREDIT_ACCOUNT,
                    settle,
                    vat_total,
                    {"TaxType": TAX_VAT},
                    self.settle_sub,
                    cur_amount=flt(vat_total / self.exchange_rate, 2),
                )
            )

        applied = 0.0
        alloc = {}
        if self.offset_prepayment and gross_total:
            balance = settlement_balance(
                self.organization,
                ADVANCE_ACCOUNT,
                self.counterparty,
                self.contract,
                "dr",
                self.posting_date,
                self._ctx,
            )
            applied = min(max(balance, 0), gross_total)
        if applied > 0:
            entries.append(
                self.entry(
                    settle,
                    ADVANCE_ACCOUNT,
                    applied,
                    self.settle_sub,
                    self.settle_sub,
                    cur_amount=flt(applied / self.exchange_rate, 2),
                )
            )
            alloc = allocate_advance(groups, applied, self.vat_mode)
        advance_vat = flt(sum(v for _g, v in alloc.values()), 2)

        if self.tax_invoice_received and self.vat_mode != VAT_NONE:
            credit_vat = flt(vat_total - advance_vat, 2)
            if credit_vat > 0:
                entries.append(
                    self.entry(VAT_ACCOUNT, VAT_CREDIT_ACCOUNT, credit_vat, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT})
                )
            for key, g in groups.items():
                covered, covered_vat = alloc.get(key, (0, 0))
                vat_left = flt(g["vat"] - covered_vat, 2)
                base_left = flt(g["net"] - (covered - covered_vat), 2)
                if g["taxable"] and vat_left > 0:
                    credits.append(self.vat_row(key, base_left, vat_left, EVENT_SHIPMENT))
        return entries, [], credits

    def on_submit(self):
        super().on_submit()
        self.set_order_status()

    def on_cancel(self):
        super().on_cancel()
        self.set_order_status()

    def set_order_status(self):
        if not self.supplier_order:
            return
        done = frappe.db.exists(
            "UA Purchase Receipt",
            {"supplier_order": self.supplier_order, "docstatus": 1, "name": ("!=", self.name)},
        )
        status = "Виконано" if (self.docstatus == 1 or done) else "Відкрито"
        frappe.db.set_value("UA Supplier Order", self.supplier_order, "status", status, update_modified=False)


@frappe.whitelist()
def make_cash_payment(source_name, target_doc=None):
    """Витрата коштів на підставі надходження."""
    receipt = frappe.get_doc("UA Purchase Receipt", source_name)
    receipt.check_permission("read")
    doc = new_from_basis(receipt, "UA Cash Payment", "purchase_receipt", copy_lines=False)
    doc.operation_type = "Оплата постачальнику"
    doc.settlement_type = "Оплата за надходження"
    doc.amount = receipt.total_amount
    return doc
