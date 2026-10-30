import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import (
    COST_ACCOUNT,
    COST_ACCOUNT_DEFAULT,
    EVENT_SHIPMENT,
    REVENUE_ACCOUNT,
    STOCK_ACCOUNT,
    TAX_VAT,
    VAT_NONE,
    TradeDocument,
    new_from_basis,
    slot_of,
)
from ua_accounting.accounting.utils import title_of

VAT_ACCOUNT = "641"
VAT_DEDUCTION_ACCOUNT = "704"


class UASalesReturn(TradeDocument):
    """Повернення товарів від покупця: the reverse of the sale.

    Dt 702 Ct 361   revenue with VAT
    Dt 641 Ct 704   VAT of the sale is taken back
    Dt 281 Ct 902   goods come back at the cost of the sale (not at the current average)
    """

    doc_code = "SRT"
    doc_title = "Повернення товарів від покупця"

    def validate(self):
        self.take_basis_terms("UA Sales Invoice", self.sales_invoice)
        super().validate()
        for row in self.goods:
            if not (row.warehouse or self.warehouse):
                frappe.throw(_("Рядок {0}: вкажіть склад").format(row.idx))
        self.check_basis()

    def check_basis(self):
        sale = frappe.db.get_value(
            "UA Sales Invoice", self.sales_invoice, ["docstatus", "organization", "counterparty", "posting_date"],
            as_dict=True,
        )
        if not sale or sale.docstatus != 1:
            frappe.throw(_("Реалізація {0} не проведена").format(self.sales_invoice))
        if sale.organization != self.organization or sale.counterparty != self.counterparty:
            frappe.throw(_("Реалізація {0} не підходить до цього повернення").format(self.sales_invoice))
        if getdate(self.posting_date) < getdate(sale.posting_date):
            frappe.throw(_("Повернення не може бути раніше реалізації {0}").format(self.sales_invoice))
        sold = self.basis_quantities()
        returned = self.returned_before()
        asked = {}
        for row in self.goods:
            asked[row.item] = flt(asked.get(row.item, 0) + flt(row.quantity), 3)
        for item, qty in asked.items():
            left = flt(sold.get(item, 0) - returned.get(item, (0, 0))[0], 3)
            if qty > left:
                frappe.throw(
                    _("Номенклатуру {0} можна повернути не більше {1}: продано {2}, вже повернуто {3}").format(
                        title_of("UA Item", item), left, sold.get(item, 0), returned.get(item, (0, 0))[0]
                    )
                )

    def basis_quantities(self):
        rows = frappe.get_all(
            "UA Goods Line",
            filters={"parent": self.sales_invoice, "parenttype": "UA Sales Invoice", "parentfield": "goods"},
            fields=["item", "quantity"],
        )
        sold = {}
        for row in rows:
            sold[row.item] = flt(sold.get(row.item, 0) + row.quantity, 3)
        return sold

    def returned_before(self):
        """{item: (quantity, cost)} of the other submitted returns of the same sale."""
        others = frappe.get_all(
            "UA Sales Return",
            filters={"sales_invoice": self.sales_invoice, "docstatus": 1, "name": ("!=", self.name or "")},
            pluck="name",
        )
        result = {}
        for row in frappe.get_all(
            "UA Goods Line",
            filters={"parent": ("in", others or [""]), "parenttype": "UA Sales Return", "parentfield": "goods"},
            fields=["item", "quantity"],
        ):
            qty, cost = result.get(row.item, (0, 0))
            result[row.item] = (flt(qty + row.quantity, 3), cost)
        for doc_name in others:
            for item, (_account, amount) in self.stock_entries(doc_name, "UA Sales Return", debit=True).items():
                qty, cost = result.get(item, (0, 0))
                result[item] = (qty, flt(cost + amount, 2))
        return result

    def stock_entries(self, registrar, doctype, debit):
        """{item: (account, amount)} of the stock entries of a document (return: Dt 281; sale: Ct 281)."""
        side = "dr" if debit else "cr"
        result = {}
        for account in set(STOCK_ACCOUNT.values()):
            slot = slot_of(account, "Item", self._ctx)
            if not slot:
                continue
            for e in frappe.get_all(
                "UA Accounting Entry",
                filters={"registrar_type": doctype, "registrar": registrar, f"account_{side}": account},
                fields=["amount", f"subconto_{side}{slot}"],
            ):
                item = e.get(f"subconto_{side}{slot}")
                prev = result.get(item, (account, 0))
                result[item] = (account, flt(prev[1] + e.amount, 2))
        return result

    def sold_cost(self):
        """{item: (stock account, cost, quantity)} of the basis sale."""
        cost = self.stock_entries(self.sales_invoice, "UA Sales Invoice", debit=False)
        sold = self.basis_quantities()
        return {item: (account, amount, sold.get(item, 0)) for item, (account, amount) in cost.items()}

    # ------------------------------------------------------------ posting

    def build(self):
        self._ctx = {}
        settle = "362" if self.is_foreign else "361"
        entries, registers = [], []
        groups = {}
        tax_sub = {"TaxType": TAX_VAT}
        costs = self.sold_cost()
        returned = self.returned_before()
        taken_qty, taken_cost = {}, {}
        for row, _kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}
            entries.append(
                self.entry(
                    REVENUE_ACCOUNT.get(info.item_type, "702"), settle, gross, item_sub, self.settle_sub,
                    cur_amount=row.total,
                )
            )
            if vat_amount:
                entries.append(self.entry(VAT_ACCOUNT, VAT_DEDUCTION_ACCOUNT, vat_amount, tax_sub, item_sub))
            if row.item in costs:
                account, total_cost, sold_qty = costs[row.item]
                qty = flt(row.quantity, 3)
                prev_qty, prev_cost = returned.get(row.item, (0, 0))
                done_qty = taken_qty.get(row.item, 0)
                done_cost = taken_cost.get(row.item, 0)
                if flt(prev_qty + done_qty + qty, 3) >= sold_qty:
                    cost = flt(total_cost - prev_cost - done_cost, 2)  # the last piece takes the rounding
                else:
                    cost = flt(total_cost * qty / sold_qty, 2)
                taken_qty[row.item] = flt(done_qty + qty, 3)
                taken_cost[row.item] = flt(done_cost + cost, 2)
                entries.append(
                    self.entry(
                        account,
                        COST_ACCOUNT.get(account, COST_ACCOUNT_DEFAULT),
                        cost,
                        {"Item": row.item, "Warehouse": row.warehouse or self.warehouse},
                        {"Item": row.item, "ExpenseItem": None},
                        quantity_dr=qty,
                        content=_("Собівартість {0}").format(self.name)[:140],
                    )
                )
        if self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                if g["taxable"] and g["vat"] > 0:
                    registers.append(self.vat_row(key, -g["net"], -g["vat"], EVENT_SHIPMENT))
        return entries, registers, []


@frappe.whitelist()
def make_sales_return(source_name, target_doc=None):
    """Повернення товарів від покупця на підставі реалізації."""
    sale = frappe.get_doc("UA Sales Invoice", source_name)
    sale.check_permission("read")
    doc = new_from_basis(sale, "UA Sales Return", "sales_invoice", copy_lines=False)
    for row in sale.goods:
        doc.append("goods", {k: row.get(k) for k in ("item", "uom", "quantity", "price", "vat_rate", "warehouse",
                                                    "discount_percent")})
    return doc
