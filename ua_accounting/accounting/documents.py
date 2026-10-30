"""Base classes and helpers of the accounting documents (UA Documents module).

A posting document builds its entries in `build()` and returns three lists:
accounting entries, VAT liabilities and VAT credits. The base class writes
them with the posting API on submit and removes them on cancel.
"""

import re

import frappe
from frappe import _
from frappe.beeone import numbering
from frappe.model.document import Document
from frappe.utils import flt, getdate

from ua_accounting.accounting import ledger, vat
from ua_accounting.accounting.utils import first_of_month, title_of
from ua_accounting.accounting_policy import policy_for

VAT_ON_TOP = "ПДВ зверху"
VAT_INCLUDED = "ПДВ у сумі"
VAT_NONE = "Без ПДВ"

TAX_VAT = "VAT"  # UA Tax Type of the VAT

TYPE_GOODS = "Товар"
TYPE_SERVICE = "Послуга"
TYPE_MATERIAL = "Матеріал"
TYPE_PRODUCT = "Продукція"

# stock account, revenue account and cost account by the item type
STOCK_ACCOUNT = {TYPE_GOODS: "281", TYPE_MATERIAL: "201", TYPE_PRODUCT: "26"}
REVENUE_ACCOUNT = {TYPE_GOODS: "702", TYPE_MATERIAL: "712", TYPE_PRODUCT: "701", TYPE_SERVICE: "703"}
COST_ACCOUNT = {"281": "902", "26": "901"}
COST_ACCOUNT_DEFAULT = "943"
EXPENSE_ACCOUNT = "92"

EVENT_SHIPMENT = "Відвантаження"
EVENT_PAYMENT = "Оплата"

# documents that can be asked for "Результат проведення"
POSTING_MODULE = "UA Documents"


# ---------------------------------------------------------------- numbering


def make_doc_name(doc, date=None):
    """Number like 1C: prefix of the organization, document code, year, counter.

    The names come from the numbering of the core. The counters keep their old keys, so the
    numbers go on without a break.
    """
    setting = frappe.db.get_value("UA Numbering Setting", {"organization": doc.get("organization"),
                                "ref_doctype": doc.doctype}, ["prefix", "digits", "reset_yearly"], as_dict=True)
    if setting:
        year = getdate(doc.get("posting_date")).strftime("%Y")
        return numbering.next_name(
            setting.prefix, int(setting.digits), scope=doc.organization, scope_chars=6,
            reset="Yearly" if setting.reset_yearly else "Never", date=doc.get("posting_date"),
            key=f"UA:{doc.organization}:{doc.doctype}:{year if setting.reset_yearly else 'all'}")
    prefix = ""
    if doc.get("organization"):
        prefix = frappe.db.get_value("UA Organization", doc.organization, "doc_prefix") or ""
    prefix = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]", "", prefix) or "UA"
    year = getdate(date or doc.get("posting_date")).strftime("%y")
    head = f"{prefix}-{doc.doc_code}-{year}"
    return numbering.next_name(head, 5, key=f"{head}-")


# ---------------------------------------------------------------- helpers


def base_currency():
    return frappe.db.get_value("UA Currency", {"is_base": 1}, "name") or "UAH"


def vat_info(vat_rate, cache):
    """(percent, is_taxable) of a UA VAT Rate."""
    if not vat_rate:
        return 0.0, False
    if vat_rate not in cache:
        row = frappe.db.get_value("UA VAT Rate", vat_rate, ["rate", "is_taxable"], as_dict=True)
        cache[vat_rate] = (flt(row.rate), bool(row.is_taxable)) if row else (0.0, False)
    return cache[vat_rate]


def calc_line(quantity, price, percent, mode, discount=0):
    """Return (amount, vat_amount, total) of one table row. The discount is in percent."""
    amount = flt(flt(quantity) * flt(price), 2)
    if discount:
        amount = flt(amount * (100 - flt(discount)) / 100, 2)
    if mode == VAT_NONE or not percent:
        return amount, 0.0, amount
    if mode == VAT_INCLUDED:
        vat_amount = flt(amount * percent / (100 + percent), 2)
        return amount, vat_amount, amount
    vat_amount = flt(amount * percent / 100, 2)
    return amount, vat_amount, flt(amount + vat_amount, 2)


def allocate_advance(groups, applied, mode):
    """Spread an advance over the VAT rate groups of a document.

    `groups` is {rate: {"gross", "percent", "taxable"}}. Returns
    {rate: (gross part, VAT part)}. The VAT part is the VAT that was already
    recorded when the advance was paid (first event rule).
    """
    gross_total = sum(g["gross"] for g in groups.values())
    result = {}
    rest = flt(applied, 2)
    keys = list(groups)
    for i, key in enumerate(keys):
        g = groups[key]
        if i == len(keys) - 1:
            part = rest
        else:
            part = flt(applied * g["gross"] / gross_total, 2) if gross_total else 0
        part = min(max(part, 0), g["gross"], rest)
        rest = flt(rest - part, 2)
        vat_part = 0.0
        if mode != VAT_NONE and g["taxable"] and g["percent"]:
            vat_part = flt(part * g["percent"] / (100 + g["percent"]), 2)
        result[key] = (part, vat_part)
    return result


def slot_of(account, subconto_type, ctx):
    """Slot number (1..3) of a subconto type in the account, or None."""
    acc = ledger._account(account, ctx)
    for idx, row in enumerate(acc.subconto, start=1):
        if row.subconto_type == subconto_type and not row.turnover_only:
            return idx
    return None


def subconto_for(account, available, ctx):
    """Keep only the subconto that the account has. Empty values are dropped."""
    acc = ledger._account(account, ctx)
    types = {row.subconto_type for row in acc.subconto}
    return {k: v for k, v in available.items() if k in types and v}


def settlement_balance(organization, account, counterparty, contract, side, date, ctx):
    """Balance of a settlement account (681, 371...) by counterparty and contract.

    side "cr": credit minus debit (advances received). side "dr": the opposite.
    Months up to the month of `date` are taken from the totals.
    """
    cp_slot = slot_of(account, "Counterparty", ctx)
    ct_slot = slot_of(account, "Contract", ctx)
    if not cp_slot:
        return 0.0
    sql = (
        "select coalesce(sum(debit), 0), coalesce(sum(credit), 0) from `tabUA Account Turnover` "
        "where organization = %s and account = %s and period <= %s and "
        f"subconto{cp_slot} = %s"
    )
    values = [organization, account, first_of_month(date), counterparty or ""]
    if ct_slot:
        sql += f" and subconto{ct_slot} = %s"
        values.append(contract or "")
    debit, credit = frappe.db.sql(sql, values)[0]
    return flt(credit - debit if side == "cr" else debit - credit, 2)


def stock_balance(organization, account, item, warehouse, date, ctx, lock=False):
    """(amount, quantity) of an item in a warehouse on the end of `date`.

    Totals of the months before the month of `date` plus entries of the
    month up to `date`. This is what the average cost is made from.
    `lock` reads with FOR UPDATE: the latest committed rows, locked until the commit,
    so two parallel submits cannot take the same stock.
    """
    it = slot_of(account, "Item", ctx)
    wh = slot_of(account, "Warehouse", ctx)
    if not it or not wh:
        return 0.0, 0.0
    first = first_of_month(date)
    suffix = " for update" if lock else ""
    amount, qty = frappe.db.sql(
        f"""select coalesce(sum(debit - credit), 0), coalesce(sum(quantity_dr - quantity_cr), 0)
        from `tabUA Account Turnover`
        where organization = %s and account = %s and period < %s
        and subconto{it} = %s and subconto{wh} = %s{suffix}""",
        (organization, account, first, item, warehouse),
    )[0]
    for side in ("dr", "cr"):
        sign = 1 if side == "dr" else -1
        e_amount, e_qty = frappe.db.sql(
            f"""select coalesce(sum(amount), 0), coalesce(sum(quantity_{side}), 0)
            from `tabUA Accounting Entry`
            where organization = %s and account_{side} = %s
            and posting_date >= %s and posting_date <= %s
            and subconto_{side}{it} = %s and subconto_{side}{wh} = %s{suffix}""",
            (organization, account, first, getdate(date), item, warehouse),
        )[0]
        amount += sign * e_amount
        qty += sign * e_qty
    return flt(amount, 2), flt(qty, 3)


# ---------------------------------------------------------------- base class


class AccountingDocument(Document):
    """Base of the posting documents."""

    doc_code = ""
    doc_title = ""
    posts = True  # False for orders: no entries

    def autoname(self):
        self.name = make_doc_name(self)

    def validate(self):
        self._ctx = {}
        self.check_organization()
        self.zero_empty_numbers()

    def zero_empty_numbers(self):
        """An empty number in a table row is 0. Else the version history shows "from 0 to null"."""
        for table in self.meta.get_table_fields():
            for row in self.get(table.fieldname) or []:
                for df in row.meta.fields:
                    if df.fieldtype in ("Float", "Currency", "Int") and row.get(df.fieldname) is None:
                        row.set(df.fieldname, 0)

    def check_organization(self):
        if self.organization and not frappe.db.exists("UA Organization", self.organization):
            frappe.throw(_("Організацію {0} не знайдено").format(self.organization))

    @property
    def accounting_policy(self):
        if "_accounting_policy" not in self.__dict__:
            self._accounting_policy = policy_for(self.organization, self.posting_date)
        return self._accounting_policy

    def on_submit(self):
        if self.posts:
            self.post_document()

    def before_cancel(self):
        from ua_accounting.accounting import tax

        tax.check_cancel_allowed(self)

    def on_cancel(self):
        if self.posts:
            ledger.cancel_entries(self)

    def post_document(self):
        self._ctx = {}
        entries, liabilities, credits = self.build()
        entries = [e for e in entries if flt(e.get("amount")) or e.get("quantity_dr") or e.get("quantity_cr")]
        if not entries:
            frappe.throw(_("Документ не створює жодної проводки"))
        ledger.post_entries(self, entries)
        vat.post_vat_entries(self, liabilities, credits)

    def build(self):
        """Return (entries, vat liabilities, vat credits)."""
        raise NotImplementedError

    # ------------------------------------------------------------ builders

    def entry(self, dr, cr, amount, dr_sub=None, cr_sub=None, **extra):
        """One accounting entry. Subconto not used by the account is dropped."""
        e = {
            "account_dr": dr,
            "account_cr": cr,
            "amount": flt(amount, 2),
            "subconto_dr": subconto_for(dr, dr_sub or {}, self._ctx) if dr else {},
            "subconto_cr": subconto_for(cr, cr_sub or {}, self._ctx) if cr else {},
            "content": self.content_text(),
        }
        cur = self.get("currency")
        cur_amount = extra.pop("cur_amount", 0)
        if cur and cur != base_currency():
            # the ledger uses these only for currency accounts
            e.update(
                currency_dr=cur,
                currency_cr=cur,
                currency_amount_dr=flt(cur_amount, 2),
                currency_amount_cr=flt(cur_amount, 2),
            )
        e.update(extra)
        return e

    def content_text(self):
        return f"{self.doc_title} {self.name}"[:140]

    def vat_row(self, vat_rate, base, vat_amount, event, **extra):
        row = {
            "counterparty": self.get("counterparty"),
            "contract": self.get("contract"),
            "settlement_doc_type": self.doctype,
            "settlement_doc": self.name,
            "vat_rate": vat_rate,
            "event": event,
            "base_amount": flt(base, 2),
            "vat_amount": flt(vat_amount, 2),
            "content": self.content_text(),
        }
        row.update(extra)
        return row


# ---------------------------------------------------------------- trade documents


class TradeDocument(AccountingDocument):
    """Orders, sale and receipt: header, tables Товари and Послуги, VAT totals."""

    goods_table = "goods"
    service_table = "services"

    def validate(self):
        super().validate()
        self.check_counterparty()
        self.set_vat_mode()
        self.set_exchange_rate()
        self.validate_lines()
        self.calculate()

    # ------------------------------------------------------------ validation

    def check_counterparty(self):
        if not self.contract:
            return
        contract = frappe.db.get_value(
            "UA Counterparty Contract",
            self.contract,
            ["counterparty", "organization"],
            as_dict=True,
        )
        if not contract or contract.counterparty != self.counterparty:
            frappe.throw(
                _("Договір {0} не належить контрагенту {1}").format(
                    title_of("UA Counterparty Contract", self.contract), title_of("UA Counterparty", self.counterparty)
                )
            )
        if contract.organization != self.organization:
            frappe.throw(_("Договір {0} укладено з іншою організацією").format(title_of("UA Counterparty Contract", self.contract)))

    def set_vat_mode(self):
        policy = self.accounting_policy
        if policy and not policy.vat_payer:
            self.vat_mode = VAT_NONE
            return
        if not self.vat_mode:
            payer = policy.vat_payer if policy else frappe.db.get_value("UA Organization", self.organization, "vat_payer")
            self.vat_mode = VAT_ON_TOP if payer else VAT_NONE

    def set_exchange_rate(self):
        if not self.currency:
            self.currency = base_currency()
        if self.currency == base_currency():
            self.exchange_rate = 1
        elif not flt(self.exchange_rate) or (self.is_new() and flt(self.exchange_rate) == 1):
            # 1 is the field default: for a foreign currency it is not a real rate
            from ua_accounting.ua_catalogs.doctype.ua_currency.ua_currency import get_rate

            self.exchange_rate = get_rate(self.currency, self.posting_date)
        if not flt(self.exchange_rate):
            frappe.throw(_("Не задано курс валюти {0} на {1}").format(self.currency, self.posting_date))

    def lines(self):
        """Rows of both tables as (row, "goods" | "services")."""
        for row in self.get(self.goods_table) or []:
            yield row, "goods"
        for row in self.get(self.service_table) or []:
            yield row, "services"

    def item_info(self, item):
        cache = self.__dict__.setdefault("_items", {})
        if item not in cache:
            cache[item] = frappe.db.get_value(
                "UA Item",
                item,
                ["item_name", "item_type", "uom", "vat_rate", "is_group"],
                as_dict=True,
            ) or frappe._dict()
        return cache[item]

    def validate_lines(self):
        if not any(True for _row in self.lines()):
            frappe.throw(_("Заповніть табличну частину «Товари» або «Послуги»"))
        for row, kind in self.lines():
            info = self.item_info(row.item)
            if not info:
                frappe.throw(_("Рядок {0}: номенклатуру {1} не знайдено").format(row.idx, title_of("UA Item", row.item)))
            if info.is_group:
                frappe.throw(_("Рядок {0}: {1} є групою номенклатури").format(row.idx, title_of("UA Item", row.item)))
            if kind == "goods" and info.item_type == TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: послугу {1} вказують у закладці «Послуги»").format(row.idx, title_of("UA Item", row.item)))
            if kind == "services" and info.item_type != TYPE_SERVICE:
                frappe.throw(_("Рядок {0}: {1} не є послугою").format(row.idx, title_of("UA Item", row.item)))
            if flt(row.quantity) <= 0:
                frappe.throw(_("Рядок {0}: кількість має бути більше нуля").format(row.idx))
            row.item_name = info.item_name
            row.uom = row.uom or info.uom
            row.vat_rate = row.vat_rate or info.vat_rate
            if not 0 <= flt(row.get("discount_percent")) <= 100:
                frappe.throw(_("Рядок {0}: знижка має бути від 0 до 100 %").format(row.idx))
            self.fill_price(row)
            if row.account:
                self.check_account(row)

    def fill_price(self, row):
        """A row without a price takes it from the price type of the document (Типи цін)."""
        price_type = self.get("price_type")
        if not price_type or flt(row.price):
            return
        from ua_accounting.ua_documents.pricing import price_of

        type_currency = frappe.db.get_value("UA Price Type", price_type, "currency")
        if type_currency and type_currency != (self.currency or base_currency()):
            frappe.throw(
                _("Тип цін {0} у валюті {1}, а документ у валюті {2}").format(
                    title_of("UA Price Type", price_type), type_currency, self.currency or base_currency()
                )
            )
        price = price_of(row.item, price_type, self.posting_date)
        if price is None:
            frappe.throw(
                _("Рядок {0}: для {1} не встановлено ціну типу {2} на {3}").format(
                    row.idx,
                    row.item_name or title_of("UA Item", row.item),
                    title_of("UA Price Type", price_type),
                    getdate(self.posting_date).strftime("%d.%m.%Y"),
                )
            )
        row.price = price

    def take_basis_terms(self, source_doctype, source_name):
        """A return keeps the terms of its basis: contract, currency, VAT mode, VAT rate and price.

        The contract and the prices must match the basis (empty ones are filled), currency and VAT mode are copied.
        """
        source = frappe.db.get_value(
            source_doctype, source_name, ["contract", "currency", "vat_mode"], as_dict=True
        )
        if not source:
            return
        if self.contract and self.contract != source.contract:
            frappe.throw(_("Повернення має повторювати договір документа-підстави {0}").format(source_name))
        # currency and VAT mode have defaults on the form: they are always taken from the basis
        self.contract = source.contract
        self.currency = source.currency
        self.vat_mode = source.vat_mode
        terms = {}
        for r in frappe.get_all(
            "UA Goods Line",
            filters={"parent": source_name, "parenttype": source_doctype, "parentfield": "goods"},
            fields=["item", "quantity", "price", "discount_percent", "vat_rate"],
            order_by="idx",
        ):
            terms.setdefault(r.item, []).append(r)
        left = {}  # (item, vat rate, price) -> source quantity still free for this document
        link = "sales_invoice" if source_doctype == "UA Sales Invoice" else "purchase_receipt"
        others = frappe.get_all(
            self.doctype, filters={link: source_name, "docstatus": 1, "name": ("!=", self.name or "")}, pluck="name"
        )
        taken = {}  # the same key -> quantity of the other submitted returns
        for r in frappe.get_all(
            "UA Goods Line",
            filters={"parent": ("in", others or [""]), "parenttype": self.doctype, "parentfield": "goods"},
            fields=["item", "quantity", "price", "discount_percent", "vat_rate"],
        ):
            k = (r.item, r.vat_rate or None, flt(flt(r.price) * (100 - flt(r.discount_percent)) / 100, 2))
            taken[k] = flt(taken.get(k, 0) + flt(r.quantity), 3)
        for row in self.get(self.goods_table) or []:
            options = terms.get(row.item)
            if not options:
                continue
            ident = lambda o: (o.vat_rate or None, flt(flt(o.price) * (100 - flt(o.discount_percent)) / 100, 2))
            if flt(row.price):
                own = flt(flt(row.price) * (100 - flt(row.get("discount_percent"))) / 100, 2)
                options = [o for o in options if abs(ident(o)[1] - own) <= 0.01]
                if not options:
                    frappe.throw(_("Рядок {0}: ціна {1} не збігається з ціною документа-підстави").format(row.idx, own))
            if row.vat_rate:
                options = [o for o in options if (o.vat_rate or None) == row.vat_rate]
                if not options:
                    frappe.throw(_("Рядок {0}: ставка ПДВ має збігатися з документом-підставою").format(row.idx))
            if len({ident(o) for o in options}) > 1:
                frappe.throw(
                    _("Рядок {0}: у документі-підставі різні ціни або ставки ПДВ цієї номенклатури, вкажіть їх у рядку").format(
                        row.idx
                    )
                )
            src = options[0]
            key = (row.item, *ident(src))
            if key not in left:
                left[key] = flt(sum(o.quantity for o in options if ident(o) == ident(src)) - taken.get(key, 0), 3)
            left[key] = flt(left[key] - flt(row.quantity), 3)
            if left[key] < 0:
                frappe.throw(_("Рядок {0}: кількість перевищує кількість за цією ціною в документі-підставі").format(row.idx))
            row.vat_rate = src.vat_rate
            if not flt(row.price):
                row.price = src.price
                row.discount_percent = src.discount_percent

    def check_account(self, row):
        acc = frappe.db.get_value("UA Account", row.account, ["is_group", "off_balance"], as_dict=True)
        if not acc or acc.is_group or acc.off_balance:
            frappe.throw(_("Рядок {0}: рахунок {1} не підходить для обліку").format(row.idx, row.account))

    # ------------------------------------------------------------ totals

    def calculate(self):
        cache = {}
        net = vat_total = gross = base_total = 0.0
        rate = flt(self.exchange_rate) or 1
        for row, _kind in self.lines():
            percent, taxable = vat_info(row.vat_rate, cache)
            if not taxable:
                percent = 0
            row.amount, row.vat_amount, row.total = calc_line(
                row.quantity, row.price, percent, self.vat_mode, row.get("discount_percent")
            )
            net += row.total - row.vat_amount
            vat_total += row.vat_amount
            gross += row.total
            base_total += self.uah(row.total - row.vat_amount) + self.uah(row.vat_amount)
        self.total_net = flt(net, 2)
        self.vat_total = flt(vat_total, 2)
        self.total_amount = flt(gross, 2)
        self.base_total = flt(base_total, 2)

    def uah(self, amount):
        return flt(flt(amount) * (flt(self.exchange_rate) or 1), 2)

    def row_amounts(self, row):
        """(net, vat, gross) of a row in UAH."""
        net = self.uah(row.total - row.vat_amount)
        vat_amount = self.uah(row.vat_amount)
        return net, vat_amount, flt(net + vat_amount, 2)

    def add_group(self, groups, row, net, vat_amount, gross):
        percent, taxable = vat_info(row.vat_rate, self.__dict__.setdefault("_vat_cache", {}))
        g = groups.setdefault(
            row.vat_rate or "",
            {"net": 0.0, "vat": 0.0, "gross": 0.0, "percent": percent, "taxable": taxable},
        )
        g["net"] = flt(g["net"] + net, 2)
        g["vat"] = flt(g["vat"] + vat_amount, 2)
        g["gross"] = flt(g["gross"] + gross, 2)

    # ------------------------------------------------------------ subconto

    @property
    def settle_sub(self):
        return {
            "Counterparty": self.counterparty,
            "Contract": self.contract,
            "SettlementDoc": (self.doctype, self.name),
        }

    @property
    def is_foreign(self):
        return self.currency != base_currency()


HEADER_COPY = ("organization", "counterparty", "contract", "warehouse", "currency", "vat_mode")
LINE_SKIP = ("amount", "vat_amount", "total")


def fill_cash_side(doc):
    """Default bank account (or cash desk) of the organization in a new cash document."""
    filters = {"organization": doc.organization}
    if doc.currency:
        filters["currency"] = doc.currency
    bank = frappe.get_all(
        "UA Bank Account", filters=filters, pluck="name", order_by="is_default desc, creation asc", limit=1
    )
    if bank:
        doc.cash_type, doc.bank_account = "Банк", bank[0]
        return
    desk = frappe.get_all("UA Cash Desk", filters=filters, pluck="name", order_by="creation asc", limit=1)
    if desk:
        doc.cash_type, doc.cash_desk = "Каса", desk[0]


def new_from_basis(source, doctype, link_field=None, copy_lines=True):
    """Unsaved new document filled from a submitted basis document."""
    if source.docstatus != 1:
        frappe.throw(_("Документ-підстава {0} не проведений").format(source.name))
    target = frappe.new_doc(doctype)
    for field in HEADER_COPY:
        if source.meta.has_field(field) and target.meta.has_field(field):
            target.set(field, source.get(field))
    if link_field:
        target.set(link_field, source.name)
    if copy_lines:
        for table in ("goods", "services"):
            fields = {
                df.fieldname
                for df in frappe.get_meta(target.meta.get_field(table).options).fields
                if df.fieldname not in LINE_SKIP and df.fieldtype not in ("Section Break", "Column Break")
            }
            for row in source.get(table) or []:
                target.append(table, {k: v for k, v in row.as_dict().items() if k in fields and v is not None})
    return target


# ---------------------------------------------------------------- show entries


@frappe.whitelist()
def get_posting_result(doctype, name):
    """Entries and VAT rows of a document for the button "Результат проведення"."""
    if frappe.get_meta(doctype).module != POSTING_MODULE:
        frappe.throw(_("Недопустимий тип документа"), frappe.PermissionError)
    frappe.has_permission(doctype, "read", name, throw=True)

    titles = {}

    def title(doctype_, value):
        if not value:
            return ""
        key = (doctype_, value)
        if key not in titles:
            field = frappe.get_meta(doctype_).title_field if doctype_ else None
            text = frappe.db.get_value(doctype_, value, field) if field else None
            titles[key] = text or value
        return titles[key]

    accounts = {}

    def account_title(code):
        if not code:
            return ""
        if code not in accounts:
            accounts[code] = f"{code} {frappe.db.get_value('UA Account', code, 'account_name') or ''}".strip()
        return accounts[code]

    filters = {"registrar_type": doctype, "registrar": name}
    entries = []
    for e in frappe.get_all("UA Accounting Entry", filters=filters, fields=["*"], order_by="line_no asc"):
        row = {
            "line_no": e.line_no,
            "account_dr": account_title(e.account_dr),
            "account_cr": account_title(e.account_cr),
            "amount": e.amount,
            "quantity_dr": e.quantity_dr,
            "quantity_cr": e.quantity_cr,
            "currency_dr": e.currency_dr,
            "currency_amount_dr": e.currency_amount_dr,
            "currency_cr": e.currency_cr,
            "currency_amount_cr": e.currency_amount_cr,
            "content": e.content,
        }
        for side in ("dr", "cr"):
            row[f"subconto_{side}"] = [
                title(e.get(f"subconto_{side}{i}_type"), e.get(f"subconto_{side}{i}"))
                for i in (1, 2, 3)
                if e.get(f"subconto_{side}{i}")
            ]
        entries.append(row)

    fields = ["line_no", "vat_rate", "event", "base_amount", "vat_amount", "counterparty"]
    vat_rows = {}
    for key, register in (("liability", vat.LIABILITY), ("credit", vat.CREDIT)):
        rows = frappe.get_all(register, filters=filters, fields=fields, order_by="line_no asc")
        for r in rows:
            r["counterparty"] = title("UA Counterparty", r.counterparty)
            r["vat_rate"] = title("UA VAT Rate", r.vat_rate)
        vat_rows[key] = rows
    return {"entries": entries, "vat": vat_rows}


@frappe.whitelist()
def get_account_subconto(account):
    """Subconto types of an account (for the manual operation form)."""
    frappe.has_permission("UA Account", "read", throw=True)
    rows = frappe.db.sql(
        """select s.subconto_type, t.subconto_name, t.reference_doctype, t.is_dynamic
        from `tabUA Account Subconto` s
        left join `tabUA Subconto Type` t on t.name = s.subconto_type
        where s.parent = %s and s.parenttype = 'UA Account' order by s.idx""",
        account,
        as_dict=True,
    )
    return rows
