import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    STOCK_ACCOUNT,
    TAX_VAT,
    VAT_NONE,
    TradeDocument,
    new_from_basis,
    stock_balance,
)
from ua_accounting.accounting.utils import title_of

VAT_ACCOUNT = "641"
VAT_CREDIT_ACCOUNT = "644"


class UAPurchaseReturn(TradeDocument):
    """Повернення товарів постачальнику: the reverse of the receipt, at the price of the receipt.

    Dt 631 Ct 281   goods without VAT
    Dt 631 Ct 644   VAT of the receipt is taken back
    Dt 644 Ct 641   the tax credit is reversed, if the tax invoice was received
    """

    doc_code = "PRT"
    doc_title = "Повернення товарів постачальнику"

    def validate(self):
        self.take_basis_terms("UA Purchase Receipt", self.purchase_receipt)
        super().validate()
        for row in self.goods:
            if not (row.warehouse or self.warehouse):
                frappe.throw(_("Рядок {0}: вкажіть склад").format(row.idx))
        self.check_basis()

    def basis(self):
        receipt = frappe.db.get_value(
            "UA Purchase Receipt", self.purchase_receipt,
            ["docstatus", "organization", "counterparty", "posting_date", "tax_invoice_received"], as_dict=True,
        )
        if not receipt or receipt.docstatus != 1:
            frappe.throw(_("Надходження {0} не проведене").format(self.purchase_receipt))
        return receipt

    def basis_rows(self):
        rows = frappe.get_all(
            "UA Goods Line",
            filters={"parent": self.purchase_receipt, "parenttype": "UA Purchase Receipt", "parentfield": "goods"},
            fields=["item", "quantity", "price", "discount_percent"],
            order_by="idx",
        )
        return rows

    def check_basis(self):
        receipt = self.basis()
        if receipt.organization != self.organization or receipt.counterparty != self.counterparty:
            frappe.throw(_("Надходження {0} не підходить до цього повернення").format(self.purchase_receipt))
        if getdate(self.posting_date) < getdate(receipt.posting_date):
            frappe.throw(_("Повернення не може бути раніше надходження {0}").format(self.purchase_receipt))
        received = {}
        for r in self.basis_rows():
            received[r.item] = flt(received.get(r.item, 0) + r.quantity, 3)
        returned = self.returned_before()
        asked = {}
        for row in self.goods:
            asked[row.item] = flt(asked.get(row.item, 0) + flt(row.quantity), 3)
        for item, qty in asked.items():
            left = flt(received.get(item, 0) - returned.get(item, 0), 3)
            if qty > left:
                frappe.throw(
                    _("Номенклатуру {0} можна повернути не більше {1}: отримано {2}, вже повернуто {3}").format(
                        title_of("UA Item", item), left, received.get(item, 0), returned.get(item, 0)
                    )
                )

    def returned_before(self):
        others = frappe.get_all(
            "UA Purchase Return",
            filters={"purchase_receipt": self.purchase_receipt, "docstatus": 1, "name": ("!=", self.name or "")},
            pluck="name",
        )
        result = {}
        for row in frappe.get_all(
            "UA Goods Line",
            filters={"parent": ("in", others or [""]), "parenttype": "UA Purchase Return", "parentfield": "goods"},
            fields=["item", "quantity"],
        ):
            result[row.item] = flt(result.get(row.item, 0) + row.quantity, 3)
        return result

    # ------------------------------------------------------------ posting

    def build(self):
        self._ctx = {}
        settle = "632" if self.is_foreign else "631"
        receipt = self.basis()
        entries, credits = [], []
        groups = {}
        tax_sub = {"TaxType": TAX_VAT}
        used = {}
        for row, _kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            account = row.account or STOCK_ACCOUNT.get(info.item_type, "281")
            warehouse = row.warehouse or self.warehouse
            self.check_stock(row, account, warehouse, used)
            amount = gross if self.vat_mode == VAT_NONE else net
            entries.append(
                self.entry(
                    settle,
                    account,
                    amount,
                    self.settle_sub,
                    {"Item": row.item, "Warehouse": warehouse},
                    cur_amount=row.total if self.vat_mode == VAT_NONE else row.total - row.vat_amount,
                    quantity_cr=flt(row.quantity, 3),
                )
            )
        vat_total = flt(sum(g["vat"] for g in groups.values()), 2)
        if vat_total:
            entries.append(
                self.entry(
                    settle, VAT_CREDIT_ACCOUNT, vat_total, self.settle_sub, {"TaxType": TAX_VAT},
                    cur_amount=flt(vat_total / self.exchange_rate, 2),
                )
            )
            if receipt.tax_invoice_received:
                entries.append(self.entry(VAT_CREDIT_ACCOUNT, VAT_ACCOUNT, vat_total, tax_sub, tax_sub))
        if self.vat_mode != VAT_NONE and receipt.tax_invoice_received:
            for key, g in groups.items():
                if g["taxable"] and g["vat"] > 0:
                    credits.append(self.vat_row(key, -g["net"], -g["vat"], EVENT_SHIPMENT))
        return entries, [], credits

    def check_stock(self, row, account, warehouse, used):
        """The goods must be on the warehouse: sold goods cannot be returned to the supplier."""
        key = (account, row.item, warehouse)
        if key not in used:
            _amount, qty = stock_balance(self.organization, account, row.item, warehouse, self.posting_date, self._ctx)
            used[key] = qty
        qty = flt(row.quantity, 3)
        if qty > flt(used[key], 3):
            frappe.throw(
                _("Рядок {0}: недостатньо {1} на складі {2}: залишок {3}, потрібно {4}").format(
                    row.idx, row.item_name or title_of("UA Item", row.item), title_of("UA Warehouse", warehouse),
                    used[key], qty,
                )
            )
        used[key] = flt(used[key] - qty, 3)


@frappe.whitelist()
def make_purchase_return(source_name, target_doc=None):
    """Повернення товарів постачальнику на підставі надходження."""
    receipt = frappe.get_doc("UA Purchase Receipt", source_name)
    receipt.check_permission("read")
    doc = new_from_basis(receipt, "UA Purchase Return", "purchase_receipt", copy_lines=False)
    for row in receipt.goods:
        doc.append("goods", {k: row.get(k) for k in ("item", "uom", "quantity", "price", "vat_rate", "warehouse",
                                                    "discount_percent")})
    return doc
