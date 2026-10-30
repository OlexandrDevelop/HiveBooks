"""Retail trade: sales report, return, revaluation, cash collection, acquiring.

A retail warehouse keeps goods at retail prices (VAT included) on 282. The trade markup is on 285:
    282 = goods at retail price, 285 = retail price - cost (Кт). Real cost of the stock = 282 - 285.
A sale writes off 282 (Дт 902) and takes back the markup (Дт 285 Кт 902).
"""

import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.accounting import ledger
from ua_accounting.accounting.bank_cash import account_balance, check_cash_balance
from ua_accounting.accounting.documents import EVENT_SHIPMENT, TAX_VAT, AccountingDocument, vat_info
from ua_accounting.accounting.utils import title_of

RETAIL = "Роздрібний"
AUTOMATED = "Автоматизована"
NOT_AUTOMATED = "Неавтоматизована"
REFUND_CASH, REFUND_CARD, REFUND_MIXED = "Готівка", "Картка", "Змішано"
STOCK, MARKUP, TRANSIT = "282", "285", "333"
GOODS = "Товар"


# ---------------------------------------------------------------- helpers


def is_retail(warehouse):
    return bool(warehouse) and frappe.db.get_value("UA Warehouse", warehouse, "kind") == RETAIL


def retail_price(item, warehouse, date, idx=None):
    """Retail price (VAT included) of an item for a warehouse on a date."""
    from ua_accounting.ua_documents.pricing import price_of

    price_type = frappe.db.get_value("UA Warehouse", warehouse, "retail_price_type")
    if not price_type:
        frappe.throw(_("Для складу {0} не вказано тип роздрібних цін").format(title_of("UA Warehouse", warehouse)))
    price = price_of(item, price_type, date)
    if price is None:
        frappe.throw(
            _("{0}для {1} не встановлено роздрібну ціну типу {2}").format(
                _("Рядок {0}: ").format(idx) if idx else "", title_of("UA Item", item), title_of("UA Price Type", price_type)
            )
        )
    return price


def markup_entries(doc, row, warehouse, cost, qty):
    """Дт 282 Кт 285: the markup of goods that come into a retail warehouse at the cost `cost`."""
    value = flt(flt(qty) * retail_price(row.item, warehouse, doc.posting_date, row.idx), 2)
    markup = flt(value - cost, 2)
    if markup < 0:
        frappe.throw(
            _("Рядок {0}: роздрібна ціна {1} менша за ціну придбання").format(row.idx, title_of("UA Item", row.item))
        )
    sub = {"Item": row.item, "Warehouse": warehouse}
    return [doc.entry(STOCK, MARKUP, markup, sub, sub)]


def retail_stock(organization, warehouse, date):
    """{item: [value 282, quantity 282, markup 285]} of a retail warehouse on the end of the date."""
    result = {}

    def put(item):
        return result.setdefault(item, [0.0, 0.0, 0.0])

    for side, sign in (("dr", 1), ("cr", -1)):
        for account in (STOCK, MARKUP):
            rows = frappe.db.sql(
                f"""select subconto_{side}1 as item, sum(amount) as amount, sum(quantity_{side}) as qty
                from `tabUA Accounting Entry` where organization = %s and account_{side} = %s
                and subconto_{side}2 = %s and posting_date <= %s and subconto_{side}1 != '' group by 1""",
                (organization, account, warehouse, date),
                as_dict=True,
            )
            for r in rows:
                line = put(r.item)
                if account == STOCK:
                    line[0] += sign * flt(r.amount)
                    line[1] += sign * flt(r.qty)
                else:
                    line[2] -= sign * flt(r.amount)
    return {k: [flt(v[0], 2), flt(v[1], 3), flt(v[2], 2)] for k, v in result.items()}


def take_retail(row, stock, item, qty):
    """(value, markup) of `qty` taken from `stock` (see retail_stock). The stock is reduced."""
    value, have, markup = stock.get(item, [0.0, 0.0, 0.0])
    qty = flt(qty, 3)
    if qty > have:
        frappe.throw(
            _("Рядок {0}: недостатньо {1} на роздрібному складі: залишок {2}, потрібно {3}").format(
                row.idx, title_of("UA Item", item), frappe.format(have, {"fieldtype": "Float", "precision": 3}),
                frappe.format(qty, {"fieldtype": "Float", "precision": 3}),
            )
        )
    if qty == have:
        taken_value, taken_markup = value, markup
    else:
        taken_value, taken_markup = flt(value * qty / have, 2), flt(markup * qty / have, 2)
    stock[item] = [flt(value - taken_value, 2), flt(have - qty, 3), flt(markup - taken_markup, 2)]
    return taken_value, taken_markup


def sold_stats(organization, warehouse, item, date):
    """(value 282, quantity, markup 285) of the goods sold from a retail warehouse and not returned."""
    value = qty = markup = 0.0
    for dr, cr, side, sign in (("902", STOCK, "cr", 1), (STOCK, "902", "dr", -1)):
        row = frappe.db.sql(
            f"""select coalesce(sum(amount), 0), coalesce(sum(quantity_{side}), 0) from `tabUA Accounting Entry`
            where organization = %s and account_dr = %s and account_cr = %s and subconto_{side}1 = %s
            and subconto_{side}2 = %s and posting_date <= %s""",
            (organization, dr, cr, item, warehouse, date),
        )[0]
        value += sign * flt(row[0])
        qty += sign * flt(row[1])
    for dr, cr, side, sign in ((MARKUP, "902", "dr", 1), ("902", MARKUP, "cr", -1)):
        row = frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where organization = %s and account_dr = %s and account_cr = %s and subconto_{side}1 = %s
            and subconto_{side}2 = %s and posting_date <= %s""",
            (organization, dr, cr, item, warehouse, date),
        )[0]
        markup += sign * flt(row[0])
    return flt(value, 2), flt(qty, 3), flt(markup, 2)


def split_payment(grosses, card_total):
    """Spread the card part of a payment over table rows: [(cash, card)] by row."""
    total = flt(sum(grosses), 2)
    rest = flt(card_total, 2)
    out = []
    for i, gross in enumerate(grosses):
        if i == len(grosses) - 1:
            card = rest
        else:
            card = min(flt(gross * card_total / total, 2) if total else 0.0, rest)
        rest = flt(rest - card, 2)
        out.append((flt(gross - card, 2), card))
    return out


# ---------------------------------------------------------------- base


class RetailDocument(AccountingDocument):
    def check_retail(self):
        wh = frappe.db.get_value("UA Warehouse", self.warehouse, ["organization", "kind"], as_dict=True)
        if not wh:
            frappe.throw(_("Склад {0} не знайдено").format(self.warehouse))
        if wh.organization != self.organization:
            frappe.throw(_("Склад {0} належить іншій організації").format(title_of("UA Warehouse", self.warehouse)))
        if wh.kind != RETAIL:
            frappe.throw(_("Склад {0} не є роздрібним").format(title_of("UA Warehouse", self.warehouse)))

    def check_cash_desk(self):
        if frappe.db.get_value("UA Cash Desk", self.cash_desk, "organization") != self.organization:
            frappe.throw(_("Каса належить іншій організації"))

    def check_bank_account(self):
        if self.bank_account and frappe.db.get_value("UA Bank Account", self.bank_account, "organization") != self.organization:
            frappe.throw(_("Банківський рахунок належить іншій організації"))

    def vat_percent(self, vat_rate):
        policy = self.accounting_policy
        payer = policy.vat_payer if policy else frappe.db.get_value("UA Organization", self.organization, "vat_payer")
        if not payer:
            return 0.0
        percent, taxable = vat_info(vat_rate, self.__dict__.setdefault("_vat_cache", {}))
        return percent if taxable else 0.0

    def vat_of(self, gross, vat_rate):
        percent = self.vat_percent(vat_rate)
        return flt(flt(gross) * percent / (100 + percent), 2) if percent else 0.0

    def check_lines(self):
        """Checks and fills the rows of the table `goods`: goods only, amount by quantity and price."""
        for row in self.goods:
            info = frappe.db.get_value("UA Item", row.item, ["item_name", "item_type", "vat_rate", "is_group"], as_dict=True)
            if not info or info.is_group or info.item_type != GOODS:
                frappe.throw(_("Рядок {0}: {1} не є товаром").format(row.idx, title_of("UA Item", row.item)))
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
            if flt(row.price) <= 0:
                frappe.throw(_("Рядок {0}: ціна має бути більше нуля").format(row.idx))
            row.item_name = info.item_name
            row.vat_rate = row.vat_rate or info.vat_rate
            row.amount = flt(flt(row.quantity) * flt(row.price), 2)

    def money_entries(self, gross, cash, card, item=None, vat_rate=None, refund=False):
        """Cash and card part of the revenue (or of the refund)."""
        entries = []
        revenue = {"Item": item, "VatRate": vat_rate}
        for amount, account, sub in (
            (cash, "301", {"CashDesk": self.cash_desk}),
            (card, TRANSIT, {"BankAccount": self.bank_account}),
        ):
            if not amount:
                continue
            if refund:
                entries.append(self.entry("702", account, amount, revenue, sub))
            else:
                entries.append(self.entry(account, "702", amount, sub, revenue))
        return entries

    def vat_entries(self, gross, vat_amount, item, vat_rate, refund=False):
        """VAT of the revenue: Дт 704 Кт 641 (a refund is the reverse) and the VAT register row."""
        if not vat_amount:
            return [], []
        revenue = {"Item": item, "VatRate": vat_rate}
        tax = {"TaxType": TAX_VAT}
        sign = -1 if refund else 1
        base = flt(gross - vat_amount, 2)
        entry = self.entry("641", "704", vat_amount, tax, revenue) if refund else self.entry("704", "641", vat_amount, revenue, tax)
        return [entry], [self.vat_row(vat_rate, sign * base, sign * vat_amount, EVENT_SHIPMENT)]


# ---------------------------------------------------------------- sales report


class UARetailSalesReport(RetailDocument):
    """Звіт про роздрібні продажі.

    Дт 301 (333) Кт 702 revenue with VAT, Дт 704 Кт 641 VAT,
    Дт 902 Кт 282 retail value, Дт 285 Кт 902 markup written off.
    Automated outlet: by the rows. Non-automated: the markup percent is 285 / 282 of the warehouse.
    """

    doc_code = "RS"
    doc_title = "Звіт про роздрібні продажі"

    def validate(self):
        super().validate()
        self.check_retail()
        self.check_cash_desk()
        self.check_bank_account()
        if self.outlet_type == AUTOMATED:
            if not self.goods:
                frappe.throw(_("Заповніть табличну частину «Товари»"))
            self.check_lines()
            self.revenue_amount = flt(sum(r.amount for r in self.goods), 2)
            self.vat_amount = flt(sum(self.vat_of(r.amount, r.vat_rate) for r in self.goods), 2)
        else:
            self.set("goods", [])
            if flt(self.revenue_amount) <= 0:
                frappe.throw(_("Вкажіть виручку більше нуля"))
            self.vat_amount = self.vat_of(self.revenue_amount, self.vat_rate)
        cash, card = flt(self.cash_amount, 2), flt(self.card_amount, 2)
        if cash < 0 or card < 0:
            frappe.throw(_("Суми оплати не можуть бути від’ємними"))
        if abs(cash + card - flt(self.revenue_amount, 2)) > 0.005:
            frappe.throw(_("Готівка і картка ({0}) мають дорівнювати виручці ({1})").format(cash + card, self.revenue_amount))

    def build(self):
        stock = retail_stock(self.organization, self.warehouse, self.posting_date)
        entries, credits_, cost = [], [], 0.0
        liabilities = []
        revenue = flt(self.revenue_amount, 2)
        if self.outlet_type == AUTOMATED:
            parts = split_payment([r.amount for r in self.goods], self.card_amount)
            for row, (cash, card) in zip(self.goods, parts, strict=True):
                entries += self.money_entries(row.amount, cash, card, row.item, row.vat_rate)
                vat_entries, vat_rows = self.vat_entries(row.amount, self.vat_of(row.amount, row.vat_rate), row.item, row.vat_rate)
                entries += vat_entries
                liabilities += vat_rows
                value, markup = take_retail(row, stock, row.item, row.quantity)
                entries += self.write_off(row.item, flt(row.quantity, 3), value, markup)
                cost += value - markup
        else:
            entries += self.money_entries(revenue, flt(self.cash_amount, 2), flt(self.card_amount, 2), None, self.vat_rate)
            vat_entries, vat_rows = self.vat_entries(revenue, self.vat_amount, None, self.vat_rate)
            entries += vat_entries
            liabilities += vat_rows
            written = self.write_off_by_percent(stock, revenue)
            entries += written[0]
            cost = written[1]
        self.db_set("cost_amount", flt(cost, 2), update_modified=False)
        return entries, liabilities, credits_

    def write_off(self, item, qty, value, markup):
        sub = {"Item": item, "Warehouse": self.warehouse}
        return [
            self.entry("902", STOCK, value, {"Item": item}, sub, quantity_cr=qty),
            self.entry(MARKUP, "902", markup, sub, {"Item": item}),
        ]

    def write_off_by_percent(self, stock, revenue):
        """Non-automated outlet: the revenue is written off from 282, the markup by the percent 285 / 282."""
        items = [(item, line) for item, line in stock.items() if line[1] > 0 and line[0] > 0]
        total_value = flt(sum(line[0] for _i, line in items), 2)
        total_markup = flt(sum(line[2] for _i, line in items), 2)
        if revenue > total_value:
            frappe.throw(
                _("Виручка {0} перевищує вартість товарів {1} у роздрібних цінах на складі {2}").format(
                    revenue, total_value, title_of("UA Warehouse", self.warehouse)
                )
            )
        everything = revenue == total_value
        markup_total = total_markup if everything else flt(total_markup * revenue / total_value, 2)
        rest_value, rest_markup = revenue, markup_total
        entries, cost = [], 0.0
        for n, (item, (value, qty, markup)) in enumerate(items):
            if n == len(items) - 1:
                part_value, part_markup = rest_value, rest_markup
            elif everything:
                part_value, part_markup = value, markup
            else:
                part_value = flt(value * revenue / total_value, 2)
                part_markup = flt(markup * part_value / value, 2)
            part_qty = qty if part_value == value else flt(qty * part_value / value, 3)
            if part_value and not part_qty:
                frappe.throw(_("Виручка {0} надто мала для списання {1}: кількість менша за 0,001").format(
                    revenue, title_of("UA Item", item)))
            rest_value = flt(rest_value - part_value, 2)
            rest_markup = flt(rest_markup - part_markup, 2)
            entries += self.write_off(item, part_qty, part_value, part_markup)
            cost += part_value - part_markup
        return entries, cost


# ---------------------------------------------------------------- return


class UARetailReturn(RetailDocument):
    """Повернення від роздрібного покупця.

    Дт 702 Кт 301 (333) refund, Дт 641 Кт 704 VAT, Дт 282 Кт 902 value, Дт 902 Кт 285 markup:
    the value and the markup are those of the goods that were sold.
    """

    doc_code = "RR"
    doc_title = "Повернення від роздрібного покупця"

    def validate(self):
        super().validate()
        self.check_retail()
        self.check_cash_desk()
        self.check_bank_account()
        if not self.goods:
            frappe.throw(_("Заповніть табличну частину «Товари»"))
        self.check_lines()
        total = flt(sum(r.amount for r in self.goods), 2)
        self.total_amount = total
        if self.refund_type == REFUND_CASH:
            self.cash_amount, self.card_amount = total, 0
        elif self.refund_type == REFUND_CARD:
            self.cash_amount, self.card_amount = 0, total
        elif abs(flt(self.cash_amount) + flt(self.card_amount) - total) > 0.005 or min(flt(self.cash_amount), flt(self.card_amount)) < 0:
            frappe.throw(_("Готівка і картка мають дорівнювати сумі повернення {0}").format(total))

    def on_submit(self):
        if flt(self.cash_amount) > 0:
            check_cash_balance(self.organization, self.cash_desk, self.posting_date, -flt(self.cash_amount))
        super().on_submit()

    def build(self):
        entries, liabilities, used = [], [], {}
        parts = split_payment([r.amount for r in self.goods], self.card_amount)
        for row, (cash, card) in zip(self.goods, parts, strict=True):
            entries += self.money_entries(row.amount, cash, card, row.item, row.vat_rate, refund=True)
            vat_entries, vat_rows = self.vat_entries(row.amount, self.vat_of(row.amount, row.vat_rate), row.item, row.vat_rate, refund=True)
            entries += vat_entries
            liabilities += vat_rows
            if row.item not in used:
                used[row.item] = list(sold_stats(self.organization, self.warehouse, row.item, self.posting_date))
            value, have, markup = used[row.item]
            qty = flt(row.quantity, 3)
            if qty > have:
                frappe.throw(
                    _("Рядок {0}: повертається {1}, а продано з цього складу лише {2}").format(
                        row.idx, qty, have)
                )
            taken_value = value if qty == have else flt(value * qty / have, 2)
            taken_markup = markup if qty == have else flt(markup * qty / have, 2)
            used[row.item] = [flt(value - taken_value, 2), flt(have - qty, 3), flt(markup - taken_markup, 2)]
            sub = {"Item": row.item, "Warehouse": self.warehouse}
            entries.append(self.entry(STOCK, "902", taken_value, sub, {"Item": row.item}, quantity_dr=qty))
            entries.append(self.entry("902", MARKUP, taken_markup, {"Item": row.item}, sub))
        return entries, liabilities, []


# ---------------------------------------------------------------- revaluation


class UARetailRevaluation(RetailDocument):
    """Переоцінка товарів у роздрібі: Дт 282 Кт 285 (дооцінка) або Дт 285 Кт 282 (уцінка).

    The change is `quantity × new price − value on 282`. The new prices are registered as a price setting.
    """

    doc_code = "RV"
    doc_title = "Переоцінка товарів у роздрібі"

    def validate(self):
        super().validate()
        self.check_retail()
        self.price_type = frappe.db.get_value("UA Warehouse", self.warehouse, "retail_price_type")
        if not self.price_type:
            frappe.throw(_("Для складу {0} не вказано тип роздрібних цін").format(title_of("UA Warehouse", self.warehouse)))
        if not self.lines:
            frappe.throw(_("Заповніть табличну частину «Товари»"))
        self.check_shared_price_type()
        stock = retail_stock(self.organization, self.warehouse, self.posting_date)
        seen = set()
        for row in self.lines:
            info = frappe.db.get_value("UA Item", row.item, ["item_name", "item_type", "is_group"], as_dict=True)
            if not info or info.is_group or info.item_type != GOODS:
                frappe.throw(_("Рядок {0}: {1} не є товаром").format(row.idx, title_of("UA Item", row.item)))
            if row.item in seen:
                frappe.throw(_("Рядок {0}: номенклатура повторюється").format(row.idx))
            seen.add(row.item)
            value, qty, _markup = stock.get(row.item, [0.0, 0.0, 0.0])
            if qty <= 0:
                frappe.throw(_("Рядок {0}: {1} немає на складі {2}").format(
                    row.idx, title_of("UA Item", row.item), title_of("UA Warehouse", self.warehouse)))
            if flt(row.new_price) < 0:
                frappe.throw(_("Рядок {0}: ціна не може бути від’ємною").format(row.idx))
            row.item_name = info.item_name
            row.quantity = qty
            row.old_price = flt(value / qty, 2)
            row.difference = flt(qty * flt(row.new_price) - value, 2)

    def check_shared_price_type(self):
        """A price type is shared by warehouses: a new price must not leave stock of another warehouse at the old one."""
        others = frappe.get_all(
            "UA Warehouse",
            filters={"retail_price_type": self.price_type, "kind": RETAIL, "name": ("!=", self.warehouse)},
            fields=["name", "organization"],
        )
        items = {r.item for r in self.lines}
        for other in others:
            held = [i for i, line in retail_stock(other.organization, other.name, self.posting_date).items() if i in items and line[1] > 0]
            if held:
                frappe.throw(
                    _("Тип цін {0} спільний зі складом {1}, де є залишок {2}: використайте окремий тип цін для кожного складу").format(
                        title_of("UA Price Type", self.price_type), title_of("UA Warehouse", other.name), title_of("UA Item", held[0])
                    )
                )

    def build(self):
        stock = retail_stock(self.organization, self.warehouse, self.posting_date)
        entries = []
        for row in self.lines:
            diff = flt(row.difference, 2)
            if not diff:
                continue
            sub = {"Item": row.item, "Warehouse": self.warehouse}
            if diff > 0:
                entries.append(self.entry(STOCK, MARKUP, diff, sub, sub))
            else:
                if flt(stock[row.item][2] + diff, 2) < 0:
                    frappe.throw(_("Рядок {0}: нова ціна нижча за собівартість, торгова націнка стане від’ємною").format(row.idx))
                entries.append(self.entry(MARKUP, STOCK, -diff, sub, sub))
        return entries, [], []

    def post_document(self):
        self._ctx = {}
        entries, _liabilities, _credits = self.build()
        if entries:
            ledger.post_entries(self, entries)

    def on_submit(self):
        super().on_submit()
        setting = frappe.get_doc(
            {
                "doctype": "UA Price Setting",
                "posting_date": self.posting_date,
                "price_type": self.price_type,
                "comment": f"{self.doc_title} {self.name}",
                "prices": [{"item": r.item, "price": r.new_price} for r in self.lines],
            }
        )
        setting.insert(ignore_permissions=True)
        setting.submit()
        self.db_set("price_setting", setting.name, update_modified=False)

    def on_cancel(self):
        super().on_cancel()
        if self.price_setting and frappe.db.get_value("UA Price Setting", self.price_setting, "docstatus") == 1:
            setting = frappe.get_doc("UA Price Setting", self.price_setting)
            setting.flags.ignore_permissions = True
            setting.cancel()


# ---------------------------------------------------------------- cash collection, acquiring


class UACashCollection(RetailDocument):
    """Інкасація: Дт 333 Кт 301. The bank credit closes 333 with a cash receipt (Дт 311 Кт 333)."""

    doc_code = "CC"
    doc_title = "Інкасація"

    def validate(self):
        super().validate()
        if flt(self.amount) <= 0:
            frappe.throw(_("Сума має бути більше нуля"))
        self.check_cash_desk()
        self.check_bank_account()

    def on_submit(self):
        check_cash_balance(self.organization, self.cash_desk, self.posting_date, -flt(self.amount))
        super().on_submit()

    def build(self):
        return [self.entry(TRANSIT, "301", self.amount, {"BankAccount": self.bank_account}, {"CashDesk": self.cash_desk})], [], []


class UAAcquiringSettlement(RetailDocument):
    """Зарахування за еквайрингом: Дт 311 Кт 333 (отримано), Дт 93 Кт 333 (комісія)."""

    doc_code = "AS"
    doc_title = "Зарахування за еквайрингом"

    def validate(self):
        super().validate()
        if flt(self.received_amount) <= 0:
            frappe.throw(_("Сума, зарахована банком, має бути більше нуля"))
        if flt(self.commission_amount) < 0:
            frappe.throw(_("Комісія не може бути від’ємною"))
        if flt(self.commission_amount) and not self.expense_item:
            frappe.throw(_("Вкажіть статтю витрат для комісії"))
        self.check_bank_account()

    def on_submit(self):
        total = flt(flt(self.received_amount) + flt(self.commission_amount), 2)
        transit = account_balance(self.organization, TRANSIT, self.posting_date)
        if total > transit:
            frappe.throw(_("Сума зарахування {0} перевищує залишок коштів у дорозі {1}").format(total, transit))
        super().on_submit()

    def build(self):
        bank = {"BankAccount": self.bank_account}
        return [
            self.entry("311", TRANSIT, self.received_amount, bank, bank),
            self.entry("93", TRANSIT, self.commission_amount, {"ExpenseItem": self.expense_item}, bank),
        ], [], []
