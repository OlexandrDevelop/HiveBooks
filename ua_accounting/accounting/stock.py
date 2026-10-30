"""Stock documents: transfer, write-off, surplus, inventory, assembly, МШП issue, requirement invoice.

Cost of the stock that leaves a warehouse comes from `take_cost`: moving average
or FIFO, as the accounting policy says. Back-dated documents re-post later
documents that took stock of the same items (`recalc_later`).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, get_datetime

from ua_accounting.accounting import ledger, vat
from ua_accounting.accounting.documents import (
    STOCK_ACCOUNT,
    AccountingDocument,
    TYPE_SERVICE,
    slot_of,
    stock_balance,
)
from ua_accounting.accounting.retail import is_retail, markup_entries, retail_price
from ua_accounting.accounting.utils import title_of

STOCK_ACCOUNTS = ("281", "201", "22", "26")
FIFO = "ФІФО"
KIND_ASSEMBLY = "Комплектація"
KIND_DISASSEMBLY = "Розкомплектація"
COST_DOCTYPES = (
    "UA Sales Invoice",
    "UA Stock Transfer",
    "UA Stock Writeoff",
    "UA Stock Assembly",
    "UA Low Value Issue",
    "UA Requirement Invoice",
    "UA Production Report",
)


# ---------------------------------------------------------------- cost


def fifo_cost(doc, account, item, warehouse, quantity, already_taken):
    """Cost of `quantity` from the oldest receipt layers. A layer is one entry (one document line); the entries of one assembly are one layer."""
    item_slot = slot_of(account, "Item", doc._ctx)
    warehouse_slot = slot_of(account, "Warehouse", doc._ctx)
    if not item_slot or not warehouse_slot:
        return 0.0
    incoming = frappe.db.sql(
        f"""select min(posting_date) as posting_date, min(creation) as creation,
        sum(quantity_dr) as qty, sum(amount) as amount
        from `tabUA Accounting Entry` where organization = %s and account_dr = %s
        and subconto_dr{item_slot} = %s and subconto_dr{warehouse_slot} = %s and posting_date <= %s
        group by registrar_type, registrar, if(registrar_type = 'UA Stock Assembly', 0, line_no)
        having sum(quantity_dr) > 0 order by min(posting_date), min(creation), min(line_no)""",
        (doc.organization, account, item, warehouse, doc.posting_date),
        as_dict=True,
    )
    outgoing = frappe.db.sql(
        f"""select coalesce(sum(quantity_cr), 0) from `tabUA Accounting Entry`
        where organization = %s and account_cr = %s
        and subconto_cr{item_slot} = %s and subconto_cr{warehouse_slot} = %s and posting_date <= %s""",
        (doc.organization, account, item, warehouse, doc.posting_date),
    )[0][0]
    skip = flt(outgoing + already_taken, 3)
    remaining = quantity
    cost = 0.0
    for lot in incoming:
        lot_qty = flt(lot.qty, 3)
        if skip >= lot_qty:
            skip = flt(skip - lot_qty, 3)
            continue
        take = min(remaining, flt(lot_qty - skip, 3))
        cost += flt(flt(lot.amount) * take / lot_qty, 2)
        remaining = flt(remaining - take, 3)
        skip = 0
        if remaining <= 0:
            break
    return flt(cost, 2)


def take_cost(doc, row, stock, item, warehouse, qty, used):
    """Cost of `qty` taken from a warehouse by `doc`. `used` keeps what the document took already."""
    key = (stock, item, warehouse)
    if key not in used:
        used[key] = list(stock_balance(doc.organization, stock, item, warehouse, doc.posting_date, doc._ctx, lock=True))
        used[key].extend([0.0, 0.0])
    bal_amount, bal_qty, taken_amount, taken_qty = used[key]
    left_qty = flt(bal_qty - taken_qty, 3)
    left_amount = flt(bal_amount - taken_amount, 2)
    qty = flt(qty, 3)
    if qty > left_qty:
        frappe.throw(
            _("Рядок {0}: недостатньо {1} на складі {2}: залишок {3}, потрібно {4}").format(
                row.idx,
                title_of("UA Item", item),
                title_of("UA Warehouse", warehouse),
                frappe.format(left_qty, {"fieldtype": "Float", "precision": 3}),
                frappe.format(qty, {"fieldtype": "Float", "precision": 3}),
            )
        )
    policy = doc.accounting_policy
    if policy and policy.cost_method == FIFO:
        cost = fifo_cost(doc, stock, item, warehouse, qty, taken_qty)
        # the ledger balance wins: FIFO layers must not overdraw the stock value
        cost = left_amount if qty == left_qty else min(cost, max(left_amount, 0.0))
    else:
        cost = left_amount if qty == left_qty else flt(left_amount * qty / left_qty, 2)
    used[key][2] += cost
    used[key][3] += qty
    return cost


# ---------------------------------------------------------------- base


class StockDocument(AccountingDocument):
    goods_table = "goods"

    def validate(self):
        super().validate()
        self.validate_goods()

    def item_info(self, item):
        cache = self.__dict__.setdefault("_items", {})
        if item not in cache:
            cache[item] = (
                frappe.db.get_value("UA Item", item, ["item_name", "item_type", "uom", "is_group"], as_dict=True)
                or frappe._dict()
            )
        return cache[item]

    def check_warehouse(self, warehouse):
        if not warehouse:
            frappe.throw(_("Вкажіть склад"))
        org = frappe.db.get_value("UA Warehouse", warehouse, "organization")
        if org is None and not frappe.db.exists("UA Warehouse", warehouse):
            frappe.throw(_("Склад {0} не знайдено").format(warehouse))
        if org != self.organization:
            frappe.throw(_("Склад {0} належить іншій організації").format(title_of("UA Warehouse", warehouse)))

    def stock_account(self, row, item=None):
        item = item or row.item
        info = self.item_info(item)
        if not info:
            frappe.throw(_("Рядок {0}: номенклатуру {1} не знайдено").format(row.idx, item))
        if info.is_group:
            frappe.throw(_("Рядок {0}: {1} є групою номенклатури").format(row.idx, title_of("UA Item", item)))
        if info.item_type == TYPE_SERVICE:
            frappe.throw(_("Рядок {0}: послуга {1} не є запасом").format(row.idx, title_of("UA Item", item)))
        return (row.get("account") if row.meta.has_field("account") else None) or STOCK_ACCOUNT[info.item_type]

    def validate_goods(self):
        rows = self.get(self.goods_table) or []
        if not rows:
            frappe.throw(_("Заповніть табличну частину «Товари»"))
        for row in rows:
            self.stock_account(row)
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
            row.item_name = self.item_info(row.item).item_name
            row.uom = row.uom or self.item_info(row.item).uom

    def stock_sub(self, item, warehouse):
        return {"Item": item, "Warehouse": warehouse}


class OutgoingDocument(StockDocument):
    """Write-off, МШП issue, requirement invoice: Дт expense account Кт stock at cost."""

    default_expense = ""
    expense_choices = ()
    stock_override = None  # fixed stock account (22 for МШП)

    def validate(self):
        super().validate()
        self.check_warehouse(self.warehouse)
        self.expense_account = self.expense_account or self.default_expense
        if self.expense_choices and self.expense_account not in self.expense_choices:
            frappe.throw(_("Рахунок витрат {0} не підходить для цього документа").format(self.expense_account))

    def before_submit(self):
        if not self.expense_item:
            frappe.throw(_("Вкажіть статтю витрат"))

    def stock_account(self, row, item=None):
        if self.stock_override and not row.get("account"):
            super().stock_account(row, item)  # checks the item
            return self.stock_override
        return super().stock_account(row, item)

    def build(self):
        entries, used = [], {}
        for row in self.goods:
            stock = self.stock_account(row)
            cost = take_cost(self, row, stock, row.item, self.warehouse, row.quantity, used)
            entries.append(
                self.entry(
                    self.expense_account,
                    stock,
                    cost,
                    {"ExpenseItem": self.expense_item, "Department": self.get("department")},
                    self.stock_sub(row.item, self.warehouse),
                    quantity_cr=flt(row.quantity, 3),
                )
            )
            entries.extend(self.extra_entries(cost))
        return entries, [], []

    def extra_entries(self, cost):
        return []


# ---------------------------------------------------------------- documents


class UAStockTransfer(StockDocument):
    """Переміщення товарів: Дт 281 (склад-одержувач) Кт 281 (склад-відправник) at cost."""

    doc_code = "ST"
    doc_title = "Переміщення товарів"

    def validate(self):
        super().validate()
        if self.warehouse_from == self.warehouse_to:
            frappe.throw(_("Склади відправника і одержувача збігаються"))
        self.check_warehouse(self.warehouse_from)
        self.check_warehouse(self.warehouse_to)
        if is_retail(self.warehouse_from):
            frappe.throw(_("З роздрібного складу товари не переміщують: їх продають звітом про роздрібні продажі"))
        if is_retail(self.warehouse_to):
            for row in self.goods:
                retail_price(row.item, self.warehouse_to, self.posting_date, row.idx)

    def build(self):
        entries, used = [], {}
        to_retail = is_retail(self.warehouse_to)
        for row in self.goods:
            stock = self.stock_account(row)
            cost = take_cost(self, row, stock, row.item, self.warehouse_from, row.quantity, used)
            qty = flt(row.quantity, 3)
            if to_retail and stock != "281":
                frappe.throw(_("Рядок {0}: на роздрібний склад передають лише товари").format(row.idx))
            entries.append(
                self.entry(
                    "282" if to_retail else stock,
                    stock,
                    cost,
                    self.stock_sub(row.item, self.warehouse_to),
                    self.stock_sub(row.item, self.warehouse_from),
                    quantity_dr=qty,
                    quantity_cr=qty,
                )
            )
            if to_retail:
                entries.extend(markup_entries(self, row, self.warehouse_to, cost, qty))
        return entries, [], []


class UAStockWriteoff(OutgoingDocument):
    """Списання товарів: Дт 947 (або 92, 93, 949) Кт 281 at cost."""

    doc_code = "SW"
    doc_title = "Списання товарів"
    default_expense = "947"
    expense_choices = ("947", "92", "93", "949", "23", "911", "912", "913")


class UALowValueIssue(OutgoingDocument):
    """Передача матеріалів в експлуатацію: Дт 92 Кт 22 at cost and Дт 09 off the balance."""

    doc_code = "LV"
    doc_title = "Передача матеріалів в експлуатацію"
    default_expense = "92"
    stock_override = "22"

    def extra_entries(self, cost):
        return [self.entry("09", None, cost)]


class UARequirementInvoice(OutgoingDocument):
    """Вимога-накладна: Дт 23 / 91x / 92 / 93 / 949 Кт 201 at cost."""

    doc_code = "RQ"
    doc_title = "Вимога-накладна"
    default_expense = "23"
    expense_choices = ("23", "911", "912", "913", "92", "93", "949")


class UAStockSurplus(StockDocument):
    """Оприбуткування товарів: Дт 281 Кт 719 at the market price."""

    doc_code = "SS"
    doc_title = "Оприбуткування товарів"

    def validate(self):
        super().validate()
        self.check_warehouse(self.warehouse)

    def before_submit(self):
        for row in self.goods:
            if flt(row.price) <= 0:
                frappe.throw(_("Рядок {0}: вкажіть ціну більше нуля").format(row.idx))

    def build(self):
        entries = []
        for row in self.goods:
            entries.append(
                self.entry(
                    self.stock_account(row),
                    "719",
                    flt(flt(row.quantity) * flt(row.price), 2),
                    self.stock_sub(row.item, self.warehouse),
                    None,
                    quantity_dr=flt(row.quantity, 3),
                )
            )
        return entries, [], []


class UAStockInventory(AccountingDocument):
    """Інвентаризація товарів. Posts nothing: write-off and surplus are made on its basis."""

    doc_code = "IN"
    doc_title = "Інвентаризація товарів"
    posts = False

    def validate(self):
        super().validate()
        if not self.warehouse or frappe.db.get_value("UA Warehouse", self.warehouse, "organization") != self.organization:
            frappe.throw(_("Вкажіть склад організації"))
        if not self.lines:
            frappe.throw(_("Заповніть табличну частину"))
        seen = set()
        for row in self.lines:
            info = frappe.db.get_value("UA Item", row.item, ["item_name", "item_type", "uom"], as_dict=True)
            if not info or info.item_type == TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: {1} не є запасом").format(row.idx, title_of("UA Item", row.item)))
            if row.item in seen:
                frappe.throw(_("Рядок {0}: номенклатура повторюється").format(row.idx))
            seen.add(row.item)
            if flt(row.actual_quantity) < 0:
                frappe.throw(_("Рядок {0}: кількість не може бути від'ємною").format(row.idx))
            stock = STOCK_ACCOUNT[info.item_type]
            amount, qty = stock_balance(self.organization, stock, row.item, self.warehouse, self.posting_date, self._ctx)
            row.item_name = info.item_name
            row.uom = row.uom or info.uom
            row.book_quantity = qty
            row.deviation = flt(flt(row.actual_quantity) - qty, 3)
            if not flt(row.price) and qty > 0:
                row.price = flt(amount / qty, 2)
            row.deviation_amount = flt(row.deviation * flt(row.price), 2)


class UAStockAssembly(AccountingDocument):
    """Комплектація / розкомплектація.

    Assembly: per component Дт 281 (product) Кт 281 (component) at the component cost.
    Disassembly: per component Дт 281 (component) Кт 281 (product) at its share of the product cost.
    """

    doc_code = "SA"
    doc_title = "Комплектація/розкомплектація"

    def validate(self):
        super().validate()
        if not self.warehouse or frappe.db.get_value("UA Warehouse", self.warehouse, "organization") != self.organization:
            frappe.throw(_("Вкажіть склад організації"))
        if flt(self.product_quantity) <= 0:
            frappe.throw(_("Кількість комплектів має бути більше нуля"))
        if not self.components:
            frappe.throw(_("Заповніть склад комплекту"))
        for row in self.components:
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
            self.stock_account(row.item, row.idx)
        self.stock_account(self.product, 0)
        if self.kind == KIND_DISASSEMBLY:
            total = sum(flt(r.cost_share) for r in self.components)
            if abs(total - 100) > 0.001:
                frappe.throw(_("Сума часток собівартості має дорівнювати 100 %"))

    def stock_account(self, item, idx):
        info = frappe.db.get_value("UA Item", item, ["item_type", "is_group"], as_dict=True)
        if not info or info.is_group or info.item_type == TYPE_SERVICE:
            frappe.throw(_("Рядок {0}: {1} не є запасом").format(idx, title_of("UA Item", item)))
        return STOCK_ACCOUNT[info.item_type]

    def build(self):
        used, entries = {}, []
        product_account = self.stock_account(self.product, 0)
        product_qty = flt(self.product_quantity, 3)
        prow = frappe._dict(idx=0)
        if self.kind == KIND_DISASSEMBLY:
            total = take_cost(self, prow, product_account, self.product, self.warehouse, product_qty, used)
            rest = total
            last = len(self.components)
            for n, row in enumerate(self.components, start=1):
                amount = rest if n == last else flt(total * flt(row.cost_share) / 100, 2)
                rest = flt(rest - amount, 2)
                entries.append(
                    self.entry(
                        self.stock_account(row.item, row.idx),
                        product_account,
                        amount,
                        {"Item": row.item, "Warehouse": self.warehouse},
                        {"Item": self.product, "Warehouse": self.warehouse},
                        quantity_dr=flt(row.quantity, 3),
                        quantity_cr=product_qty if n == 1 else 0,
                    )
                )
            return entries, [], []
        for n, row in enumerate(self.components, start=1):
            account = self.stock_account(row.item, row.idx)
            cost = take_cost(self, row, account, row.item, self.warehouse, row.quantity, used)
            entries.append(
                self.entry(
                    product_account,
                    account,
                    cost,
                    {"Item": self.product, "Warehouse": self.warehouse},
                    {"Item": row.item, "Warehouse": self.warehouse},
                    quantity_dr=product_qty if n == 1 else 0,
                    quantity_cr=flt(row.quantity, 3),
                )
            )
        return entries, [], []


# ---------------------------------------------------------------- inventory basis


@frappe.whitelist()
def make_inventory_documents(inventory):
    """Draft write-off (shortage) and surplus (excess) on the basis of a submitted inventory."""
    inv = frappe.get_doc("UA Stock Inventory", inventory)
    inv.check_permission("write")
    if inv.docstatus != 1:
        frappe.throw(_("Інвентаризація {0} не проведена").format(inv.name))
    shortage = [r for r in inv.lines if flt(r.deviation) < 0]
    excess = [r for r in inv.lines if flt(r.deviation) > 0]
    head = {"organization": inv.organization, "posting_date": inv.posting_date, "warehouse": inv.warehouse}
    result = {"writeoff": inv.writeoff_doc or None, "surplus": inv.surplus_doc or None}
    if shortage and not inv.writeoff_doc:
        doc = frappe.get_doc(
            {
                "doctype": "UA Stock Writeoff",
                **head,
                "reason": _("Нестача за інвентаризацією {0}").format(inv.name),
                "goods": [{"item": r.item, "quantity": -flt(r.deviation)} for r in shortage],
            }
        ).insert()
        result["writeoff"] = doc.name
    if excess and not inv.surplus_doc:
        doc = frappe.get_doc(
            {
                "doctype": "UA Stock Surplus",
                **head,
                "goods": [{"item": r.item, "quantity": flt(r.deviation), "price": r.price} for r in excess],
            }
        ).insert()
        result["surplus"] = doc.name
    frappe.db.set_value(
        "UA Stock Inventory",
        inv.name,
        {"writeoff_doc": result["writeoff"] or "", "surplus_doc": result["surplus"] or ""},
        update_modified=False,
    )
    return result


# ---------------------------------------------------------------- back-dated recalculation


def recalc_later(doc, method=None):
    """Re-post later documents that took stock of the items a submitted/cancelled document changed."""
    if getattr(frappe.flags, "ua_recalc_off", False):
        return
    if doc.meta.module != "UA Documents" or not getattr(doc, "posts", False):
        return
    items = entry_items(doc.doctype, doc.name)
    if doc.docstatus == 2:
        # entries are gone already: take the items from the document rows
        for table in doc.meta.get_table_fields():
            for row in doc.get(table.fieldname) or []:
                if row.get("item"):
                    items.add(row.item)
        if doc.get("product"):
            items.add(doc.product)
    if not items:
        return
    start = (getdate(doc.posting_date), get_datetime(doc.creation))
    done = {(doc.doctype, doc.name)}
    while True:
        rows = frappe.db.sql(
            """select distinct registrar_type, registrar from `tabUA Accounting Entry`
            where organization = %s and posting_date >= %s and registrar_type in %s
            and account_cr in %s and subconto_cr1 in %s""",
            (doc.organization, start[0], COST_DOCTYPES, STOCK_ACCOUNTS, tuple(items)),
            as_dict=True,
        )
        later = []
        for r in rows:
            if (r.registrar_type, r.registrar) in done:
                continue
            info = frappe.db.get_value(r.registrar_type, r.registrar, ["posting_date", "creation"], as_dict=True)
            if not info or (getdate(info.posting_date), get_datetime(info.creation)) <= start:
                continue
            later.append((getdate(info.posting_date), get_datetime(info.creation), r.registrar_type, r.registrar))
        if not later:
            return
        _date, _created, doctype, name = min(later)
        done.add((doctype, name))
        other = frappe.get_doc(doctype, name)
        links = _vat_links(doctype, name)
        ledger.cancel_entries(other)
        other.post_document()
        _restore_vat_links(doctype, name, links)
        # what the re-posted document produced (assembly output, transfer target) changes later withdrawals too
        items |= entry_items(doctype, name)


def _vat_links(doctype, name):
    """{(register, line_no): (tax_invoice_type, tax_invoice)} of the VAT register rows of a document."""
    links = {}
    for table in (vat.LIABILITY, vat.CREDIT):
        for r in frappe.get_all(
            table,
            filters={"registrar_type": doctype, "registrar": name, "tax_invoice": ("is", "set")},
            fields=["line_no", "tax_invoice_type", "tax_invoice"],
            limit_page_length=0,
        ):
            links[(table, r.line_no)] = (r.tax_invoice_type, r.tax_invoice)
    return links


def _restore_vat_links(doctype, name, links):
    """Put the tax invoice links back on the rewritten VAT register rows (amounts stay as posted)."""
    for (table, line_no), (link_type, link) in links.items():
        frappe.db.set_value(
            table,
            {"registrar_type": doctype, "registrar": name, "line_no": line_no, "tax_invoice": ("is", "not set")},
            {"tax_invoice_type": link_type, "tax_invoice": link},
            update_modified=False,
        )


def entry_items(doctype, name):
    """Items on stock accounts in the entries of a document."""
    items = set()
    for side in ("dr", "cr"):
        items.update(
            frappe.db.sql_list(
                f"""select distinct subconto_{side}1 from `tabUA Accounting Entry`
                where registrar_type = %s and registrar = %s and account_{side} in %s and subconto_{side}1 != ''""",
                (doctype, name, STOCK_ACCOUNTS),
            )
        )
    return items


# ---------------------------------------------------------------- report data


def stock_movements(organization, date_from=None, date_to=None, warehouse=None, item=None):
    """{(item, warehouse): {"dr": [qty, amount], "cr": [qty, amount]}} of entries in the period.

    Stock accounts have Item in the 1st and Warehouse in the 2nd subconto.
    """
    from ua_accounting.administration import report_scope

    allowed = report_scope(organization, warehouse)
    result = {}
    for side in ("dr", "cr"):
        cond = [f"organization = %s", f"account_{side} in %s"]
        values = [organization, STOCK_ACCOUNTS]
        if date_from:
            cond.append("posting_date >= %s")
            values.append(date_from)
        if date_to:
            cond.append("posting_date <= %s")
            values.append(date_to)
        if warehouse:
            cond.append(f"subconto_{side}2 = %s")
            values.append(warehouse)
        elif allowed:
            cond.append(f"subconto_{side}2 in %s")
            values.append(tuple(allowed))
        if item:
            cond.append(f"subconto_{side}1 = %s")
            values.append(item)
        rows = frappe.db.sql(
            f"""select subconto_{side}1 as item, subconto_{side}2 as warehouse,
            sum(quantity_{side}) as qty, sum(amount) as amount from `tabUA Accounting Entry`
            where {' and '.join(cond)} and subconto_{side}1 != '' group by 1, 2""",
            values,
            as_dict=True,
        )
        for r in rows:
            entry = result.setdefault((r.item, r.warehouse), {"dr": [0.0, 0.0], "cr": [0.0, 0.0]})
            entry[side][0] += flt(r.qty)
            entry[side][1] += flt(r.amount)
    return result
