"""Returnable packaging (поворотна тара): deposit in purchases and sales, return, settlements.

Purchase receipt row: Dt 284 Ct 631 at the deposit price, no VAT.
Sales invoice row:    Dt 361 Ct 284 at the deposit price, no VAT.
Return to supplier:   Dt 631 Ct 284.   Return from buyer: Dt 284 Ct 361.
The settlements by counterparty are read from the submitted documents.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.accounting.stock import StockDocument, take_cost
from ua_accounting.accounting.utils import title_of

PACKAGING_ACCOUNT = "284"
LINE = "UA Packaging Line"
TO_SUPPLIER = "Постачальнику"
FROM_BUYER = "Від покупця"


def prepare(doc):
    """Check the packaging rows of a purchase or a sale, fill amounts. Return the deposit total in the document currency."""
    total = 0.0
    for row in doc.get("packaging") or []:
        check_row(doc, row)
        total += row.amount
    total = flt(total, 2)
    if total:
        doc.total_amount = flt(doc.total_amount + total, 2)
        doc.base_total = flt(doc.base_total + doc.uah(total), 2)
    return total


def check_row(doc, row):
    info = frappe.db.get_value("UA Item", row.item, ["item_name", "item_type", "uom", "is_group"], as_dict=True)
    if not info:
        frappe.throw(_("Тара, рядок {0}: номенклатуру {1} не знайдено").format(row.idx, title_of("UA Item", row.item)))
    if info.is_group or info.item_type == "Послуга":
        frappe.throw(_("Тара, рядок {0}: {1} не є запасом").format(row.idx, title_of("UA Item", row.item)))
    if flt(row.quantity) <= 0:
        frappe.throw(_("Тара, рядок {0}: кількість має бути більше нуля").format(row.idx))
    if flt(row.price) < 0:
        frappe.throw(_("Тара, рядок {0}: ціна не може бути від'ємною").format(row.idx))
    row.item_name = info.item_name
    row.uom = row.uom or info.uom
    row.warehouse = row.warehouse or doc.get("warehouse")
    if not row.warehouse:
        frappe.throw(_("Тара, рядок {0}: вкажіть склад").format(row.idx))
    if frappe.db.get_value("UA Warehouse", row.warehouse, "organization") != doc.organization:
        frappe.throw(_("Тара, рядок {0}: склад {1} належить іншій організації або не існує").format(row.idx, row.warehouse))
    row.amount = flt(flt(row.quantity) * flt(row.price), 2)


def sub(row):
    return {"Item": row.item, "Warehouse": row.warehouse}


def receipt_entries(doc, settle):
    """Dt 284 Ct 631: the deposit for the containers received with the goods."""
    entries = []
    for row in doc.get("packaging") or []:
        entries.append(
            doc.entry(
                PACKAGING_ACCOUNT,
                settle,
                doc.uah(row.amount),
                sub(row),
                doc.settle_sub,
                cur_amount=row.amount,
                quantity_dr=flt(row.quantity, 3),
            )
        )
    return entries


def sale_entries(doc, settle, used):
    """Dt 361 Ct 284: the deposit for the containers given to the buyer."""
    entries = []
    for row in doc.get("packaging") or []:
        take_cost(doc, row, PACKAGING_ACCOUNT, row.item, row.warehouse, row.quantity, used)  # stock check
        entries.append(
            doc.entry(
                settle,
                PACKAGING_ACCOUNT,
                doc.uah(row.amount),
                doc.settle_sub,
                sub(row),
                cur_amount=row.amount,
                quantity_cr=flt(row.quantity, 3),
            )
        )
    return entries


# ---------------------------------------------------------------- settlements

# (document, sign of the quantity: + the counterparty holds our packaging, exchange rate column)
SOURCES = (
    ("UA Purchase Receipt", "-1", "p.exchange_rate"),
    ("UA Sales Invoice", "1", "p.exchange_rate"),
    ("UA Packaging Return", f"if(p.direction = '{FROM_BUYER}', -1, 1)", "1"),
)


def balances(organization, counterparty=None, item=None, date=None, exclude=None):
    """[{counterparty, item, quantity, amount}]: positive = the counterparty holds our packaging."""
    result = {}
    for doctype, sign, rate in SOURCES:
        sql = (
            f"select p.counterparty, l.item, sum(l.quantity * {sign}) as quantity, "
            f"sum(l.amount * {sign} * coalesce({rate}, 1)) as amount "
            f"from `tab{doctype}` p join `tab{LINE}` l on l.parent = p.name and l.parenttype = %s "
            "where p.docstatus = 1 and p.organization = %s"
        )
        values = [doctype, organization]
        if counterparty:
            sql += " and p.counterparty = %s"
            values.append(counterparty)
        if item:
            sql += " and l.item = %s"
            values.append(item)
        if date:
            sql += " and p.posting_date <= %s"
            values.append(getdate(date))
        if exclude and exclude[0] == doctype:
            sql += " and p.name != %s"
            values.append(exclude[1])
        sql += " group by p.counterparty, l.item"
        for cp, it, qty, amount in frappe.db.sql(sql, values):
            key = (cp, it)
            old = result.get(key, (0.0, 0.0))
            result[key] = (old[0] + flt(qty), old[1] + flt(amount))
    rows = []
    for (cp, it), (qty, amount) in sorted(result.items()):
        qty, amount = flt(qty, 3), flt(amount, 2)
        if qty or amount:
            rows.append({"counterparty": cp, "item": it, "quantity": qty, "amount": amount})
    return rows


def held_quantity(organization, counterparty, item, date, exclude=None):
    rows = balances(organization, counterparty, item, date, exclude)
    return flt(sum(r["quantity"] for r in rows), 3)


# ---------------------------------------------------------------- document


class UAPackagingReturn(StockDocument):
    """Повернення тари: постачальнику (Дт 631 Кт 284) або від покупця (Дт 284 Кт 361)."""

    doc_code = "PKR"
    doc_title = "Повернення тари"
    goods_table = "packaging"

    def validate(self):
        AccountingDocument.validate(self)
        if self.direction not in (TO_SUPPLIER, FROM_BUYER):
            frappe.throw(_("Напрям повернення має бути «{0}» або «{1}»").format(TO_SUPPLIER, FROM_BUYER))
        if not self.get("packaging"):
            frappe.throw(_("Заповніть табличну частину «Тара»"))
        self.check_warehouse(self.warehouse)
        if self.contract:
            contract = frappe.db.get_value(
                "UA Counterparty Contract", self.contract, ["counterparty", "organization"], as_dict=True
            )
            if not contract or contract.counterparty != self.counterparty or contract.organization != self.organization:
                frappe.throw(_("Договір {0} не підходить до цього документа").format(title_of("UA Counterparty Contract", self.contract)))
        for row in self.packaging:
            check_row(self, row)

    @property
    def settle_sub(self):
        return {"Counterparty": self.counterparty, "Contract": self.contract, "SettlementDoc": (self.doctype, self.name)}

    def build(self):
        entries, used, left = [], {}, {}
        exclude = (self.doctype, self.name)
        for row in self.packaging:
            if row.item not in left:
                rows = balances(self.organization, self.counterparty, row.item, self.posting_date, exclude)
                balance = [sum(r["quantity"] for r in rows), sum(r["amount"] for r in rows)]
                if self.direction == TO_SUPPLIER:
                    balance = [-balance[0], -balance[1]]
                left[row.item] = [flt(balance[0], 3), flt(balance[1], 2)]
            qty_left, amount_left = left[row.item]
            qty = flt(row.quantity, 3)
            if qty > qty_left:
                frappe.throw(
                    _("Тару {0} повертають у кількості {1}, а в контрагента {2}: {3}").format(
                        title_of("UA Item", row.item), qty, title_of("UA Counterparty", self.counterparty), max(qty_left, 0)
                    )
                )
            # the return is valued at the deposit that is still open, whatever price the row has
            amount = amount_left if qty == qty_left else flt(amount_left * qty / qty_left, 2)
            left[row.item] = [flt(qty_left - qty, 3), flt(amount_left - amount, 2)]
            if flt(row.amount, 2) != amount:
                row.amount = amount
                row.db_set("amount", amount, update_modified=False)
            if self.direction == TO_SUPPLIER:
                take_cost(self, row, PACKAGING_ACCOUNT, row.item, row.warehouse, qty, used)  # stock check
                entries.append(self.entry("631", PACKAGING_ACCOUNT, amount, self.settle_sub, sub(row), quantity_cr=qty))
            else:
                entries.append(self.entry(PACKAGING_ACCOUNT, "361", amount, sub(row), self.settle_sub, quantity_dr=qty))
        return entries, [], []
