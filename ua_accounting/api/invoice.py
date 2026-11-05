"""Invoice (Інвойс) actions and the card data (T-533, T-705).

There is no document of the sale. Every action adds an event to the Invoice (shipment, service provision, return): a row
with its own number, date, lines and movements (accounting/invoice_events.py), or cancels one. Each runs in the
transaction of the request on the locked, fresh Invoice: an error leaves nothing. `event_key` makes an action idempotent:
the same key returns the event that was already made.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from ua_accounting.accounting import invoice as inv_logic
from ua_accounting.accounting import invoice_events as events
from ua_accounting.accounting import tax, vat
from ua_accounting.accounting.documents import fill_cash_side
from ua_accounting.accounting.invoice import (
    INVOICE,
    KIND_RETURN,
    KIND_SERVICES,
    KIND_SHIPMENT,
    POSTED,
)


def _locked(name, right):
    """The Invoice for an action: the permission is checked, then the document is locked and read fresh."""
    frappe.get_doc(INVOICE, name).check_permission(right)
    inv = inv_logic.lock(name)
    if inv.docstatus != 1:
        frappe.throw(_("Інвойс {0} не підтверджений").format(name))
    return inv


def _doc(name, right):
    doc = frappe.get_doc(INVOICE, name)
    doc.check_permission(right)
    if doc.docstatus != 1:
        frappe.throw(_("Інвойс {0} не підтверджений").format(name))
    return doc


def _list(value):
    return json.loads(value) if isinstance(value, str) else (value or [])


def _wanted(inv, table, lines):
    """[(invoice row, quantity)] asked by the dialog; by default everything that is left."""
    left = {l.row: l for l in inv_logic.effective_lines(inv) if l.table == table}
    asked = {}
    if lines:
        for item in _list(lines):
            row = item.get("row")
            if row not in left:
                frappe.throw(_("Рядок {0} не належить інвойсу {1}").format(row, inv.name))
            asked[row] = flt(asked.get(row, 0) + flt(item.get("quantity")), 3)
    else:
        asked = {row: line.left for row, line in left.items() if line.left > 0}
    asked = {row: qty for row, qty in asked.items() if qty > 0}
    if not asked:
        frappe.throw(_("Немає що виконувати: усе за інвойсом {0} вже виконано").format(inv.name))
    return list(asked.items())


def _done(inv, event):
    inv_logic.after_event(inv)
    return event.number


@frappe.whitelist(methods=["POST"])
def ship(
    name, posting_date=None, warehouse=None, lines=None, packaging=None, event_key=None, offset_advance=1,
    vehicle_no=None, driver_name=None,
):
    """Shipment of goods: an event of the Invoice for the rows (default: all that is left). Returns its number."""
    inv = _locked(name, "submit")
    if found := events.event_by_key(inv, event_key):
        return found.number
    event = events.new_event(
        inv, KIND_SHIPMENT, posting_date, _wanted(inv, "goods", lines), warehouse=warehouse,
        offset_advance=offset_advance, event_key=event_key, packaging_rows=_list(packaging),
        vehicle_no=vehicle_no, driver_name=driver_name,
    )
    return _done(inv, event)


@frappe.whitelist(methods=["POST"])
def provide_services(name, posting_date=None, lines=None, event_key=None, offset_advance=1):
    """Provision of services: an event of the Invoice for the rows (default: all that is left). Returns its number."""
    inv = _locked(name, "submit")
    if found := events.event_by_key(inv, event_key):
        return found.number
    event = events.new_event(
        inv, KIND_SERVICES, posting_date, _wanted(inv, "services", lines), offset_advance=offset_advance,
        event_key=event_key,
    )
    return _done(inv, event)


@frappe.whitelist(methods=["POST"])
def return_goods(name, shipment, posting_date=None, lines=None, reduce_invoice=1, event_key=None):
    """Return of goods of one shipment (its event number). With `reduce_invoice` the quantity of the Invoice is reduced too."""
    inv = _locked(name, "submit")
    if found := events.event_by_key(inv, event_key):
        return found.number
    asked = {}
    for item in _list(lines):
        asked[item.get("row")] = flt(asked.get(item.get("row"), 0) + flt(item.get("quantity")), 3)
    asked = {row: qty for row, qty in asked.items() if qty > 0}
    if not asked:
        frappe.throw(_("Вкажіть, що повертається"))
    event = events.new_event(
        inv, KIND_RETURN, posting_date, list(asked.items()), return_of=shipment, event_key=event_key
    )
    if str(reduce_invoice) not in ("0", "False", "false", ""):
        rows = [
            {"invoice_row": row, "quantity_delta": -qty, "reason": _("Повернення {0}").format(event.number),
             "source_doctype": INVOICE, "source_name": event.number}
            for row, qty in asked.items()
        ]
        _add_adjustments(inv, rows, check_floor=False, event_action=True)
    return _done(inv, event)


@frappe.whitelist(methods=["POST"])
def cancel_event(name, event, reason):
    """Cancel one event of the Invoice: its movements go, the event stays in the history with the reason."""
    inv = _locked(name, "cancel")
    events.cancel_event(inv, event, reason)
    inv_logic.after_event(inv)
    return event


def _add_adjustments(inv, rows, check_floor=True, event_action=False):
    own = {r.name: r for t in ("goods", "services") for r in inv.get(t) or []}
    for item in rows:
        src = own.get(item["invoice_row"])
        if not src:
            frappe.throw(_("Рядок {0} не належить інвойсу {1}").format(item["invoice_row"], inv.name))
        inv.append(
            "adjustments",
            {
                "posting_date": nowdate(), "invoice_row": src.name, "item": src.item,
                "quantity_delta": flt(item["quantity_delta"], 3), "reason": item.get("reason"),
                "source_doctype": item.get("source_doctype"), "source_name": item.get("source_name"),
            },
        )
    if check_floor:
        for line in inv_logic.effective_lines(inv):
            if line.effective < 0 or line.effective < flt(line.shipped - line.returned, 3):
                frappe.throw(
                    _("Номенклатура {0}: кількість за інвойсом не може бути меншою за вже виконану").format(line.item_name or line.item)
                )
    inv.flags.ignore_permissions = True
    # the date of the return was checked with the return: the date of the Invoice does not lock this change
    inv.flags.invoice_action = event_action
    inv.save()
    inv_logic.refresh(inv.name)


@frappe.whitelist(methods=["POST"])
def adjust(name, rows, reason):
    """Change the quantity of Invoice rows after the confirmation. Manager only; the change stays in the history."""
    inv = _locked(name, "cancel")
    if not (reason or "").strip():
        frappe.throw(_("Вкажіть причину коригування"))
    items = _list(rows)
    if not items:
        frappe.throw(_("Вкажіть рядки коригування"))
    _add_adjustments(inv, [{**r, "invoice_row": r.get("row") or r.get("invoice_row"), "reason": reason} for r in items])
    inv_logic.after_event(inv)
    return name


@frappe.whitelist()
def make_payment(source_name, target_doc=None):
    """Cash receipt on the basis of an Invoice: one allocation row for the debt (the payment itself is a finance document)."""
    inv = frappe.get_doc(INVOICE, source_name)
    inv.check_permission("read")
    if inv.docstatus != 1:
        frappe.throw(_("Інвойс {0} не підтверджений").format(source_name))
    doc = frappe.new_doc("UA Cash Receipt")
    for field in ("organization", "counterparty", "contract", "currency", "exchange_rate"):
        doc.set(field, inv.get(field))
    doc.operation_type = "Оплата від покупця"
    doc.settlement_type = "Оплата за реалізацію"
    debt = max(flt(inv.debt_amount, 2), 0) or flt(inv.effective_total, 2)
    doc.amount = debt
    first = (inv.goods or inv.services)[0]
    if inv.vat_mode != "Без ПДВ":
        doc.vat_rate = first.vat_rate
    fill_cash_side(doc)
    doc.append("allocations", {"invoice": inv.name, "amount": debt})
    return doc


@frappe.whitelist(methods=["POST"])
def create_tax_invoice(name, event=None, payment=None):
    """Draft tax invoice for one event of the Invoice or for an allocated payment (an advance)."""
    inv = _doc(name, "read")
    from ua_accounting.api.tax_invoice import create_on_basis

    if event:
        events.get_event(inv, event)
        return create_on_basis(INVOICE, name, basis_part=event)
    if payment and frappe.db.exists("UA Payment Allocation", {"parent": payment, "parenttype": "UA Cash Receipt", "invoice": name}):
        return create_on_basis("UA Cash Receipt", payment)
    frappe.throw(_("Вкажіть подію інвойсу {0} або його оплату").format(inv.name))


# ---------------------------------------------------------------- card


def _tax_events(inv, payments):
    """VAT liability rows of the events and of the allocated payments, with the state of their tax invoice."""
    registrars = [(INVOICE, inv.name, e.number) for e in inv.get("events") or [] if e.status == POSTED]
    registrars += [("UA Cash Receipt", p["registrar"], "") for p in payments if p["registrar_type"] == "UA Cash Receipt"]
    result = []
    for doctype, name, part in registrars:
        filters = {"registrar_type": doctype, "registrar": name}
        if part:
            filters["registrar_part"] = part
        rows = frappe.get_all(
            vat.LIABILITY, filters=filters,
            fields=["registrar_type", "registrar", "posting_date", "event", "vat_rate", "base_amount", "vat_amount",
                    "tax_invoice"],
            order_by="line_no asc", limit_page_length=0,
        )
        if not rows:
            continue
        pn = next((r.tax_invoice for r in rows if r.tax_invoice), None)
        state, erpn, reg = "Не сформовано", "", ""
        if pn:
            data = frappe.db.get_value(tax.PN, pn, ["erpn_status", "erpn_reg_number"], as_dict=True)
            state, erpn, reg = "Сформовано", data.erpn_status, data.erpn_reg_number
        else:
            draft = frappe.db.get_value(
                tax.PN, {"basis_type": doctype, "basis": name, "basis_part": part or "", "docstatus": 0}, "name"
            )
            if draft:
                pn, state = draft, "Чернетка"
        result.append(
            {
                "basis_doctype": doctype, "basis": name, "basis_part": part, "date": rows[0].posting_date,
                "event": rows[0].event,
                "base_amount": flt(sum(r.base_amount for r in rows), 2), "vat_amount": flt(sum(r.vat_amount for r in rows), 2),
                "tax_invoice": pn, "formation": state, "erpn_status": erpn, "erpn_reg_number": reg,
            }
        )
    return result


def _event_data(inv, event, returned):
    return {
        "name": event.number, "number": event.number, "kind": event.kind, "posting_date": event.posting_date,
        "status": event.status, "docstatus": 1 if event.status == POSTED else 2, "warehouse": event.warehouse,
        "return_of": event.return_of, "total_amount": event.total_amount, "vat_total": event.vat_total,
        "cost_amount": event.cost_amount, "cancel_reason": event.cancel_reason, "cancelled_on": event.cancelled_on,
        "cancelled_by": event.cancelled_by,
        "lines": [
            {"row": l.invoice_row, "item": l.item, "item_name": l.item_name, "quantity": flt(l.quantity, 3),
             "amount": l.amount, "line_type": l.line_type,
             "returned": returned.get((event.number, l.invoice_row), 0.0)}
            for l in events.lines_of(inv, event) if l.line_type != "packaging"
        ],
    }


@frappe.whitelist()
def get_overview(name):
    """Everything for the Invoice card: states, amounts, rows with shipped and left, events, payments, taxes, prints."""
    inv = frappe.get_doc(INVOICE, name)
    inv.check_permission("read")
    lines = inv_logic.effective_lines(inv)
    returned = {}
    for event in inv_logic.posted_events(inv).values():
        if event.kind == KIND_RETURN:
            for l in events.lines_of(inv, event):
                key = (event.return_of, l.invoice_row)
                returned[key] = flt(returned.get(key, 0) + flt(l.quantity), 3)
    event_list = [_event_data(inv, e, returned) for e in sorted(
        inv.get("events") or [], key=lambda e: (str(e.posting_date), str(e.moment)))]
    payments = []
    if inv.docstatus == 1:
        slot_accounts = ("361", "362", "681")
        for account in slot_accounts:
            slot = inv_logic.slot_of(account, "SettlementDoc", {})
            if not slot:
                continue
            for side, sign in (("cr", 1), ("dr", -1)):
                payments += [
                    {"registrar_type": r.registrar_type, "registrar": r.registrar, "date": r.posting_date,
                     "amount": sign * flt(r.amount, 2), "account": account}
                    for r in frappe.get_all(
                        "UA Accounting Entry",
                        filters={f"account_{side}": account, f"subconto_{side}{slot}": name,
                                 f"subconto_{side}{slot}_type": INVOICE, "registrar_type": ("in", inv_logic.PAYMENT_REGISTRARS)},
                        fields=["registrar_type", "registrar", "posting_date", "amount"], limit_page_length=0,
                    )
                ]
        fifo = inv_logic.invoice_fifo(inv)
        if fifo:
            payments.append(
                {"registrar_type": "", "registrar": "", "date": None, "amount": fifo, "account": "",
                 "label": _("Оплата за договором (без розподілу)")}
            )
    prints = [{"label": "Рахунок на оплату", "doctype": INVOICE, "name": name, "format": "UA Рахунок на оплату"}]
    for e in event_list:
        if e["status"] != POSTED:
            continue
        if e["kind"] == KIND_SHIPMENT:
            prints += [
                {"label": "Видаткова накладна", "doctype": INVOICE, "name": name, "event": e["number"],
                 "format": "UA Видаткова накладна"},
                {"label": "ТТН", "doctype": INVOICE, "name": name, "event": e["number"], "format": "UA ТТН"},
            ]
        elif e["kind"] == KIND_SERVICES:
            prints.append({"label": "Акт виконаних робіт", "doctype": INVOICE, "name": name, "event": e["number"],
                           "format": "UA Акт виконаних робіт"})
    tax_events = _tax_events(inv, payments) if inv.docstatus == 1 else []
    for t in tax_events:
        if t["tax_invoice"] and t["formation"] == "Сформовано":
            prints.append({"label": "Податкова накладна", "doctype": tax.PN, "name": t["tax_invoice"],
                           "format": "UA Податкова накладна (ПН)"})
    history = []
    try:
        from frappe.beeone import change_log

        history += [{**h, "doctype": INVOICE, "docname": name} for h in change_log.get_history(INVOICE, name, 50)]
    except frappe.PermissionError:
        pass
    history.sort(key=lambda h: str(h.get("creation") or h.get("timestamp") or ""), reverse=True)
    return {
        "name": name, "docstatus": inv.docstatus, "currency": inv.currency,
        "states": {k: inv.get(k) for k in ("commercial_status", "fulfilment_status", "payment_status")},
        "amounts": {k: flt(inv.get(k), 2) for k in ("total_amount", "effective_total", "fulfilled_amount", "paid_amount", "debt_amount")},
        "lines": [
            {"row": l.row, "table": l.table, "item": l.item, "item_name": l.item_name, "quantity": l.quantity,
             "adjustment": l.adjustment, "effective": l.effective, "shipped": l.shipped, "returned": l.returned, "left": l.left}
            for l in lines
        ],
        "events": event_list, "payments": payments, "tax_events": tax_events, "prints": prints,
        "adjustments": [a.as_dict() for a in inv.get("adjustments") or []], "history": history[:50],
    }


@frappe.whitelist()
def print_event(name, event, print_format, pdf=0):
    """The primary document of one event (waybill, TTN, act) from the Invoice: the number and date of the event, its lines."""
    from frappe.utils.print_utils import get_print

    inv = frappe.get_doc(INVOICE, name)
    inv.check_permission("read")
    row = events.get_event(inv, event)
    if row.status != POSTED:
        frappe.throw(_("Подія {0} скасована: друк недоступний").format(event))
    inv.print_event = frappe._dict(
        row.as_dict(),
        lines=[l.as_dict() for l in events.lines_of(inv, row) if l.line_type != "packaging"],
        packaging=[l.as_dict() for l in events.lines_of(inv, row) if l.line_type == "packaging"],
    )
    if str(pdf) not in ("0", "", "False", "false"):
        frappe.local.response.filename = f"{event}.pdf"
        frappe.local.response.filecontent = get_print(INVOICE, name, print_format, doc=inv, as_pdf=True)
        frappe.local.response.type = "pdf"
        return
    return get_print(INVOICE, name, print_format, doc=inv)
