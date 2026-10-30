"""Production: specifications, planned prices, shift report, month closing of account 23, own work act.

Shift report:   Дт 23 Кт 20x   materials at the moving average cost
                Дт 26/25 Кт 23 output at the planned price
Month closing:  Дт 23 Кт 911/912   overheads
                Дт 26/25 Кт 23     actual cost minus planned cost of the output (storno when negative)
                Дт 901 Кт 26       the part of the difference that belongs to the sold output
Own work act:   Дт 361 Кт 703, Дт 703 Кт 641, Дт 903 Кт 23 at the planned cost
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_last_day, getdate

from ua_accounting.accounting.documents import (
    EVENT_SHIPMENT,
    STOCK_ACCOUNT,
    TYPE_SERVICE,
    AccountingDocument,
    TradeDocument,
    VAT_NONE,
)
from ua_accounting.accounting.stock import take_cost
from ua_accounting.accounting.utils import first_of_month, title_of

MATERIAL_KIND = "Матеріальні затрати"
OUTPUT_ACCOUNTS = ("26", "25")
BASE_QUANTITY = "Кількість"


# ---------------------------------------------------------------- helpers


def planned_price_of(organization, item, date):
    """Planned price in force on the date: the row with the latest `date_from` not after the date."""
    rows = frappe.get_all(
        "UA Planned Price",
        filters={"organization": organization, "item": item, "date_from": ("<=", getdate(date))},
        fields=["price"],
        order_by="date_from desc, creation desc",
        limit=1,
    )
    return flt(rows[0].price, 2) if rows else None


def material_expense_item():
    """Expense item «Матеріальні затрати» of the 23 subconto: the first one with this kind, else a new one."""
    name = frappe.db.get_value("UA Expense Item", {"expense_kind": MATERIAL_KIND}, "name", order_by="creation asc")
    if name:
        return name
    doc = frappe.get_doc({"doctype": "UA Expense Item", "item_name": MATERIAL_KIND, "expense_kind": MATERIAL_KIND})
    doc.insert(ignore_permissions=True)
    return doc.name


def spread(total, weights):
    """Split `total` by the weights to kopecks. The last part takes the rest."""
    weight_sum = sum(weights)
    parts, rest = [], flt(total, 2)
    for n, w in enumerate(weights):
        if n == len(weights) - 1:
            part = rest
        elif weight_sum:
            part = flt(total * w / weight_sum, 2)
        else:
            part = 0.0
        parts.append(part)
        rest = flt(rest - part, 2)
    return parts


def closed_month(organization, date):
    """Submitted closing that covers the date (same month, closing date not before it)."""
    return frappe.db.get_value(
        "UA Production Month Closing",
        {
            "organization": organization,
            "docstatus": 1,
            "posting_date": (">=", getdate(date)),
        },
        ["name", "posting_date"],
        as_dict=True,
        order_by="posting_date asc",
    )


def check_month_open(organization, date):
    closing = closed_month(organization, date)
    if closing and first_of_month(closing.posting_date) <= first_of_month(date):
        frappe.throw(_("Виробничий місяць закрито документом {0}").format(closing.name))


# ---------------------------------------------------------------- catalogs


class UAItemSpecification(Document):
    def validate(self):
        if flt(self.quantity) <= 0:
            frappe.throw(_("Кількість виробу має бути більше нуля"))
        if not self.components:
            frappe.throw(_("Заповніть склад специфікації"))
        for row in self.components:
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
            if row.item == self.item:
                frappe.throw(_("Рядок {0}: виріб не може входити до власної специфікації").format(row.idx))
            info = frappe.db.get_value("UA Item", row.item, ["item_type", "is_group"], as_dict=True)
            if not info or info.is_group or info.item_type == TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: {1} не є запасом").format(row.idx, title_of("UA Item", row.item)))

    def on_update(self):
        if self.is_default:
            frappe.db.sql(
                "update `tabUA Item Specification` set is_default = 0 where item = %s and name != %s",
                (self.item, self.name),
            )


class UAPlannedPrice(Document):
    def validate(self):
        if flt(self.price) <= 0:
            frappe.throw(_("Планова ціна має бути більше нуля"))


# ---------------------------------------------------------------- shift report


class UAProductionReport(AccountingDocument):
    """Звіт виробництва за зміну."""

    doc_code = "PR"
    doc_title = "Звіт виробництва за зміну"

    def validate(self):
        super().validate()
        self.check_stores()
        if not self.products:
            frappe.throw(_("Заповніть таблицю «Продукція»"))
        check_month_open(self.organization, self.posting_date)
        specs = {}
        for row in self.products:
            self.check_product(row, specs)
        if not self.materials:
            self.fill_materials(specs)
        for row in self.materials:
            self.check_material(row)
        self.calculate()

    def before_cancel(self):
        super().before_cancel()
        check_month_open(self.organization, self.posting_date)

    # ------------------------------------------------------------ validation

    def check_stores(self):
        if self.output_account not in OUTPUT_ACCOUNTS:
            frappe.throw(_("Рахунок випуску має бути 26 або 25"))
        for field in ("warehouse", "output_warehouse"):
            org = frappe.db.get_value("UA Warehouse", self.get(field), "organization")
            if org != self.organization:
                frappe.throw(_("Вкажіть склад організації"))

    def check_product(self, row, specs):
        info = frappe.db.get_value("UA Item", row.item, ["item_type", "is_group"], as_dict=True)
        if not info or info.is_group or info.item_type == TYPE_SERVICE:
            frappe.throw(_("Рядок {0}: {1} не є продукцією").format(row.idx, title_of("UA Item", row.item)))
        if flt(row.quantity) <= 0:
            frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
        if row.specification:
            spec_item = frappe.db.get_value("UA Item Specification", row.specification, "item")
            if spec_item != row.item:
                frappe.throw(_("Рядок {0}: специфікація належить іншій номенклатурі").format(row.idx))
        else:
            row.specification = frappe.db.get_value(
                "UA Item Specification", {"item": row.item, "is_default": 1}, "name"
            ) or frappe.db.get_value("UA Item Specification", {"item": row.item}, "name", order_by="creation asc")
        if row.specification and row.specification not in specs:
            specs[row.specification] = frappe.get_doc("UA Item Specification", row.specification)
        if not flt(row.planned_price):
            row.planned_price = planned_price_of(self.organization, row.item, self.posting_date)
        if flt(row.planned_price) <= 0:
            frappe.throw(
                _("Рядок {0}: для {1} не встановлено планову ціну на {2}").format(
                    row.idx, title_of("UA Item", row.item), getdate(self.posting_date).strftime("%d.%m.%Y")
                )
            )

    def fill_materials(self, specs):
        """Norm of the specifications: component quantity × (product quantity / specification quantity)."""
        need = {}
        for row in self.products:
            spec = specs.get(row.specification)
            if not spec:
                frappe.throw(
                    _("Рядок {0}: для {1} немає специфікації, заповніть таблицю «Матеріали»").format(
                        row.idx, title_of("UA Item", row.item)
                    )
                )
            for comp in spec.components:
                need[comp.item] = need.get(comp.item, 0) + flt(comp.quantity) * flt(row.quantity) / flt(spec.quantity)
        for item, qty in need.items():
            self.append("materials", {"item": item, "quantity": flt(qty, 3), "warehouse": self.warehouse})

    def check_material(self, row):
        info = frappe.db.get_value("UA Item", row.item, ["item_type", "is_group"], as_dict=True)
        if not info or info.is_group or info.item_type not in STOCK_ACCOUNT:
            frappe.throw(_("Рядок {0}: {1} не є запасом").format(row.idx, title_of("UA Item", row.item)))
        if flt(row.quantity) <= 0:
            frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
        row.warehouse = row.warehouse or self.warehouse
        org = frappe.db.get_value("UA Warehouse", row.warehouse, "organization")
        if org != self.organization:
            frappe.throw(_("Рядок {0}: склад належить іншій організації").format(row.idx))

    def calculate(self):
        for row in self.products:
            row.amount = flt(flt(row.quantity) * flt(row.planned_price), 2)
        self.total_output = flt(sum(r.amount for r in self.products), 2)

    # ------------------------------------------------------------ posting

    def materials_cost(self):
        """[(row, stock account, cost)] at the moving average cost on the posting date."""
        used, result = {}, []
        for row in self.materials:
            account = STOCK_ACCOUNT[frappe.db.get_value("UA Item", row.item, "item_type")]
            result.append((row, account, take_cost(self, row, account, row.item, row.warehouse, row.quantity, used)))
        return result

    def before_submit(self):
        self.materials_cost_rows = self.materials_cost()
        for row, _account, cost in self.materials_cost_rows:
            row.amount = cost
        self.total_materials = flt(sum(c for _r, _a, c in self.materials_cost_rows), 2)

    def build(self):
        expense = material_expense_item()
        cost_sub = {"ExpenseItem": expense, "Department": self.department}
        entries = []
        for row, account, cost in self.materials_cost():
            entries.append(
                self.entry(
                    "23",
                    account,
                    cost,
                    cost_sub,
                    {"Item": row.item, "Warehouse": row.warehouse},
                    quantity_cr=flt(row.quantity, 3),
                )
            )
        for row in self.products:
            entries.append(
                self.entry(
                    self.output_account,
                    "23",
                    row.amount,
                    {"Item": row.item, "Warehouse": self.output_warehouse},
                    cost_sub,
                    quantity_dr=flt(row.quantity, 3),
                )
            )
        return entries, [], []


# ---------------------------------------------------------------- month closing


def month_outputs(organization, first, end):
    """Output lines of the shift reports of the month with the materials spent by the same report.

    Returns a list of dicts: report, department, account, item, warehouse, quantity, planned, materials.
    """
    lines = frappe.db.sql(
        """select e.registrar as report, r.department, e.account_dr as account, e.subconto_dr1 as item,
        e.subconto_dr2 as warehouse, sum(e.quantity_dr) as quantity, sum(e.amount) as planned
        from `tabUA Accounting Entry` e join `tabUA Production Report` r on r.name = e.registrar
        where e.registrar_type = 'UA Production Report' and e.organization = %s and e.posting_date between %s and %s
        and e.account_dr in ('26', '25') and e.account_cr = '23'
        group by e.registrar, r.department, e.account_dr, e.subconto_dr1, e.subconto_dr2
        order by e.registrar, e.subconto_dr1""",
        (organization, first, end),
        as_dict=True,
    )
    spent = dict(
        frappe.db.sql(
            """select registrar, sum(amount) from `tabUA Accounting Entry`
            where registrar_type = 'UA Production Report' and organization = %s and posting_date between %s and %s
            and account_dr = '23' group by registrar""",
            (organization, first, end),
        )
    )
    by_report = {}
    for line in lines:
        by_report.setdefault(line.report, []).append(line)
    for report, rows in by_report.items():
        parts = spread(flt(spent.get(report)), [flt(r.planned) for r in rows])
        for row, part in zip(rows, parts, strict=True):
            row.materials = part
    return lines


def sold_quantities(organization, first, end):
    """{(item, warehouse): quantity of finished goods sold in the month} (cost of sales 90x minus returns)."""
    sold = {}
    for side, sign in (("cr", 1), ("dr", -1)):
        other = "account_dr" if side == "cr" else "account_cr"
        rows = frappe.db.sql(
            f"""select subconto_{side}1, subconto_{side}2, sum(quantity_{side}) from `tabUA Accounting Entry`
            where organization = %s and posting_date between %s and %s and account_{side} = '26'
            and {other} like '90%%' group by subconto_{side}1, subconto_{side}2""",
            (organization, first, end),
        )
        for item, warehouse, qty in rows:
            sold[(item, warehouse)] = sold.get((item, warehouse), 0) + sign * flt(qty)
    return sold


def sold_by_group(products, sold):
    """Sold pieces of every output group (same order as `products`): a list of (warehouse, quantity).

    A group takes the sales from its own warehouse first. What is left (the output was moved to
    another warehouse before the sale) goes to the groups of the same item that still have quantity.
    """
    parts = [[] for _g in products]
    left = {k: max(v, 0) for k, v in sold.items()}
    taken = [0.0] * len(products)
    for n, g in enumerate(products):
        if g.account == "26":
            key = (g.item, g.warehouse)
            take = min(left.get(key, 0), flt(g.quantity))
            if take > 0:
                parts[n].append((g.warehouse, take))
                taken[n] = take
            left[key] = flt(left.get(key, 0) - take, 3)
    for n, g in enumerate(products):
        if g.account != "26":
            continue
        rest = flt(g.quantity - taken[n], 3)
        for key in left:
            if rest <= 0:
                break
            if key[0] == g.item and left[key] > 0:
                take = min(left[key], rest)
                parts[n].append((key[1], take))
                left[key] = flt(left[key] - take, 3)
                rest = flt(rest - take, 3)
    return parts


def stock_quantities(organization, end):
    """{(item, warehouse): quantity of finished goods (26) in stock at the end date}."""
    stock = {}
    for side, sign in (("dr", 1), ("cr", -1)):
        rows = frappe.db.sql(
            f"""select subconto_{side}1, subconto_{side}2, sum(quantity_{side}) from `tabUA Accounting Entry`
            where organization = %s and posting_date <= %s and account_{side} = '26'
            group by subconto_{side}1, subconto_{side}2""",
            (organization, end),
        )
        for item, warehouse, qty in rows:
            stock[(item, warehouse)] = stock.get((item, warehouse), 0) + sign * flt(qty)
    return stock


def unsold_by_group(products, parts, stock):
    """Where the unsold part of every output group lies: a list of (warehouse, quantity) per group.

    The own warehouse is used first, then the other warehouses of the item that still hold stock.
    What stock cannot cover stays at the output warehouse.
    """
    left = {k: max(v, 0) for k, v in stock.items()}
    result = [[] for _g in products]
    for n, g in enumerate(products):
        if g.account != "26":
            continue
        rest = flt(g.quantity - sum(q for _w, q in parts[n]), 3)
        keys = [(g.item, g.warehouse)] + [k for k in left if k[0] == g.item and k[1] != g.warehouse]
        for key in keys:
            if rest <= 0:
                break
            take = min(left.get(key, 0), rest)
            if take > 0:
                result[n].append((key[1], take))
                left[key] = flt(left[key] - take, 3)
                rest = flt(rest - take, 3)
        if rest > 0:
            result[n].append((g.warehouse, rest))
    return result


class UAProductionMonthClosing(AccountingDocument):
    """Закриття місяця (виробництво): overheads 91 → 23 and actual cost of the output."""

    doc_code = "PMC"
    doc_title = "Закриття місяця (виробництво)"

    def validate(self):
        super().validate()
        if getdate(self.posting_date) != get_last_day(self.posting_date):
            frappe.throw(_("Закриття виконують на останній день місяця"))
        other = frappe.get_all(
            "UA Production Month Closing",
            filters={
                "organization": self.organization,
                "docstatus": 1,
                "name": ("!=", self.name or ""),
                "posting_date": ("between", [first_of_month(self.posting_date), self.posting_date]),
            },
            pluck="name",
        )
        if other:
            frappe.throw(_("Місяць уже закрито документом {0}").format(other[0]))
        self._entries = self.plan()

    def build(self):
        entries = self.__dict__.pop("_entries", None) or self.plan()
        return entries, [], []

    def plan(self):
        """Fill the table and return the entries."""
        from ua_accounting.accounting.month_closing import balances, money

        org = self.organization
        end = getdate(self.posting_date)
        first = first_of_month(end)
        lines = month_outputs(org, first, end)
        if not lines:
            frappe.throw(_("За місяць немає випуску продукції"))
        expense = material_expense_item()
        entries = []

        # 23 balance by (expense item, department)
        key_balance = {}
        for b in balances(org, end, ["23"]):
            key = (b["subs"][0][1], b["subs"][1][1])
            key_balance[key] = money(key_balance.get(key, 0) + b["amount"])

        # overheads 911 / 912 to 23: the whole balance
        overhead = 0.0
        for b in balances(org, end, ["911", "912"]):
            amount = b["amount"]
            if not amount:
                continue
            key = (b["subs"][0][1], b["subs"][1][1])
            subs = {"ExpenseItem": key[0], "Department": key[1]}
            if amount > 0:
                entries.append(self.entry("23", b["account"], amount, subs, subs))
            else:
                entries.append(self.entry(b["account"], "23", -amount, subs, subs))
            key_balance[key] = money(key_balance.get(key, 0) + amount)
            overhead = money(overhead + amount)

        # products of the month
        groups = {}
        for line in lines:
            key = (line.account, line.item, line.warehouse, line.department)
            g = groups.setdefault(
                key,
                frappe._dict(
                    account=line.account,
                    item=line.item,
                    warehouse=line.warehouse,
                    department=line.department,
                    quantity=0.0,
                    planned=0.0,
                    materials=0.0,
                ),
            )
            g.quantity = flt(g.quantity + flt(line.quantity), 3)
            g.planned = money(g.planned + flt(line.planned))
            g.materials = money(g.materials + flt(line.materials))
        products = list(groups.values())

        planned_total = money(sum(g.planned for g in products))
        materials_total = money(sum(g.materials for g in products))
        balance = money(sum(key_balance.values()))
        # all that is left on 23 after the planned output and the planned cost of the services
        # goes to the cost of the output
        deviation_total = balance
        other_direct = money(planned_total + deviation_total - materials_total - overhead)

        if self.distribution_base == BASE_QUANTITY:
            weights = [flt(g.quantity) for g in products]
        else:
            weights = [flt(g.planned) for g in products]
        shares = spread(overhead, weights)
        other = spread(other_direct, weights)

        sold_parts = sold_by_group(products, sold_quantities(org, first, end))
        unsold_parts = unsold_by_group(products, sold_parts, stock_quantities(org, end))
        self.set("products", [])
        total_deviation = 0.0
        for g, share, direct, sold_pieces, unsold_pieces in zip(
            products, shares, other, sold_parts, unsold_parts, strict=True
        ):
            actual = money(g.materials + direct + share)
            deviation = money(actual - g.planned)
            total_deviation = money(total_deviation + deviation)
            self.append(
                "products",
                {
                    "item": g.item,
                    "quantity": g.quantity,
                    "planned_cost": g.planned,
                    "overhead_share": share,
                    "actual_cost": actual,
                    "deviation": deviation,
                    "output_account": g.account,
                    "warehouse": g.warehouse,
                    "department": g.department,
                },
            )
            if not deviation:
                continue
            cost_sub = {"ExpenseItem": expense, "Department": g.department}
            pieces = sold_pieces if g.account == "26" else []
            posted = 0.0
            for warehouse, qty in pieces:
                sold_amount = money(deviation * qty / flt(g.quantity))
                if not sold_amount:
                    continue
                sub = {"Item": g.item, "Warehouse": warehouse}
                entries.append(self.adjust(g.account, "23", sold_amount, sub, cost_sub))
                entries.append(self.adjust("901", "26", sold_amount, {"Item": g.item}, sub))
                posted = money(posted + sold_amount)
            rest = money(deviation - posted)
            if rest:
                # the unsold deviation follows the units to the warehouses where they lie
                unsold = unsold_pieces or [(g.warehouse, g.quantity)]
                total_qty = sum(q for _w, q in unsold)
                left_amount = rest
                for i, (warehouse, qty) in enumerate(unsold):
                    amount = left_amount if i == len(unsold) - 1 else money(rest * qty / total_qty)
                    left_amount = money(left_amount - amount)
                    if amount:
                        sub = {"Item": g.item, "Warehouse": warehouse}
                        entries.append(self.adjust(g.account, "23", amount, sub, cost_sub))
            key_balance[(expense, g.department)] = money(key_balance.get((expense, g.department), 0) - deviation)
        self.total_overhead = overhead
        self.total_deviation = total_deviation

        # what is left on 23 by other subconto goes to the first product's key: all of 23 ends at zero
        target_key = (expense, products[0].department)
        target = {"ExpenseItem": target_key[0], "Department": target_key[1]}
        for key, amount in key_balance.items():
            if key == target_key or not amount:
                continue
            subs = {"ExpenseItem": key[0], "Department": key[1]}
            if amount > 0:
                entries.append(self.entry("23", "23", amount, target, subs))
            else:
                entries.append(self.entry("23", "23", -amount, subs, target))
        return entries

    def adjust(self, account_dr, account_cr, amount, dr_sub, cr_sub):
        """Entry for a signed difference: a negative amount is a storno (accounts swapped)."""
        if amount > 0:
            return self.entry(account_dr, account_cr, amount, dr_sub, cr_sub)
        return self.entry(account_cr, account_dr, -amount, cr_sub, dr_sub)


# ---------------------------------------------------------------- own work act


class UAOwnWorkAct(TradeDocument):
    """Акт про виконання робіт власного виробництва.

    Дт 361 Кт 703   revenue (with VAT)
    Дт 703 Кт 641   VAT liability
    Дт 903 Кт 23    cost at the planned cost of the unit
    """

    doc_code = "OWA"
    doc_title = "Акт про виконання робіт власного виробництва"

    def validate(self):
        super().validate()
        org = frappe.db.get_value("UA Department", self.department, "organization")
        if org and org != self.organization:
            frappe.throw(_("Підрозділ належить іншій організації"))
        for row in self.services:
            if flt(row.planned_cost) < 0:
                frappe.throw(_("Рядок {0}: планова собівартість не може бути від'ємною").format(row.idx))

    def build(self):
        settle = "362" if self.is_foreign else "361"
        expense = material_expense_item()
        entries, liabilities, groups = [], [], {}
        for row, _kind in self.lines():
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}
            entries.append(self.entry(settle, "703", gross, self.settle_sub, item_sub, cur_amount=row.total))
            if vat_amount:
                entries.append(
                    self.entry("703", "641", vat_amount, item_sub, {"TaxType": "VAT"})
                )
            cost = flt(flt(row.planned_cost) * flt(row.quantity), 2)
            if cost:
                entries.append(
                    self.entry(
                        "903",
                        "23",
                        cost,
                        {"Item": row.item},
                        {"ExpenseItem": row.expense_item or expense, "Department": self.department},
                    )
                )
        if self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                if g["taxable"] and (g["vat"] > 0 or g["net"] > 0):
                    liabilities.append(self.vat_row(key, g["net"], g["vat"], EVENT_SHIPMENT))
        return entries, liabilities, []
