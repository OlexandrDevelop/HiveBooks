import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import packaging
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
    fill_cash_side,
    new_from_basis,
    settlement_balance,
)
from ua_accounting.accounting.retail import is_retail
from ua_accounting.accounting.stock import take_cost

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
    Dt 704 Ct 643   VAT already taken at the advance (first event rule), instead of Ct 641
    """

    doc_code = "SI"
    doc_title = "Реалізація товарів та послуг"

    def validate(self):
        super().validate()
        packaging.prepare(self)
        if self.customer_order and self.customer_order_status() == 2:
            frappe.throw(_("Замовлення {0} скасоване").format(self.customer_order))
        for row in self.get(self.goods_table) or []:
            if not (row.warehouse or self.warehouse) and self.item_info(row.item).item_type != TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: вкажіть склад").format(row.idx))
            if is_retail(row.warehouse or self.warehouse):
                frappe.throw(_("Рядок {0}: з роздрібного складу продають звітом про роздрібні продажі").format(row.idx))

    def customer_order_status(self):
        return frappe.db.get_value("UA Customer Order", self.customer_order, "docstatus")

    # ------------------------------------------------------------ posting

    def build(self):
        settle = "362" if self.is_foreign else "361"
        entries, liabilities = [], []
        groups = {}
        used = {}  # stock already taken by this document: key -> [amount, quantity]
        vat_lines = []  # (rate group, VAT amount, subconto) of the rows

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
                vat_lines.append((row.vat_rate or "", vat_amount, item_sub))
            if kind == "goods" and info.item_type in STOCK_ACCOUNT:
                entries.append(self.cost_entry(row, info, used))

        entries.extend(packaging.sale_entries(self, settle, used))

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

        # the VAT liability of the advance part was recorded when the advance was paid:
        # it is closed from 643, only the rest goes to 641
        covered_left = {key: covered_vat for key, (_part, covered_vat) in alloc.items()}
        tax_sub = {"TaxType": TAX_VAT}
        for key, vat_amount, item_sub in vat_lines:
            from_advance = min(covered_left.get(key, 0), vat_amount)
            covered_left[key] = flt(covered_left.get(key, 0) - from_advance, 2)
            if from_advance:
                entries.append(self.entry(VAT_DEDUCTION_ACCOUNT, VAT_PREPAID_ACCOUNT, from_advance, item_sub, tax_sub))
            if flt(vat_amount - from_advance, 2):
                entries.append(
                    self.entry(VAT_DEDUCTION_ACCOUNT, VAT_ACCOUNT, flt(vat_amount - from_advance, 2), item_sub, tax_sub)
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
        """Dt 902 Ct 281 at the cost of the item in the warehouse (average or FIFO by the policy)."""
        stock = row.account or STOCK_ACCOUNT[info.item_type]
        warehouse = row.warehouse or self.warehouse
        qty = flt(row.quantity, 3)
        cost = take_cost(self, row, stock, row.item, warehouse, qty, used)
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
        order = frappe.get_doc("UA Customer Order", self.customer_order)
        invoices = frappe.get_all(
            "UA Sales Invoice", filters={"customer_order": self.customer_order, "docstatus": 1}, pluck="name"
        )
        shipped = {}
        for line_type, table in (("UA Goods Line", "goods"), ("UA Service Line", "services")):
            for row in frappe.get_all(
                line_type,
                filters={"parent": ("in", invoices or [""]), "parenttype": "UA Sales Invoice", "parentfield": table},
                fields=["item", "quantity"],
            ):
                shipped[row.item] = flt(shipped.get(row.item, 0) + row.quantity, 3)
        wanted = [*(order.get("goods") or []), *(order.get("services") or [])]
        if not invoices:
            status = "Відкрито"
        elif all(shipped.get(row.item, 0) >= flt(row.quantity, 3) for row in wanted):
            status = "Виконано"
        else:
            status = "Виконується"
        from ua_accounting.administration import set_status

        set_status("UA Customer Order", self.customer_order, status)


@frappe.whitelist()
def make_cash_receipt(source_name, target_doc=None):
    """Надходження коштів на підставі реалізації."""
    sale = frappe.get_doc("UA Sales Invoice", source_name)
    sale.check_permission("read")
    doc = new_from_basis(sale, "UA Cash Receipt", "sales_invoice", copy_lines=False)
    doc.operation_type = "Оплата від покупця"
    doc.settlement_type = "Оплата за реалізацію"
    doc.amount = sale.total_amount
    fill_cash_side(doc)
    return doc
