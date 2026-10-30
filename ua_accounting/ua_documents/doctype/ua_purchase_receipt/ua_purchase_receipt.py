import frappe
from frappe import _
from frappe.utils import add_days, flt

from ua_accounting.accounting.retail import is_retail, markup_entries, retail_price
from ua_accounting.accounting import packaging
from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    EXPENSE_ACCOUNT,
    STOCK_ACCOUNT,
    TAX_VAT,
    TYPE_GOODS,
    VAT_NONE,
    TradeDocument,
    allocate_advance,
    fill_cash_side,
    new_from_basis,
    settlement_balance,
    vat_info,
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

    def calculate(self):
        super().calculate()
        if not self.accounting_policy or self.accounting_policy.vat_payer:
            return
        extra = 0.0
        for row, _kind in self.lines():
            percent, taxable = vat_info(row.vat_rate, {})
            if taxable:
                tax = flt(flt(row.quantity) * flt(row.price) * percent / 100, 2)
                row.total = flt(row.total + tax, 2)
                extra += tax
        self.total_amount = flt(self.total_amount + extra, 2)
        self.total_net = self.total_amount
        self.base_total = self.uah(self.total_amount)

    def validate(self):
        super().validate()
        self.set_payment_due_date()
        packaging.prepare(self)
        if self.supplier_order and frappe.db.get_value("UA Supplier Order", self.supplier_order, "docstatus") == 2:
            frappe.throw(_("Замовлення {0} скасоване").format(self.supplier_order))
        for row in self.goods or []:
            warehouse = row.warehouse or self.warehouse
            if is_retail(warehouse):
                retail_price(row.item, warehouse, self.posting_date, row.idx)

    def set_payment_due_date(self):
        """Due date of the payment: the date of the document + the payment term of the contract."""
        if self.payment_due_date:
            return
        days = (frappe.db.get_value("UA Counterparty Contract", self.contract, "payment_term_days") if self.contract else 0) or 0
        self.payment_due_date = add_days(self.posting_date, days)

    def build(self):
        settle = "632" if self.is_foreign else "631"
        entries, credits = [], []
        groups = {}

        for row, kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            retail = kind == "goods" and is_retail(row.warehouse or self.warehouse)
            if retail:
                if info.item_type != TYPE_GOODS:
                    frappe.throw(_("Рядок {0}: на роздрібний склад приймають лише товари").format(row.idx))
            if kind == "goods":
                account = "282" if retail else row.account or STOCK_ACCOUNT.get(info.item_type, "281")
                dr_sub = {"Item": row.item, "Warehouse": row.warehouse or self.warehouse}
                extra = {"quantity_dr": flt(row.quantity, 3)}
            else:
                account = row.account or EXPENSE_ACCOUNT
                dr_sub = {"ExpenseItem": row.expense_item, "Department": row.department, "Item": row.item}
                extra = {}
            amount = gross if self.vat_mode == VAT_NONE else net
            entries.append(
                self.entry(
                    account,
                    settle,
                    amount,
                    dr_sub,
                    self.settle_sub,
                    cur_amount=row.total if self.vat_mode == VAT_NONE else row.total - row.vat_amount,
                    **extra,
                )
            )
            if retail:
                entries.extend(markup_entries(self, row, row.warehouse or self.warehouse, amount, row.quantity))

        entries.extend(packaging.receipt_entries(self, settle))

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
        from ua_accounting.administration import set_status

        set_status("UA Supplier Order", self.supplier_order, status)


@frappe.whitelist()
def make_cash_payment(source_name, target_doc=None):
    """Витрата коштів на підставі надходження."""
    receipt = frappe.get_doc("UA Purchase Receipt", source_name)
    receipt.check_permission("read")
    doc = new_from_basis(receipt, "UA Cash Payment", "purchase_receipt", copy_lines=False)
    doc.operation_type = "Оплата постачальнику"
    doc.settlement_type = "Оплата за надходження"
    doc.amount = receipt.total_amount
    fill_cash_side(doc)
    return doc
