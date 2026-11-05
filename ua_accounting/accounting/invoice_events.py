"""Events of an Invoice: shipment, service provision, return (T-705).

There is no document of the sale. An event is a row of the Invoice (child table `events`) with its own number, date,
warehouse, status and lines (`event_lines`). The Invoice is the registrar of the movements of all its events, and the
event number is the part of the record sets (`registrar_part`). An event is posted, cancelled and reposted alone:
the other events of the Invoice keep their rows.

The rows of `events` and `event_lines` are added only here (the api actions set `flags.invoice_action`). A posted event is
never edited, it is cancelled: its status becomes «Скасовано», the row, the lines and the reason stay in the history.

Movements of an event:
    shipment   Dt 361 Ct 70x revenue; Dt 704 Ct 641 VAT (Ct 643 for the part taken at the advance, first event rule);
               Dt 90x Ct 281 cost; Dt 681 Ct 361 offset of the advance; packaging Dt 361 Ct 284
    services   the same without stock
    return     Dt 70x Ct 361; Dt 641 Ct 704; Dt 281 Ct 90x at the cost of the returned shipment lines
"""

import re

import frappe
from frappe import _
from frappe.beeone import numbering, sequences
from frappe.beeone.registers.posting import Moment, check_period_lock
from frappe.utils import flt, get_datetime, getdate, now_datetime, nowdate

from ua_accounting.accounting import invoice as inv_logic
from ua_accounting.accounting import ledger, packaging, stock, tax, vat
from ua_accounting.accounting.documents import (
    COST_ACCOUNT,
    COST_ACCOUNT_DEFAULT,
    EVENT_SHIPMENT,
    REVENUE_ACCOUNT,
    STOCK_ACCOUNT,
    TAX_VAT,
    TYPE_SERVICE,
    VAT_NONE,
    EntryBuilder,
    allocate_advance,
    calc_line,
    vat_info,
)
from ua_accounting.accounting.invoice import (
    ADVANCE_ACCOUNT,
    CANCELLED,
    INVOICE,
    KIND_RETURN,
    KIND_SERVICES,
    KIND_SHIPMENT,
    POSTED,
    SHIPPING,
)
from ua_accounting.accounting.retail import is_retail
from ua_accounting.accounting.stock import take_cost
from ua_accounting.accounting_policy import policy_for

VAT_ACCOUNT = "641"
VAT_PREPAID_ACCOUNT = "643"
VAT_DEDUCTION_ACCOUNT = "704"
LINE_FIELDS = ("item", "item_name", "uom", "price", "discount_percent", "vat_rate", "account")
CODE = {KIND_SHIPMENT: "VN", KIND_SERVICES: "AKT", KIND_RETURN: "PVR"}


# ---------------------------------------------------------------- numbers, lookups


def event_number(inv, kind, date):
    """Number of the primary document of an event: prefix of the organization, kind, year, counter."""
    prefix = frappe.db.get_value("UA Organization", inv.organization, "doc_prefix") or ""
    prefix = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]", "", prefix) or "UA"
    head = f"{prefix}-{CODE[kind]}-{getdate(date).strftime('%y')}"
    return numbering.next_name(head, 5, key=f"{head}-")


def get_event(inv, number):
    for event in inv.get("events") or []:
        if event.number == number:
            return event
    frappe.throw(_("Подію {0} не знайдено в інвойсі {1}").format(number, inv.name))


def lines_of(inv, event):
    number = event.number if hasattr(event, "number") else event
    return [l for l in inv.get("event_lines") or [] if l.event == number]


def event_by_key(inv, event_key):
    if not event_key:
        return None
    return next((e for e in inv.get("events") or [] if e.event_key == event_key), None)


def moment_of(inv, event):
    return Moment(getdate(event.posting_date), 0, get_datetime(event.moment), inv.name)


def returns_of(inv, event):
    return [
        e
        for e in inv.get("events") or []
        if e.kind == KIND_RETURN and e.return_of == event.number and e.status == POSTED
    ]


def check_lock(inv, date):
    """The date of an event cannot be in a closed period (the lock date of the organization or a Period Lock)."""
    from ua_accounting.administration import check_lock_dates

    check_lock_dates([(inv.organization, date)])
    check_period_lock(
        frappe._dict(doctype=INVOICE, name=inv.name, organization=inv.organization, posting_date=date, creation=inv.creation)
    )


# ---------------------------------------------------------------- the registrar of an event


class EventPoster(EntryBuilder):
    """The registrar context of one event: the Invoice is the registrar, the event number is the part.

    It has the attributes the posting API reads from a document (doctype, name, organization, posting_date, get) and
    the builders of the entries (EntryBuilder), as the documents of the accounting have.
    """

    def __init__(self, inv, event):
        self.inv = inv
        self.event = event
        self.doctype = INVOICE
        self.name = inv.name
        self.part = event.number
        self.number = event.number
        self.doc_title = event.kind
        self.kind = event.kind
        self.creation = inv.creation
        self.organization = inv.organization
        self.counterparty = inv.counterparty
        self.contract = inv.contract
        self.currency = inv.currency
        self.exchange_rate = inv.exchange_rate
        self.vat_mode = inv.vat_mode
        self.posting_date = getdate(event.posting_date)
        self.warehouse = event.warehouse
        self.offset_advance = event.offset_advance
        self.all_lines = lines_of(inv, event)
        self.packaging = [l for l in self.all_lines if l.line_type == "packaging"]
        self._ctx = {}

    def get(self, key, default=None):
        value = self.__dict__.get(key)
        return default if value is None else value

    @property
    def accounting_policy(self):
        if "_accounting_policy" not in self.__dict__:
            self._accounting_policy = policy_for(self.organization, self.posting_date)
        return self._accounting_policy

    def content_text(self):
        return f"{self.kind} № {self.number} (інвойс {self.name})"[:140]

    def lines(self):
        """The goods and services rows of the event as (row, "goods" | "services")."""
        for row in self.all_lines:
            if row.line_type in ("goods", "services"):
                yield row, row.line_type

    # ------------------------------------------------------------ builders

    def build(self):
        """(accounting entries, VAT liabilities, VAT credits) of the event."""
        if self.kind == KIND_RETURN:
            return self.build_return()
        return self.build_shipping()

    def build_shipping(self):
        settle = "362" if self.is_foreign else "361"
        entries, liabilities = [], []
        groups = {}
        used = {}  # stock already taken by this event: key -> [amount, quantity]
        vat_lines = []  # (rate group, VAT amount, subconto) of the rows

        for row, kind in self.lines():
            info = self.item_info(row.item)
            net, vat_amount, gross = self.row_amounts(row)
            self.add_group(groups, row, net, vat_amount, gross)
            item_sub = {"Item": row.item, "VatRate": row.vat_rate}
            entries.append(
                self.entry(
                    settle,
                    REVENUE_ACCOUNT.get(info.item_type, "702" if kind == "goods" else "703"),
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

        alloc = {}
        gross_total = sum(g["gross"] for g in groups.values())
        applied = 0.0
        if gross_total:
            applied, advance_entries = self.invoice_advance(gross_total, settle)
            entries.extend(advance_entries)
        if applied > 0:
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
        stock_account = row.account or STOCK_ACCOUNT[info.item_type]
        warehouse = row.warehouse or self.warehouse
        qty = flt(row.quantity, 3)
        cost = take_cost(self, row, stock_account, row.item, warehouse, qty, used)
        row.cost = cost
        return self.entry(
            COST_ACCOUNT.get(stock_account, COST_ACCOUNT_DEFAULT),
            stock_account,
            cost,
            {"Item": row.item, "ExpenseItem": None},
            {"Item": row.item, "Warehouse": warehouse},
            quantity_cr=qty,
            content=_("Собівартість {0}").format(self.number)[:140],
        )

    def invoice_advance(self, gross_total, settle):
        """Entries that use advances for this event: those of this Invoice first, then free ones if allowed.

        Returns (applied amount, entries). Advances linked to other Invoices are not taken.
        """
        balances = inv_logic.advance_balances(
            self.organization, self.counterparty, self.contract, self.posting_date, self._ctx
        )
        linked = min(max(balances["linked"].get(self.name, 0), 0), gross_total)
        free = 0.0
        if self.offset_advance:
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
                    ADVANCE_ACCOUNT,
                    settle,
                    free,
                    {"Counterparty": self.counterparty, "Contract": self.contract},
                    self.settle_sub,
                    cur_amount=cur(free),
                )
            )
        return flt(linked + free, 2), entries

    def build_return(self):
        settle = "362" if self.is_foreign else "361"
        entries, registers = [], []
        groups = {}
        tax_sub = {"TaxType": TAX_VAT}
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
            if row.line_type == "goods" and info.item_type in STOCK_ACCOUNT:
                entries.append(self.returned_cost_entry(row, info))
        if self.vat_mode != VAT_NONE:
            for key, g in groups.items():
                if g["taxable"] and g["vat"] > 0:
                    registers.append(self.vat_row(key, -g["net"], -g["vat"], EVENT_SHIPMENT))
        return entries, registers, []

    def returned_cost_entry(self, row, info):
        """Dt 281 Ct 902: the goods come back at the cost of the shipment, not at the current average."""
        account = row.account or STOCK_ACCOUNT[info.item_type]
        shipped_qty = shipped_cost = 0.0
        for line in self.inv.get("event_lines") or []:
            if line.event == self.event.return_of and line.invoice_row == row.invoice_row and line.line_type == "goods":
                shipped_qty += flt(line.quantity)
                shipped_cost += flt(line.cost)
                warehouse = line.warehouse
        before_qty = before_cost = 0.0
        for other in inv_logic.posted_events(self.inv, exclude=self.number).values():
            if other.kind != KIND_RETURN or other.return_of != self.event.return_of:
                continue
            for line in lines_of(self.inv, other):
                if line.invoice_row == row.invoice_row:
                    before_qty += flt(line.quantity)
                    before_cost += flt(line.cost)
        qty = flt(row.quantity, 3)
        if not shipped_qty:
            frappe.throw(_("Рядок повернення {0} не належить відвантаженню {1}").format(row.idx, self.event.return_of))
        if flt(before_qty + qty, 3) >= flt(shipped_qty, 3):
            cost = flt(shipped_cost - before_cost, 2)  # the last piece takes the rounding
        else:
            cost = flt(shipped_cost * qty / shipped_qty, 2)
        row.cost = cost
        row.warehouse = row.warehouse or warehouse
        return self.entry(
            account,
            COST_ACCOUNT.get(account, COST_ACCOUNT_DEFAULT),
            cost,
            {"Item": row.item, "Warehouse": row.warehouse},
            {"Item": row.item, "ExpenseItem": None},
            quantity_dr=qty,
            content=_("Собівартість {0}").format(self.number)[:140],
        )


# ---------------------------------------------------------------- posting


def _post(poster):
    """Write the movements of one event and store the cost on its lines."""
    for row in poster.all_lines:
        row.cost = 0
    entries, liabilities, credits = poster.build()
    entries = [e for e in entries if flt(e.get("amount")) or e.get("quantity_dr") or e.get("quantity_cr")]
    if not entries:
        frappe.throw(_("Подія не створює жодної проводки"))
    ledger.post_entries(poster, entries)
    vat.post_vat_entries(poster, liabilities, credits)
    for row in poster.all_lines:
        if row.name:
            frappe.db.set_value("UA Invoice Event Line", row.name, "cost", flt(row.cost, 2), update_modified=False)
    cost = flt(sum(flt(row.cost) for row in poster.all_lines), 2)
    poster.event.cost_amount = cost
    if poster.event.name:
        frappe.db.set_value("UA Invoice Event", poster.event.name, "cost_amount", cost, update_modified=False)


def post_event(inv, event):
    """Post a new event and put it into the sequence of the stock cost."""
    poster = EventPoster(inv, event)
    _post(poster)
    sequences.mark_part(inv, event.number, moment_of(inv, event))
    return poster


def repost_event(inv, event):
    """Post an event again (a back-dated receipt changed the cost, a restore of the sequence). The ПН links stay."""
    poster = EventPoster(inv, event)
    links = stock._vat_links(INVOICE, inv.name, poster.part)
    ledger.cancel_entries(poster)
    _post(poster)
    stock._restore_vat_links(INVOICE, inv.name, links, poster.part)
    if event.kind == KIND_SHIPMENT:
        # the returns of the shipment take their cost from its lines
        for ret in returns_of(inv, event):
            repost_event(inv, ret)


def cancel_event(inv, number, reason, save=True):
    """Cancel a posted event: its movements go, the row stays with the status and the reason.

    `save` is off when the Invoice itself is being cancelled: the document is saved by the cancel.
    """
    event = get_event(inv, number)
    if event.status != POSTED:
        frappe.throw(_("Подія {0} вже скасована").format(number))
    if not (reason or "").strip():
        frappe.throw(_("Вкажіть причину скасування"))
    check_lock(inv, event.posting_date)
    pn = frappe.db.exists(
        tax.PN, {"basis_type": INVOICE, "basis": inv.name, "basis_part": number, "docstatus": 1}
    )
    if pn:
        frappe.throw(_("Спочатку скасуйте податкову накладну {0}").format(pn))
    if event.kind == KIND_SHIPMENT and returns_of(inv, event):
        frappe.throw(
            _("Спочатку скасуйте повернення відвантаження {0}: {1}").format(
                number, ", ".join(e.number for e in returns_of(inv, event))
            )
        )
    poster = EventPoster(inv, event)
    ledger.cancel_entries(poster)
    event.status = CANCELLED
    event.cancelled_on = now_datetime()
    event.cancelled_by = frappe.session.user
    event.cancel_reason = reason
    if event.kind == KIND_RETURN:
        _restore_adjustments(inv, event)
    if save:
        inv.flags.invoice_action = True
        inv.flags.ignore_permissions = True
        inv.save()
    sequences.mark_part(inv, number, moment_of(inv, event), cancel=True)


def _restore_adjustments(inv, event):
    """A cancelled return gives back the quantity that it took from the Invoice."""
    taken = {}
    for adj in inv.get("adjustments") or []:
        if adj.source_doctype == INVOICE and adj.source_name == event.number:
            taken[adj.invoice_row] = (adj.item, flt(taken.get(adj.invoice_row, (None, 0))[1] + flt(adj.quantity_delta), 3))
    for row, (item, delta) in taken.items():
        if delta < 0:
            inv.append(
                "adjustments",
                {
                    "posting_date": nowdate(),
                    "invoice_row": row,
                    "item": item,
                    "quantity_delta": -delta,
                    "reason": _("Скасування повернення {0}").format(event.number),
                    "source_doctype": INVOICE,
                    "source_name": event.number,
                },
            )


def cancel_all(inv, reason):
    """The Invoice is cancelled: its posted events are cancelled in reverse date order (not saved here)."""
    posted = sorted(
        inv_logic.posted_events(inv).values(), key=lambda e: (getdate(e.posting_date), get_datetime(e.moment)), reverse=True
    )
    for event in posted:
        cancel_event(inv, event.number, reason, save=False)


# ---------------------------------------------------------------- creation


def _line(inv, src, qty, line_type, cache, warehouse=None, invoice_row=None):
    percent, taxable = vat_info(src.vat_rate, cache)
    amount, vat_amount, total = calc_line(
        qty, src.price, percent if taxable else 0, inv.vat_mode, src.get("discount_percent")
    )
    row = {f: src.get(f) for f in LINE_FIELDS if src.get(f) not in (None, "")}
    row.update(
        line_type=line_type,
        invoice_row=invoice_row or src.name,
        quantity=qty,
        amount=amount,
        vat_amount=vat_amount,
        total=total,
        warehouse=warehouse if line_type == "goods" else None,
    )
    return row


def _fit_last_parts(inv, rows, kinds):
    """The part that completes an Invoice row takes the remainder of its sums: all parts add up to the Invoice."""
    if inv_logic.adjustments_of(inv):
        return
    done = inv_logic._sum_by_row(inv, kinds)
    own = {r.name: r for t in ("goods", "services") for r in inv.get(t) or []}
    per_row = {}
    for row in rows:
        per_row.setdefault(row["invoice_row"], []).append(row)
    for name, items in per_row.items():
        src, before = own.get(name), done.get(name)
        if not src or not before or len(items) != 1:
            continue
        row = items[0]
        if flt(before.quantity + flt(row["quantity"]), 3) == flt(src.quantity, 3):
            row["amount"] = flt(src.amount - before.amount, 2)
            row["vat_amount"] = flt(src.vat_amount - before.vat_amount, 2)
            row["total"] = flt(src.total - before.total, 2)


def new_event(
    inv, kind, posting_date, picks, warehouse=None, return_of=None, offset_advance=1, event_key=None, packaging_rows=None,
    vehicle_no=None, driver_name=None,
):
    """Add an event to the locked, fresh Invoice and post it. `picks` is [(invoice row name, quantity)]. Returns the event row."""
    posting_date = getdate(posting_date or nowdate())
    if not picks:
        frappe.throw(_("Немає що виконувати: усе за інвойсом {0} вже виконано").format(inv.name))
    if inv.customer_order and frappe.db.get_value("UA Customer Order", inv.customer_order, "docstatus") == 2:
        frappe.throw(_("Замовлення {0} скасоване").format(inv.customer_order))
    check_lock(inv, posting_date)

    own = {r.name: r for t in ("goods", "services") for r in inv.get(t) or []}
    cache = {}
    rows = []
    if kind == KIND_RETURN:
        shipment = get_event(inv, return_of)
        if shipment.kind != KIND_SHIPMENT or shipment.status != POSTED:
            frappe.throw(_("Відвантаження {0} не проведене").format(return_of))
        if posting_date < getdate(shipment.posting_date):
            frappe.throw(_("Повернення не може бути раніше відвантаження {0}").format(return_of))
        shipped = {l.invoice_row: l for l in lines_of(inv, shipment) if l.line_type == "goods"}
        returned = {}
        for ret in returns_of(inv, shipment):
            for l in lines_of(inv, ret):
                returned[l.invoice_row] = flt(returned.get(l.invoice_row, 0) + flt(l.quantity), 3)
        warehouse = shipment.warehouse
        for name, qty in picks:
            src = shipped.get(name)
            if not src:
                frappe.throw(_("Рядок {0} не входить до відвантаження {1}").format(name, return_of))
            if qty > flt(src.quantity - returned.get(name, 0), 3):
                frappe.throw(
                    _("Номенклатуру {0} можна повернути не більше {1}: відвантажено {2}, вже повернуто {3}").format(
                        src.item_name or src.item, flt(src.quantity - returned.get(name, 0), 3), src.quantity,
                        returned.get(name, 0),
                    )
                )
            rows.append(_line(inv, own[name], qty, "goods", cache, warehouse=src.warehouse))
    else:
        table = "goods" if kind == KIND_SHIPMENT else "services"
        warehouse = warehouse or inv.get("warehouse")
        left = {l.row: l for l in inv_logic.effective_lines(inv) if l.table == table}
        for name, qty in picks:
            line = left.get(name)
            if not line:
                frappe.throw(_("Рядок {0} не належить інвойсу {1}").format(name, inv.name))
            if qty > line.left:
                frappe.throw(
                    _("Номенклатура {0}: кількість {1} перевищує залишок {2} за інвойсом {3}: потрібне коригування інвойсу").format(
                        line.item_name or line.item, qty, max(line.left, 0), inv.name
                    )
                )
            src = line.source
            row_warehouse = src.get("warehouse") or warehouse
            if table == "goods" and is_stock_item(src):
                if not row_warehouse:
                    frappe.throw(_("Рядок {0}: вкажіть склад").format(src.idx))
                if is_retail(row_warehouse):
                    frappe.throw(_("Рядок {0}: з роздрібного складу продають звітом про роздрібні продажі").format(src.idx))
            rows.append(_line(inv, src, qty, table, cache, warehouse=row_warehouse))
        _fit_last_parts(inv, rows, SHIPPING)

    context = frappe._dict(organization=inv.organization, warehouse=warehouse)
    deposit_rows = []
    for index, item in enumerate(packaging_rows or [], 1):
        row = frappe._dict(item, idx=index)
        packaging.check_row(context, row)
        deposit_rows.append(
            {"line_type": "packaging", "item": row.item, "item_name": row.item_name, "uom": row.uom,
             "quantity": flt(row.quantity, 3), "price": flt(row.price, 2), "amount": row.amount, "total": row.amount,
             "warehouse": row.warehouse}
        )
    deposit = flt(sum(r["amount"] for r in deposit_rows), 2)

    uah = lambda value: flt(flt(value) * (flt(inv.exchange_rate) or 1), 2)
    net = flt(sum(r["total"] - r["vat_amount"] for r in rows), 2)
    vat_total = flt(sum(r["vat_amount"] for r in rows), 2)
    total = flt(sum(r["total"] for r in rows) + deposit, 2)
    base = flt(sum(uah(r["total"] - r["vat_amount"]) + uah(r["vat_amount"]) for r in rows) + uah(deposit), 2)

    number = event_number(inv, kind, posting_date)
    event = inv.append(
        "events",
        {
            "kind": kind,
            "number": number,
            "posting_date": posting_date,
            "warehouse": warehouse if kind != KIND_SERVICES else None,
            "return_of": return_of if kind == KIND_RETURN else None,
            "offset_advance": 1 if kind in SHIPPING and offset_advance in (1, "1", True, None) else 0,
            "vehicle_no": vehicle_no or None,
            "driver_name": driver_name or None,
            "status": POSTED,
            "total_net": net,
            "vat_total": vat_total,
            "total_amount": total,
            "base_total": base,
            "event_key": event_key or None,
            "moment": now_datetime(),
        },
    )
    for line in [*rows, *deposit_rows]:
        inv.append("event_lines", {**line, "event": number})
    inv.flags.invoice_action = True
    inv.flags.ignore_permissions = True
    inv.save()
    event = get_event(inv, number)
    post_event(inv, event)
    return event


def is_stock_item(src):
    info = frappe.db.get_value("UA Item", src.item, "item_type")
    return info != TYPE_SERVICE
