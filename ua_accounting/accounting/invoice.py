"""Invoice (Інвойс): one document for the whole sale of goods and services (T-533).

The Invoice is the UA Payment Invoice. Its events are the existing posting documents:
shipment = UA Sales Invoice, services = UA Service Act, return = UA Sales Return.
An event is linked to the Invoice by `invoice` and to the Invoice row by the line field `invoice_row`.
Each event is its own registrar. Payments stay in the finance documents (UA Cash Receipt with allocations,
UA Bank Statement lines): the Invoice only reads them from the ledger, by the settlement document
(UA Payment Invoice, name) on the accounts 361, 362 and 681.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import base_currency, slot_of

INVOICE = "UA Payment Invoice"
ADVANCE_ACCOUNT = "681"
SALE = "UA Sales Invoice"
ACT = "UA Service Act"
RETURN = "UA Sales Return"
CASH_IN = "UA Cash Receipt"
BANK = "UA Bank Statement"
PAYMENT_REGISTRARS = (CASH_IN, BANK, "UA Cash Payment")

# event doctype -> (table of the event, line doctype)
EVENT_TABLE = {SALE: ("goods", "UA Goods Line"), ACT: ("services", "UA Service Line"), RETURN: ("goods", "UA Goods Line")}
SHIPPING = (SALE, ACT)

COMMERCIAL = {0: "Чернетка", 1: "Підтверджено", 2: "Скасовано"}
NOT_FULFILLED, PARTLY_FULFILLED, FULFILLED = "Не виконано", "Частково виконано", "Виконано"
UNPAID, PARTLY_PAID, PAID = "Не оплачено", "Частково оплачено", "Оплачено"


# ---------------------------------------------------------------- quantities


def _sum_by_row(invoice, doctype, exclude=None, locking=False):
    """{invoice row: quantity, amount, vat, total} of the submitted events of one kind.

    `locking` reads the rows with FOR UPDATE: the latest committed rows, not the snapshot of the transaction
    (MariaDB REPEATABLE READ), so a shipment committed by a parallel request while this one waited for the
    lock of the Invoice is counted. The sums are made here, not in SQL (no FOR UPDATE with GROUP BY on PostgreSQL).
    """
    table, line = EVENT_TABLE[doctype]
    params = [doctype, table, invoice]
    extra = ""
    if exclude:
        extra = " and p.name != %s"
        params.append(exclude)
    suffix = " for update" if locking else ""
    result = {}
    for row, qty, amount, vat_amount, total in frappe.db.sql(
        f"""select r.invoice_row, r.quantity, r.amount, r.vat_amount, r.total
        from `tab{line}` r join `tab{doctype}` p on p.name = r.parent
        where r.parenttype = %s and r.parentfield = %s and p.invoice = %s and p.docstatus = 1
        and coalesce(r.invoice_row, '') != ''{extra}{suffix}""",
        params,
    ):
        item = result.setdefault(row, frappe._dict(quantity=0.0, amount=0.0, vat_amount=0.0, total=0.0))
        item.quantity = flt(item.quantity + flt(qty), 3)
        item.amount = flt(item.amount + flt(amount), 2)
        item.vat_amount = flt(item.vat_amount + flt(vat_amount), 2)
        item.total = flt(item.total + flt(total), 2)
    return result


def adjustments_of(inv):
    result = {}
    for row in inv.get("adjustments") or []:
        result[row.invoice_row] = flt(result.get(row.invoice_row, 0) + flt(row.quantity_delta), 3)
    return result


def effective_lines(inv, exclude=None, locking=False):
    """Rows of the Invoice with what was done: quantity, adjustments, shipped (or provided), returned, left.

    `exclude` is an event that is not counted (the document that is being checked). `locking` is for the
    checks made after the lock of the Invoice (see `_sum_by_row`).
    """
    shipped = {**_sum_by_row(inv.name, SALE, exclude, locking), **_sum_by_row(inv.name, ACT, exclude, locking)}
    returned = _sum_by_row(inv.name, RETURN, exclude, locking)
    adj = adjustments_of(inv)
    rows = []
    for table in ("goods", "services"):
        for row in inv.get(table) or []:
            done = flt(shipped.get(row.name, {}).get("quantity", 0), 3)
            back = flt(returned.get(row.name, {}).get("quantity", 0), 3)
            effective = flt(flt(row.quantity, 3) + adj.get(row.name, 0), 3)
            rows.append(
                frappe._dict(
                    row=row.name, table=table, item=row.item, item_name=row.item_name, quantity=flt(row.quantity, 3),
                    adjustment=adj.get(row.name, 0), effective=effective, shipped=done, returned=back,
                    left=flt(effective - (done - back), 3), source=row,
                )
            )
    return rows


def lock(name):
    """Serialises the events of one Invoice (the shipped quantity cannot be exceeded by parallel shipments)."""
    frappe.db.sql("select name from `tabUA Payment Invoice` where name = %s for update", name)


# ---------------------------------------------------------------- event mixin


class InvoiceEvent:
    """Mixin of UA Sales Invoice, UA Service Act and UA Sales Return. Does nothing when `invoice` is empty."""

    @property
    def settle_sub(self):
        from ua_accounting.accounting.documents import TradeDocument

        sub = TradeDocument.settle_sub.fget(self)
        if self.get("invoice"):
            sub["SettlementDoc"] = (INVOICE, self.invoice)
        return sub

    def _invoice_doc(self):
        if "_inv" not in self.__dict__:
            self._inv = frappe.get_doc(INVOICE, self.invoice)
        return self._inv

    def validate(self):
        super().validate()
        if not self.get("event_key"):
            self.event_key = None  # the unique index allows many empty keys, not many empty strings
        self.check_invoice()

    def check_invoice(self):
        if not self.get("invoice"):
            return
        inv = self._invoice_doc()
        if inv.docstatus != 1:
            frappe.throw(_("Інвойс {0} не підтверджений").format(inv.name))
        for field in ("organization", "counterparty", "contract", "currency", "vat_mode"):
            if self.get(field) != inv.get(field):
                frappe.throw(_("Поле «{0}» має збігатися з інвойсом {1}").format(self.meta.get_label(field), inv.name))
        if self.doctype == RETURN and frappe.db.get_value(SALE, self.sales_invoice, "invoice") != inv.name:
            frappe.throw(_("Реалізація {0} не належить інвойсу {1}").format(self.sales_invoice, inv.name))
        if self.doctype == SALE and self.get("services"):
            frappe.throw(_("Послуги за інвойсом надають актом виконаних робіт, а не відвантаженням"))
        own = {r.name: r for t in ("goods", "services") for r in inv.get(t) or []}
        for row, kind in self.lines():
            src = own.get(row.get("invoice_row"))
            if not src or (kind == "goods") != (src.parentfield == "goods"):
                frappe.throw(_("Рядок {0}: має відповідати рядку інвойсу {1}").format(row.idx, inv.name))
            if (
                src.item != row.item
                or abs(flt(src.price) - flt(row.price)) > 0.005
                or abs(flt(src.get("discount_percent")) - flt(row.get("discount_percent"))) > 0.005
                or (src.vat_rate or None) != (row.vat_rate or None)
            ):
                frappe.throw(_("Рядок {0}: номенклатура, ціна, знижка і ставка ПДВ мають збігатися з інвойсом {1}").format(row.idx, inv.name))
        if self.doctype in SHIPPING:
            self.check_limit()

    def check_limit(self, locking=False):
        """Shipped (provided) minus returned per Invoice row cannot exceed the row quantity plus its adjustments."""
        inv = self._invoice_doc()
        asked = {}
        for row, _kind in self.lines():
            asked[row.invoice_row] = flt(asked.get(row.invoice_row, 0) + flt(row.quantity), 3)
        for line in effective_lines(inv, exclude=self.name, locking=locking):
            qty = asked.get(line.row)
            if qty and qty > line.left:
                frappe.throw(
                    _("Номенклатура {0}: кількість {1} перевищує залишок {2} за інвойсом {3}: потрібне коригування інвойсу").format(
                        line.item_name or line.item, qty, max(line.left, 0), inv.name
                    )
                )

    def before_submit(self):
        if self.get("invoice") and self.doctype in SHIPPING:
            lock(self.invoice)
            self.check_limit(locking=True)

    def calculate(self):
        super().calculate()
        if self.get("invoice") and self.doctype in SHIPPING:
            self.fit_last_part()

    def fit_last_part(self):
        """The part that completes an Invoice row takes the remainder of its sums: all parts add up to the Invoice."""
        inv = self._invoice_doc()
        if not inv.docstatus == 1 or adjustments_of(inv):
            return
        done = _sum_by_row(inv.name, self.doctype, exclude=self.name)
        own = {r.name: r for t in ("goods", "services") for r in inv.get(t) or []}
        per_row = {}
        for row, _kind in self.lines():
            per_row.setdefault(row.get("invoice_row"), []).append(row)
        changed = False
        for name, rows in per_row.items():
            src, before = own.get(name), done.get(name)
            if not src or not before or len(rows) != 1:
                continue
            row = rows[0]
            if flt(before.quantity + flt(row.quantity), 3) == flt(src.quantity, 3):
                row.amount = flt(src.amount - before.amount, 2)
                row.vat_amount = flt(src.vat_amount - before.vat_amount, 2)
                row.total = flt(src.total - before.total, 2)
                changed = True
        if changed:
            net = vat_total = gross = base_total = 0.0
            for row, _kind in self.lines():
                net += row.total - row.vat_amount
                vat_total += row.vat_amount
                gross += row.total
                base_total += self.uah(row.total - row.vat_amount) + self.uah(row.vat_amount)
            self.total_net, self.vat_total = flt(net, 2), flt(vat_total, 2)
            self.total_amount, self.base_total = flt(gross, 2), flt(base_total, 2)

    def invoice_advance(self, gross_total, settle):
        """Entries that use advances for this event: those of this Invoice first, then free ones if allowed.

        Returns (applied amount, entries). Advances linked to other Invoices are not taken.
        """
        balances = advance_balances(self.organization, self.counterparty, self.contract, self.posting_date, self._ctx)
        linked = min(max(balances["linked"].get(self.invoice, 0), 0), gross_total)
        free = 0.0
        if self.get("offset_advance"):
            free = min(max(balances["free"], 0), flt(gross_total - linked, 2))
        entries = []
        cur = lambda amount: flt(amount / (flt(self.exchange_rate) or 1), 2)
        if linked > 0:
            entries.append(
                self.entry(ADVANCE_ACCOUNT, settle, linked, self.settle_sub, self.settle_sub, cur_amount=cur(linked))
            )
        if free > 0:
            entries.append(
                self.entry(
                    ADVANCE_ACCOUNT, settle, free,
                    {"Counterparty": self.counterparty, "Contract": self.contract}, self.settle_sub,
                    cur_amount=cur(free),
                )
            )
        return flt(linked + free, 2), entries

    def on_submit(self):
        super().on_submit()
        if self.get("invoice"):
            refresh(self.invoice)

    def on_cancel(self):
        super().on_cancel()
        if self.get("invoice"):
            refresh(self.invoice)


def add_event_key_index(doctype):
    # PostgreSQL keeps the names of unique indexes in one namespace for the whole schema: one name per table.
    # MariaDB keeps the old name, so a site that has the index does not get a second one.
    name = f"unique_event_key_{frappe.scrub(doctype)}" if frappe.db.db_type == "postgres" else None
    frappe.db.add_unique(doctype, ["event_key"], constraint_name=name)


# ---------------------------------------------------------------- payments


def _entry_sum(account, side, slot, invoice, extra="", params=()):
    return flt(
        frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where account_{side} = %s and subconto_{side}{slot} = %s and subconto_{side}{slot}_type = %s{extra}""",
            (account, invoice, INVOICE, *params),
        )[0][0],
        2,
    )


def invoice_paid(inv):
    """Paid amount in the currency of the Invoice, from the ledger rows of the settlement document (plan 4.1)."""
    ctx = {}
    marks = ", ".join(["%s"] * len(PAYMENT_REGISTRARS))
    total = 0.0
    for account in ("361", "362", ADVANCE_ACCOUNT):
        slot = slot_of(account, "SettlementDoc", ctx)
        if not slot:
            continue
        for side, sign in (("cr", 1), ("dr", -1)):
            total += sign * _entry_sum(
                account, side, slot, inv.name, f" and registrar_type in ({marks})", PAYMENT_REGISTRARS
            )
    # free advances used by an event of this Invoice (Dt 681 without this Invoice, Ct 361 of this Invoice)
    adv_slot = slot_of(ADVANCE_ACCOUNT, "SettlementDoc", ctx)
    for account in ("361", "362"):
        slot = slot_of(account, "SettlementDoc", ctx)
        if slot and adv_slot:
            total += _entry_sum(
                account, "cr", slot, inv.name,
                f" and registrar_type in (%s, %s) and account_dr = %s and subconto_dr{adv_slot} != %s",
                (SALE, ACT, ADVANCE_ACCOUNT, inv.name),
            )
    rate = flt(inv.exchange_rate) or 1
    return flt(total / rate, 2) if inv.currency != base_currency() else flt(total, 2)


def settlement_debt(account, invoice, date, ctx):
    """Debit minus credit of an account for one Invoice, on the end of `date` (base currency)."""
    slot = slot_of(account, "SettlementDoc", ctx)
    if not slot:
        return 0.0
    total = 0.0
    for side, sign in (("dr", 1), ("cr", -1)):
        total += sign * _entry_sum(account, side, slot, invoice, " and posting_date <= %s", (getdate(date),))
    return flt(total, 2)


def advance_balances(organization, counterparty, contract, date, ctx):
    """{"linked": {invoice: balance}, "free": balance} of the advances 681 of a contract on the end of `date`."""
    slot = slot_of(ADVANCE_ACCOUNT, "SettlementDoc", ctx)
    cp, ct = slot_of(ADVANCE_ACCOUNT, "Counterparty", ctx), slot_of(ADVANCE_ACCOUNT, "Contract", ctx)
    result = {"linked": {}, "free": 0.0}
    if not (slot and cp):
        return result
    for side, sign in (("cr", 1), ("dr", -1)):
        where = f"organization = %s and account_{side} = %s and posting_date <= %s and subconto_{side}{cp} = %s"
        params = [organization, ADVANCE_ACCOUNT, getdate(date), counterparty or ""]
        if ct:
            where += f" and subconto_{side}{ct} = %s"
            params.append(contract or "")
        for invoice, amount in frappe.db.sql(
            f"""select subconto_{side}{slot}, sum(amount) from `tabUA Accounting Entry`
            where {where} and subconto_{side}{slot}_type = %s group by subconto_{side}{slot}""",
            (*params, INVOICE),
        ):
            result["linked"][invoice] = flt(result["linked"].get(invoice, 0) + sign * flt(amount), 2)
        (free,) = frappe.db.sql(
            f"""select coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where {where} and subconto_{side}{slot}_type != %s""",
            (*params, INVOICE),
        )[0]
        result["free"] = flt(result["free"] + sign * flt(free), 2)
    return result


# ---------------------------------------------------------------- states


def effective_total(inv):
    adj = adjustments_of(inv)
    total = 0.0
    for table in ("goods", "services"):
        for row in inv.get(table) or []:
            qty = flt(row.quantity, 3)
            eff = max(flt(qty + adj.get(row.name, 0), 3), 0)
            total += flt(flt(row.total) * eff / qty, 2) if qty else 0
    return flt(total, 2)


def fulfilment_state(lines):
    active = [l for l in lines if l.effective > 0]
    net = sum(l.shipped - l.returned for l in active)
    if net <= 0:
        return NOT_FULFILLED
    return FULFILLED if all(l.left <= 0 for l in active) else PARTLY_FULFILLED


def payment_state(paid, total):
    if paid <= 0:
        return UNPAID
    return PAID if paid >= total else PARTLY_PAID


def states(inv):
    """The four independent states of the Invoice and the derived amounts."""
    lines = effective_lines(inv)
    total = effective_total(inv)
    paid = invoice_paid(inv) if inv.docstatus == 1 else 0.0
    fulfilled = 0.0
    for doctype, sign in ((SALE, 1), (ACT, 1), (RETURN, -1)):
        value = frappe.db.sql(
            f"select coalesce(sum(total_amount), 0) from `tab{doctype}` where invoice = %s and docstatus = 1", inv.name
        )[0][0]
        fulfilled += sign * flt(value)
    return {
        "commercial_status": COMMERCIAL.get(inv.docstatus, "Чернетка"),
        "fulfilment_status": fulfilment_state(lines) if inv.docstatus == 1 else "",
        "payment_status": payment_state(paid, total) if inv.docstatus == 1 else "",
        "effective_total": total,
        "fulfilled_amount": flt(fulfilled, 2),
        "paid_amount": paid,
        "debt_amount": flt(total - paid, 2) if inv.docstatus == 1 else 0.0,
    }


def refresh(name):
    """Recompute the derived states and amounts of an Invoice (after an event, a payment or an adjustment)."""
    if not name or not frappe.db.exists(INVOICE, name):
        return
    inv = frappe.get_doc(INVOICE, name)
    frappe.db.set_value(INVOICE, name, states(inv), update_modified=False)


def refresh_many(names):
    for name in {n for n in names if n}:
        refresh(name)
