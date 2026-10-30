"""Commission trade and tolling raw materials (давальницька сировина).

Agent (комісіонер): goods of the principal are on the off-balance account 024.
Principal (комітент): goods given to the agent are on 283 at cost.
Customer of tolling: raw materials at the processor are on 206.
Processor: raw materials of the customer are on the off-balance account 022.
"""

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
    slot_of,
    vat_info,
)
from ua_accounting.accounting.stock import StockDocument, take_cost
from ua_accounting.accounting.utils import title_of

COMMISSION_AGENT_OFF = "024"
COMMISSION_STOCK = "283"
TOLLING_STOCK = "206"
TOLLING_OFF = "022"
SETTLE_CUSTOMER = "361"
SETTLE_SUPPLIER = "631"
SETTLE_PRINCIPAL = "685"


def off_balance(doc, account, item, counterparty, date):
    """(amount, quantity) of an item of a counterparty on an off-balance account (Item, Counterparty) up to `date`."""
    item_slot = slot_of(account, "Item", doc._ctx)
    cp_slot = slot_of(account, "Counterparty", doc._ctx)
    amount = qty = 0.0
    for side, sign in (("dr", 1), ("cr", -1)):
        a, q = frappe.db.sql(
            f"""select coalesce(sum(amount), 0), coalesce(sum(quantity_{side}), 0) from `tabUA Accounting Entry`
            where organization = %s and account_{side} = %s and posting_date <= %s
            and subconto_{side}{item_slot} = %s and subconto_{side}{cp_slot} = %s""",
            (doc.organization, account, date, item, counterparty),
        )[0]
        amount += sign * flt(a)
        qty += sign * flt(q)
    return flt(amount, 2), flt(qty, 3)


def off_balance_qty(doc, account, item, counterparty, date):
    return off_balance(doc, account, item, counterparty, date)[1]


def running_minimum(doc, account, item, other_type, other, exclude):
    """Smallest running quantity (by day) of an account for item and warehouse/counterparty without the entries of `exclude`."""
    item_slot = slot_of(account, "Item", doc._ctx)
    other_slot = slot_of(account, other_type, doc._ctx)
    by_day = {}
    for side, sign in (("dr", 1), ("cr", -1)):
        rows = frappe.db.sql(
            f"""select posting_date, sum(quantity_{side}) from `tabUA Accounting Entry`
            where organization = %s and account_{side} = %s and subconto_{side}{item_slot} = %s
            and subconto_{side}{other_slot} = %s and not (registrar_type = %s and registrar = %s)
            group by posting_date""",
            (doc.organization, account, item, other, exclude[0], exclude[1]),
        )
        for day, qty in rows:
            by_day[day] = by_day.get(day, 0) + sign * flt(qty)
    total = lowest = 0.0
    for day in sorted(by_day):
        total += by_day[day]
        lowest = min(lowest, total)
    return flt(lowest, 3)


class PartyDocument(StockDocument):
    """Base: header with counterparty and contract, tables of goods rows (UA Goods Line)."""

    tables = ("goods",)  # tables with rows
    priced_tables = ()  # tables that have VAT in the rows
    stock_moves = True  # False: off-balance document, the warehouse is not needed
    guard_cancel = None  # (account, "stock" | "off") : the balance made by the document may not be taken away

    def validate(self):
        super().validate()
        if self.stock_moves or self.get("warehouse"):
            self.check_warehouse(self.warehouse)
        self.check_contract(self.counterparty, self.contract)

    def check_contract(self, counterparty, contract):
        if not contract:
            return
        row = frappe.db.get_value("UA Counterparty Contract", contract, ["counterparty", "organization"], as_dict=True)
        if not row or row.counterparty != counterparty:
            frappe.throw(
                _("Договір {0} не належить контрагенту {1}").format(
                    title_of("UA Counterparty Contract", contract), title_of("UA Counterparty", counterparty)
                )
            )
        if row.organization != self.organization:
            frappe.throw(_("Договір {0} укладено з іншою організацією").format(title_of("UA Counterparty Contract", contract)))

    def rows(self, table=None):
        return list(self.get(table or self.tables[0]) or [])

    def validate_goods(self):
        if not any(self.rows(t) for t in self.tables):
            frappe.throw(_("Заповніть табличну частину «Товари»"))
        cache = {}
        for table in self.tables:
            for row in self.rows(table):
                self.stock_account(row)  # checks the item
                if flt(row.quantity) <= 0:
                    frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
                if flt(row.price) < 0:
                    frappe.throw(_("Рядок {0}: ціна не може бути від'ємною").format(row.idx))
                info = self.item_info(row.item)
                row.item_name = info.item_name
                row.uom = row.uom or info.uom
                row.amount = flt(flt(row.quantity) * flt(row.price), 2)
                row.vat_amount, row.total = row.amount, row.amount
                if table in self.priced_tables:
                    row.vat_rate = row.vat_rate or frappe.db.get_value("UA Item", row.item, "vat_rate")
                    percent, taxable = vat_info(row.vat_rate, cache)
                    row.vat_amount = flt(row.amount * percent / 100, 2) if taxable else 0.0
                    row.total = flt(row.amount + row.vat_amount, 2)
                else:
                    row.vat_amount = 0.0

    # ------------------------------------------------------------ helpers

    @property
    def settle_sub(self):
        return {"Counterparty": self.counterparty, "Contract": self.contract, "SettlementDoc": (self.doctype, self.name)}

    @property
    def vat_payer(self):
        policy = self.accounting_policy
        if policy:
            return bool(policy.vat_payer)
        return bool(frappe.db.get_value("UA Organization", self.organization, "vat_payer"))

    def vat_name(self, percent):
        name = frappe.db.get_value("UA VAT Rate", {"rate": percent, "is_taxable": 1}, "name")
        if not name:
            frappe.throw(_("Не знайдено ставку ПДВ {0} %").format(percent))
        return name

    def item_sub(self, item, counterparty=None):
        return {"Item": item, "Counterparty": counterparty or self.counterparty}

    def need_off_balance(self, account, table=None):
        """Every item may not leave more than the counterparty has on the off-balance account."""
        wanted = {}
        for row in self.rows(table):
            wanted[row.item] = flt(wanted.get(row.item, 0) + flt(row.quantity), 3)
        for item, qty in wanted.items():
            have = off_balance_qty(self, account, item, self.counterparty, self.posting_date)
            if qty > have:
                frappe.throw(
                    _("Недостатньо {0} на рахунку {1} контрагента {2}: залишок {3}, потрібно {4}").format(
                        title_of("UA Item", item), account, title_of("UA Counterparty", self.counterparty), have, qty
                    )
                )

    def before_cancel(self):
        super().before_cancel()
        if not self.guard_cancel:
            return
        account, kind = self.guard_cancel
        self._ctx = {}
        keys = {(row.item, row.get("warehouse") or self.get("warehouse")) for row in self.rows()}
        for item, warehouse in keys:
            if kind == "off":
                lowest = running_minimum(self, account, item, "Counterparty", self.counterparty, (self.doctype, self.name))
            else:
                lowest = running_minimum(self, account, item, "Warehouse", warehouse, (self.doctype, self.name))
            if lowest < 0:
                frappe.throw(
                    _("Документ не можна скасувати: {0} з нього вже використано в наступних документах").format(
                        title_of("UA Item", item)
                    )
                )

    def off_credit(self, account, row, used):
        """Recorded value of the units that leave an off-balance account (average of what is there)."""
        key = (account, row.item, self.counterparty)
        if key not in used:
            used[key] = [*off_balance(self, account, row.item, self.counterparty, self.posting_date), 0.0, 0.0]
        bal_amount, bal_qty, taken_amount, taken_qty = used[key]
        left_qty = flt(bal_qty - taken_qty, 3)
        left_amount = flt(bal_amount - taken_amount, 2)
        qty = flt(row.quantity, 3)
        cost = left_amount if qty >= left_qty else flt(left_amount * qty / left_qty, 2)
        used[key][2] += cost
        used[key][3] += qty
        return cost

    def cost_account_of(self, item):
        stock = STOCK_ACCOUNT.get(self.item_info(item).item_type, "281")
        return COST_ACCOUNT.get(stock, COST_ACCOUNT_DEFAULT)


# ---------------------------------------------------------------- agent side


class UACommissionReceipt(PartyDocument):
    """Надходження товарів на комісію: off-balance Дт 024 at the agreed sale price."""

    doc_code = "KRC"
    stock_moves = False
    doc_title = "Надходження товарів на комісію"
    guard_cancel = (COMMISSION_AGENT_OFF, "off")

    def build(self):
        entries = []
        for row in self.goods:
            entries.append(
                self.entry(
                    COMMISSION_AGENT_OFF, None, row.amount, self.item_sub(row.item), None, quantity_dr=flt(row.quantity, 3)
                )
            )
        return entries, [], []


class UACommissionReturn(PartyDocument):
    """Повернення комітенту: off-balance Кт 024."""

    doc_code = "KRT"
    stock_moves = False
    doc_title = "Повернення товарів комітенту"

    def build(self):
        self.need_off_balance(COMMISSION_AGENT_OFF)
        used = {}
        return (
            [
                self.entry(
                    None,
                    COMMISSION_AGENT_OFF,
                    self.off_credit(COMMISSION_AGENT_OFF, row, used),
                    None,
                    self.item_sub(row.item),
                    quantity_cr=flt(row.quantity, 3),
                )
                for row in self.goods
            ],
            [],
            [],
        )


class CommissionReport(PartyDocument):
    """Common part of the two reports: fee and its VAT."""

    priced_tables = ("goods",)

    def validate(self):
        super().validate()
        for field in ("commission_rate", "commission_vat_rate"):
            if not 0 <= flt(self.get(field)) <= 100:
                frappe.throw(_("Відсоток має бути від 0 до 100"))

    def fee(self):
        """(fee without VAT, VAT of the fee) of the whole report."""
        base = flt(sum(row.amount for row in self.goods), 2)
        fee = flt(base * flt(self.commission_rate) / 100, 2)
        percent = flt(self.commission_vat_rate) if self.vat_payer else 0
        return fee, flt(fee * percent / 100, 2), percent


class UAPrincipalReport(CommissionReport):
    """Звіт комітенту (agent sold the goods of the principal).

    Dt 361 (buyer) Ct 685 (principal)   gross sale
    Ct 024 off the balance               goods leave the agent
    Dt 685 Ct 703                        fee of the agent with VAT (gross)
    Dt 703 Ct 641                        VAT of the fee
    """

    doc_code = "KPR"
    stock_moves = False
    doc_title = "Звіт комітенту"

    def validate(self):
        super().validate()
        if not self.buyer:
            frappe.throw(_("Вкажіть покупця"))
        self.check_contract(self.buyer, self.buyer_contract)

    def build(self):
        self.need_off_balance(COMMISSION_AGENT_OFF)
        entries, liabilities, used = [], [], {}
        buyer_sub = {"Counterparty": self.buyer, "Contract": self.buyer_contract, "SettlementDoc": (self.doctype, self.name)}
        for row in self.goods:
            entries.append(self.entry(SETTLE_CUSTOMER, SETTLE_PRINCIPAL, row.total, buyer_sub, self.settle_sub))
            entries.append(
                self.entry(
                    None,
                    COMMISSION_AGENT_OFF,
                    self.off_credit(COMMISSION_AGENT_OFF, row, used),
                    None,
                    self.item_sub(row.item),
                    quantity_cr=flt(row.quantity, 3),
                )
            )
        fee, fee_vat, percent = self.fee()
        tax_sub = {"TaxType": TAX_VAT}
        if fee:
            entries.append(self.entry(SETTLE_PRINCIPAL, "703", flt(fee + fee_vat, 2), self.settle_sub, {}))
        if fee_vat:
            entries.append(self.entry("703", "641", fee_vat, {}, tax_sub))
        if fee and percent:
            liabilities.append(self.vat_row(self.vat_name(percent), fee, fee_vat, EVENT_SHIPMENT))
        return entries, liabilities, []


class UACommissionTransfer(PartyDocument):
    """Передача на комісію (principal): Дт 283 Кт 281 at cost."""

    doc_code = "KTR"
    doc_title = "Передача товарів на комісію"
    guard_cancel = (COMMISSION_STOCK, "stock")

    def build(self):
        entries, used = [], {}
        for row in self.goods:
            stock = self.stock_account(row)
            cost = take_cost(self, row, stock, row.item, self.warehouse, row.quantity, used)
            qty = flt(row.quantity, 3)
            entries.append(
                self.entry(
                    COMMISSION_STOCK,
                    stock,
                    cost,
                    self.stock_sub(row.item, self.warehouse),
                    self.stock_sub(row.item, self.warehouse),
                    quantity_dr=qty,
                    quantity_cr=qty,
                )
            )
        return entries, [], []


class UACommissionAgentReport(CommissionReport):
    """Звіт комісіонера (principal books the sale).

    Dt 361 Ct 702 gross, Dt 704 Ct 641 VAT, Dt 902 Ct 283 cost of the goods given on commission,
    Dt 93 Ct 361 fee of the agent, Dt 644 Ct 361 VAT of the fee.
    """

    doc_code = "KAR"
    doc_title = "Звіт комісіонера"

    def build(self):
        entries, liabilities, credits, used, groups = [], [], [], {}, {}
        tax_sub = {"TaxType": TAX_VAT}
        cache = {}
        for row in self.goods:
            info = self.item_info(row.item)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}
            entries.append(
                self.entry(SETTLE_CUSTOMER, REVENUE_ACCOUNT.get(info.item_type, "702"), row.total, self.settle_sub, item_sub)
            )
            if row.vat_amount:
                entries.append(self.entry("704", "641", row.vat_amount, item_sub, tax_sub))
            cost = take_cost(self, row, COMMISSION_STOCK, row.item, self.warehouse, row.quantity, used)
            entries.append(
                self.entry(
                    self.cost_account_of(row.item),
                    COMMISSION_STOCK,
                    cost,
                    {"Item": row.item},
                    self.stock_sub(row.item, self.warehouse),
                    quantity_cr=flt(row.quantity, 3),
                )
            )
            percent, taxable = vat_info(row.vat_rate, cache)
            g = groups.setdefault(row.vat_rate or "", [0.0, 0.0, taxable])
            g[0] = flt(g[0] + row.amount, 2)
            g[1] = flt(g[1] + row.vat_amount, 2)
        for rate, (base, vat_amount, taxable) in groups.items():
            if taxable and rate:
                liabilities.append(self.vat_row(rate, base, vat_amount, EVENT_SHIPMENT))
        fee, fee_vat, percent = self.fee()
        if fee:
            entries.append(self.entry("93", SETTLE_CUSTOMER, fee, {}, self.settle_sub))
        if fee_vat:
            entries.append(self.entry("644", SETTLE_CUSTOMER, fee_vat, tax_sub, self.settle_sub))
        if fee and percent:
            credits.append(self.vat_row(self.vat_name(percent), fee, fee_vat, EVENT_SHIPMENT))
        return entries, liabilities, credits


# ---------------------------------------------------------------- tolling


class UATollingTransfer(PartyDocument):
    """Передача сировини в переробку: Дт 206 Кт 201 at cost."""

    doc_code = "TTR"
    doc_title = "Передача сировини в переробку"
    guard_cancel = (TOLLING_STOCK, "stock")

    def build(self):
        entries, used = [], {}
        for row in self.goods:
            stock = self.stock_account(row)
            cost = take_cost(self, row, stock, row.item, self.warehouse, row.quantity, used)
            qty = flt(row.quantity, 3)
            entries.append(
                self.entry(
                    TOLLING_STOCK,
                    stock,
                    cost,
                    self.stock_sub(row.item, self.warehouse),
                    self.stock_sub(row.item, self.warehouse),
                    quantity_dr=qty,
                    quantity_cr=qty,
                )
            )
        return entries, [], []


class TollingFeeDocument(PartyDocument):
    """Documents with products, materials used and a processing fee."""

    tables = ("products", "materials_used")

    def validate(self):
        super().validate()
        if not self.rows("products") or not self.rows("materials_used"):
            frappe.throw(_("Заповніть таблиці «Продукція» і «Витрачена сировина»"))
        if flt(self.processing_fee) < 0:
            frappe.throw(_("Вартість переробки не може бути від'ємною"))

    def fee_amounts(self):
        """(fee, VAT, VAT percent) of the processing."""
        fee = flt(self.processing_fee, 2)
        percent, taxable = vat_info(self.vat_rate, {})
        if not (taxable and self.vat_payer):
            percent = 0
        return fee, flt(fee * percent / 100, 2), percent


class UATollingReceipt(TollingFeeDocument):
    """Отримання з переробки (customer).

    Dt 26 Ct 206   raw materials used at cost
    Dt 26 Ct 631   processing fee
    Dt 644 Ct 631  VAT of the fee
    """

    doc_code = "TRC"
    doc_title = "Отримання продукції з переробки"

    def build(self):
        entries, credits, used = [], [], {}
        products = self.rows("products")
        total_qty = flt(sum(r.quantity for r in products), 3)
        fee, fee_vat, percent = self.fee_amounts()
        costs = [
            (row, take_cost(self, row, TOLLING_STOCK, row.item, self.warehouse, row.quantity, used))
            for row in self.rows("materials_used")
        ]
        # every product takes a share of the materials and of the fee by its quantity; the last one takes the rest
        rest_materials = [[cost, flt(row.quantity, 3)] for row, cost in costs]
        rest_fee = fee
        for i, prod in enumerate(products):
            last = i == len(products) - 1
            share = flt(prod.quantity) / total_qty if total_qty else 0
            stock = self.stock_account(prod)
            first = True
            for j, (row, cost) in enumerate(costs):
                part_cost = rest_materials[j][0] if last else flt(cost * share, 2)
                part_qty = rest_materials[j][1] if last else flt(row.quantity * share, 3)
                rest_materials[j][0] = flt(rest_materials[j][0] - part_cost, 2)
                rest_materials[j][1] = flt(rest_materials[j][1] - part_qty, 3)
                extra = {"quantity_dr": flt(prod.quantity, 3)} if first else {}
                first = False
                entries.append(
                    self.entry(
                        stock,
                        TOLLING_STOCK,
                        part_cost,
                        self.stock_sub(prod.item, self.warehouse),
                        self.stock_sub(row.item, self.warehouse),
                        quantity_cr=part_qty,
                        **extra,
                    )
                )
            part_fee = rest_fee if last else flt(fee * share, 2)
            rest_fee = flt(rest_fee - part_fee, 2)
            if part_fee:
                entries.append(
                    self.entry(stock, SETTLE_SUPPLIER, part_fee, self.stock_sub(prod.item, self.warehouse), self.settle_sub)
                )
        if fee_vat:
            entries.append(self.entry("644", SETTLE_SUPPLIER, fee_vat, {"TaxType": TAX_VAT}, self.settle_sub))
            credits.append(self.vat_row(self.vat_name(percent), fee, fee_vat, EVENT_SHIPMENT))
        return entries, [], credits


class UATollingIntake(PartyDocument):
    """Сировина, прийнята в переробку (processor): off-balance Дт 022."""

    doc_code = "TIN"
    stock_moves = False
    doc_title = "Сировина, прийнята в переробку"
    guard_cancel = (TOLLING_OFF, "off")

    def build(self):
        return (
            [
                self.entry(TOLLING_OFF, None, row.amount, self.item_sub(row.item), None, quantity_dr=flt(row.quantity, 3))
                for row in self.goods
            ],
            [],
            [],
        )


class UATollingOutput(TollingFeeDocument):
    """Передача готової продукції замовнику (processor).

    Dt 361 Ct 703   processing fee with VAT, Dt 704 Ct 641 VAT,
    Ct 022 off the balance: raw materials used.
    """

    doc_code = "TOU"
    stock_moves = False
    doc_title = "Передача готової продукції замовнику"

    def build(self):
        self.need_off_balance(TOLLING_OFF, "materials_used")
        entries, liabilities, used = [], [], {}
        for row in self.rows("materials_used"):
            entries.append(
                self.entry(
                    None,
                    TOLLING_OFF,
                    self.off_credit(TOLLING_OFF, row, used),
                    None,
                    self.item_sub(row.item),
                    quantity_cr=flt(row.quantity, 3),
                )
            )
        fee, fee_vat, percent = self.fee_amounts()
        if fee:
            entries.append(
                self.entry(SETTLE_CUSTOMER, "703", flt(fee + fee_vat, 2), self.settle_sub, {"VatRate": self.vat_rate})
            )
        if fee_vat:
            entries.append(self.entry("704", "641", fee_vat, {"VatRate": self.vat_rate}, {"TaxType": TAX_VAT}))
        if fee and percent:
            liabilities.append(self.vat_row(self.vat_rate, fee, fee_vat, EVENT_SHIPMENT))
        return entries, liabilities, []
