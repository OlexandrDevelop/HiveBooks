import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting.documents import (
    COST_ACCOUNT,
    COST_ACCOUNT_DEFAULT,
    EVENT_SHIPMENT,
    REVENUE_ACCOUNT,
    STOCK_ACCOUNT,
    TAX_VAT,
    TYPE_SERVICE,
    VAT_NONE,
    TradeDocument,
    allocate_advance,
    new_from_basis,
    settlement_balance,
    stock_balance,
)

ADVANCE_ACCOUNT = "681"
VAT_ACCOUNT = "641"
VAT_PREPAID_ACCOUNT = "643"
VAT_DEDUCTION_ACCOUNT = "704"


class UASalesInvoice(TradeDocument):
    """Реалізація товарів та послуг.

    Dt 361 Ct 70x   revenue (with VAT)
    Dt 704 Ct 641   VAT liability of the shipment
    Dt 90x Ct 281   cost of goods, average cost of the warehouse
    Dt 681 Ct 361   offset of the advance
    Dt 641 Ct 643   VAT already taken at the advance (first event rule)
    """

    doc_code = "SI"
    doc_title = "Реалізація товарів та послуг"

    def validate(self):
        super().validate()
        if self.customer_order and self.customer_order_status() == 2:
            frappe.throw(_("Замовлення {0} скасоване").format(self.customer_order))
        for row in self.get(self.goods_table) or []:
            if not (row.warehouse or self.warehouse) and self.item_info(row.item).item_type != TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: вкажіть склад").format(row.idx))

    def customer_order_status(self):
        return frappe.db.get_value("UA Customer Order", self.customer_order, "docstatus")

    # ------------------------------------------------------------ posting

    def build(self):
        settle = "362" if self.is_foreign else "361"
        entries, liabilities = [], []
        groups = {}
        used = {}  # stock already taken by this document: key -> [amount, quantity]

        for row, kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}

            entries.append(
                self.entry(
                    settle,
                    REVENUE_ACCOUNT.get(info.item_type, "702"),
                    gross,
                    self.settle_sub,
                    item_sub,
                    cur_amount=row.total,
                )
            )
            if vat_amount:
                entries.append(
                    self.entry(VAT_DEDUCTION_ACCOUNT, VAT_ACCOUNT, vat_amount, item_sub, {"TaxType": TAX_VAT})
                )
            if kind == "goods" and info.item_type in STOCK_ACCOUNT:
                entries.append(self.cost_entry(row, info, used))

        applied = 0.0
        alloc = {}
        gross_total = sum(g["gross"] for g in groups.values())
        if self.offset_advance and gross_total:
            balance = settlement_balance(
                self.organization,
                ADVANCE_ACCOUNT,
                self.counterparty,
                self.contract,
                "cr",
                self.posting_date,
                self._ctx,
            )
            applied = min(max(balance, 0), gross_total)
        if applied > 0:
            entries.append(
                self.entry(
                    ADVANCE_ACCOUNT,
                    settle,
                    applied,
                    self.settle_sub,
                    self.settle_sub,
                    cur_amount=flt(applied / self.exchange_rate, 2),
                )
            )
            alloc = allocate_advance(groups, applied, self.vat_mode)
            advance_vat = flt(sum(v for _g, v in alloc.values()), 2)
            if advance_vat:
                # the VAT liability of this part was recorded when the advance was paid
                entries.append(
                    self.entry(VAT_ACCOUNT, VAT_PREPAID_ACCOUNT, advance_vat, {"TaxType": TAX_VAT}, {"TaxType": TAX_VAT})
                )

        if self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                covered, covered_vat = alloc.get(key, (0, 0))
                vat_left = flt(g["vat"] - covered_vat, 2)
                base_left = flt(g["net"] - (covered - covered_vat), 2)
                if g["taxable"] and (vat_left > 0 or base_left > 0):
                    liabilities.append(self.vat_row(key, base_left, vat_left, EVENT_SHIPMENT))
        return entries, liabilities, []

    def cost_entry(self, row, info, used):
        """Dt 902 Ct 281 at the average cost of the item in the warehouse."""
        stock = row.account or STOCK_ACCOUNT[info.item_type]
        warehouse = row.warehouse or self.warehouse
        key = (stock, row.item, warehouse)
        if key not in used:
            used[key] = list(stock_balance(self.organization, stock, row.item, warehouse, self.posting_date, self._ctx))
            used[key].extend([0.0, 0.0])
        bal_amount, bal_qty, taken_amount, taken_qty = used[key]
        left_qty = flt(bal_qty - taken_qty, 3)
        left_amount = flt(bal_amount - taken_amount, 2)
        qty = flt(row.quantity, 3)
        if qty > left_qty:
            frappe.throw(
                _("Рядок {0}: недостатньо {1} на складі {2}: залишок {3}, потрібно {4}").format(
                    row.idx, row.item_name or row.item, warehouse, left_qty, qty
                )
            )
        cost = left_amount if qty == left_qty else flt(left_amount * qty / left_qty, 2)
        used[key][2] += cost
        used[key][3] += qty
        return self.entry(
            COST_ACCOUNT.get(stock, COST_ACCOUNT_DEFAULT),
            stock,
            cost,
            {"Item": row.item, "ExpenseItem": None},
            {"Item": row.item, "Warehouse": warehouse},
            quantity_cr=qty,
            content=_("Собівартість {0}").format(self.name)[:140],
        )

    # ------------------------------------------------------------ order status

    def on_submit(self):
        super().on_submit()
        self.set_order_status()

    def on_cancel(self):
        super().on_cancel()
        self.set_order_status()

    def set_order_status(self):
        if not self.customer_order:
            return
        done = frappe.db.exists(
            "UA Sales Invoice",
            {"customer_order": self.customer_order, "docstatus": 1, "name": ("!=", self.name)},
        )
        if self.docstatus == 1 or done:
            status = "Виконано"
        else:
            status = "Відкрито"
        frappe.db.set_value("UA Customer Order", self.customer_order, "status", status, update_modified=False)


@frappe.whitelist()
def make_cash_receipt(source_name, target_doc=None):
    """Надходження коштів на підставі реалізації."""
    sale = frappe.get_doc("UA Sales Invoice", source_name)
    sale.check_permission("read")
    doc = new_from_basis(sale, "UA Cash Receipt", "sales_invoice", copy_lines=False)
    doc.operation_type = "Оплата від покупця"
    doc.settlement_type = "Оплата за реалізацію"
    doc.amount = sale.total_amount
    return doc
