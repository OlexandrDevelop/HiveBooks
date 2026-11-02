"""Invoice (Інвойс) actions and the card data (T-533).

Every action creates and submits an existing posting document (shipment, service act, return) linked to the
Invoice. All run in the transaction of the request: an error leaves nothing. `event_key` makes an action
idempotent: the same key returns the document that was already made.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from ua_accounting.accounting import invoice as inv_logic
from ua_accounting.accounting import tax, vat
from ua_accounting.accounting.documents import fill_cash_side
from ua_accounting.accounting.invoice import ACT, INVOICE, RETURN, SALE


def _doc(name, right):
    doc = frappe.get_doc(INVOICE, name)
    doc.check_permission(right)
    if doc.docstatus != 1:
        frappe.throw(_("Інвойс {0} не підтверджений").format(name))
    return doc


def _list(value):
    return json.loads(value) if isinstance(value, str) else (value or [])


def _existing(doctype, event_key, locking=False):
    """The event made earlier with this key. `locking` reads the latest committed row (after the lock of the Invoice)."""
    if not event_key:
        return None
    return frappe.db.get_value(doctype, {"event_key": event_key}, "name", for_update=locking)


def _wanted(inv, table, lines):
    """{invoice row: quantity} asked by the dialog; by default everything that is left.

    Called after the lock of the Invoice: the events are read with a locking read (latest committed rows).
    """
    left = {l.row: l for l in inv_logic.effective_lines(inv, locking=True) if l.table == table}
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
    for row, qty in asked.items():
        if qty > left[row].left:
            frappe.throw(
                _("Номенклатура {0}: кількість {1} перевищує залишок {2} за інвойсом {3}: потрібне коригування інвойсу").format(
                    left[row].item_name or left[row].item, qty, max(left[row].left, 0), inv.name
                )
            )
    return asked, left


def _event(doctype, inv, posting_date, event_key, offset_advance):
    doc = frappe.new_doc(doctype)
    for field in ("organization", "counterparty", "contract", "currency", "exchange_rate", "vat_mode"):
        doc.set(field, inv.get(field))
    doc.update({"posting_date": posting_date or nowdate(), "invoice": inv.name, "event_key": event_key or None})
    if doc.meta.has_field("offset_advance"):
        doc.offset_advance = 1 if offset_advance in (1, "1", True, None) else 0
    return doc


def _append(doc, table, src, qty, fields, invoice_row=None):
    row = {f: src.get(f) for f in fields if src.get(f) not in (None, "")}
    row.update(quantity=qty, invoice_row=invoice_row or src.name)
    doc.append(table, row)


@frappe.whitelist(methods=["POST"])
def ship(name, posting_date=None, warehouse=None, lines=None, event_key=None, offset_advance=1):
    """Shipment of goods: a UA Sales Invoice for the rows (default: all that is left). Returns its name."""
    inv = _doc(name, "submit")
    if found := _existing(SALE, event_key):
        return found
    inv_logic.lock(name)
    if found := _existing(SALE, event_key, locking=True):  # a parallel call with the same key may have committed meanwhile
        return found
    asked, _left = _wanted(inv, "goods", lines)
    doc = _event(SALE, inv, posting_date, event_key, offset_advance)
    doc.warehouse = warehouse or inv.get("warehouse")
    doc.customer_order = inv.get("customer_order")
    doc.price_type = inv.get("price_type")
    for src in inv.goods:
        if src.name in asked:
            _append(doc, "goods", src, asked[src.name], ("item", "uom", "price", "discount_percent", "vat_rate", "account"))
            doc.goods[-1].warehouse = src.warehouse or doc.warehouse
    doc.insert()
    doc.submit()
    return doc.name


@frappe.whitelist(methods=["POST"])
def provide_services(name, posting_date=None, lines=None, event_key=None, offset_advance=1):
    """Provision of services: a UA Service Act for the rows (default: all that is left). Returns its name."""
    inv = _doc(name, "submit")
    if found := _existing(ACT, event_key):
        return found
    inv_logic.lock(name)
    if found := _existing(ACT, event_key, locking=True):
        return found
    asked, _left = _wanted(inv, "services", lines)
    doc = _event(ACT, inv, posting_date, event_key, offset_advance)
    for src in inv.services:
        if src.name in asked:
            _append(
                doc, "services", src, asked[src.name],
                ("item", "uom", "price", "discount_percent", "vat_rate", "account", "expense_item", "department"),
            )
    doc.insert()
    doc.submit()
    return doc.name


@frappe.whitelist(methods=["POST"])
def return_goods(name, shipment, posting_date=None, lines=None, reduce_invoice=1, event_key=None):
    """Return of goods of one shipment. With `reduce_invoice` the quantity of the Invoice is reduced too."""
    inv = _doc(name, "submit")
    if found := _existing(RETURN, event_key):
        return found
    sale = frappe.get_doc(SALE, shipment)
    if sale.invoice != name or sale.docstatus != 1:
        frappe.throw(_("Відвантаження {0} не належить інвойсу {1}").format(shipment, name))
    inv_logic.lock(name)
    if found := _existing(RETURN, event_key, locking=True):
        return found
    by_row = {r.invoice_row: r for r in sale.goods}
    doc = _event(RETURN, inv, posting_date, event_key, None)
    doc.sales_invoice = shipment
    doc.warehouse = sale.warehouse
    asked = {}
    for item in _list(lines):
        asked[item.get("row")] = flt(asked.get(item.get("row"), 0) + flt(item.get("quantity")), 3)
    if not asked:
        frappe.throw(_("Вкажіть, що повертається"))
    for row, qty in asked.items():
        src = by_row.get(row)
        if not src:
            frappe.throw(_("Рядок {0} не входить до відвантаження {1}").format(row, shipment))
        _append(doc, "goods", src, qty, ("item", "uom", "price", "discount_percent", "vat_rate", "warehouse", "account"),
                invoice_row=src.invoice_row)
    doc.insert()
    doc.submit()
    if str(reduce_invoice) not in ("0", "False", "false", ""):
        rows = [
            {"invoice_row": row, "quantity_delta": -qty, "reason": _("Повернення {0}").format(doc.name),
             "source_doctype": RETURN, "source_name": doc.name}
            for row, qty in asked.items()
        ]
        _add_adjustments(inv, rows, check_floor=False)
    inv_logic.refresh(name)
    return doc.name


def _add_adjustments(inv, rows, check_floor=True):
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
    inv.save()
    inv_logic.refresh(inv.name)


@frappe.whitelist(methods=["POST"])
def adjust(name, rows, reason):
    """Change the quantity of Invoice rows after the confirmation. Manager only; the change stays in the history."""
    inv = _doc(name, "cancel")
    if not (reason or "").strip():
        frappe.throw(_("Вкажіть причину коригування"))
    items = _list(rows)
    if not items:
        frappe.throw(_("Вкажіть рядки коригування"))
    inv_logic.lock(name)
    _add_adjustments(inv, [{**r, "invoice_row": r.get("row") or r.get("invoice_row"), "reason": reason} for r in items])
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
def create_tax_invoice(name, basis_doctype, basis_name):
    """Draft tax invoice for one event of the Invoice (a shipment, an act or an allocated payment)."""
    inv = _doc(name, "read")
    ok = False
    if basis_doctype in (SALE, ACT):
        ok = frappe.db.get_value(basis_doctype, basis_name, "invoice") == name
    elif basis_doctype == "UA Cash Receipt":
        ok = bool(frappe.db.exists("UA Payment Allocation", {"parent": basis_name, "parenttype": basis_doctype, "invoice": name}))
    if not ok:
        frappe.throw(_("Документ {0} не належить інвойсу {1}").format(basis_name, inv.name))
    from ua_accounting.api.tax_invoice import create_on_basis

    return create_on_basis(basis_doctype, basis_name)


# ---------------------------------------------------------------- card


def _tax_events(inv, events, payments):
    """VAT liability rows of the events and of the allocated payments, with the state of their tax invoice."""
    registrars = [(d, e["name"]) for d, items in events.items() for e in items if e["docstatus"] == 1]
    registrars += [("UA Cash Receipt", p["registrar"]) for p in payments if p["registrar_type"] == "UA Cash Receipt"]
    result = []
    for doctype, name in registrars:
        rows = frappe.get_all(
            vat.LIABILITY, filters={"registrar_type": doctype, "registrar": name},
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
            draft = frappe.db.get_value(tax.PN, {"basis_type": doctype, "basis": name, "docstatus": 0}, "name")
            if draft:
                pn, state = draft, "Чернетка"
        result.append(
            {
                "basis_doctype": doctype, "basis": name, "date": rows[0].posting_date, "event": rows[0].event,
                "base_amount": flt(sum(r.base_amount for r in rows), 2), "vat_amount": flt(sum(r.vat_amount for r in rows), 2),
                "tax_invoice": pn, "formation": state, "erpn_status": erpn, "erpn_reg_number": reg,
            }
        )
    return result


@frappe.whitelist()
def get_overview(name):
    """Everything for the Invoice card: states, amounts, rows with shipped and left, events, payments, taxes, prints."""
    inv = frappe.get_doc(INVOICE, name)
    inv.check_permission("read")
    lines = inv_logic.effective_lines(inv)
    events = {}
    for doctype in (SALE, ACT, RETURN):
        events[doctype] = frappe.get_all(
            doctype, filters={"invoice": name}, fields=["name", "posting_date", "docstatus", "total_amount"],
            order_by="posting_date asc, creation asc",
        )
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
    prints = [{"label": "Рахунок на оплату", "doctype": INVOICE, "name": name, "format": "UA Рахунок на оплату"}]
    for e in events[SALE]:
        if e["docstatus"] == 1:
            prints += [
                {"label": "Видаткова накладна", "doctype": SALE, "name": e["name"], "format": "UA Видаткова накладна"},
                {"label": "ТТН", "doctype": SALE, "name": e["name"], "format": "UA ТТН"},
            ]
    for e in events[ACT]:
        if e["docstatus"] == 1:
            prints.append({"label": "Акт виконаних робіт", "doctype": ACT, "name": e["name"], "format": "UA Акт виконаних робіт"})
    tax_events = _tax_events(inv, events, payments) if inv.docstatus == 1 else []
    for t in tax_events:
        if t["tax_invoice"] and t["formation"] == "Сформовано":
            prints.append({"label": "Податкова накладна", "doctype": tax.PN, "name": t["tax_invoice"],
                           "format": "UA Податкова накладна (ПН)"})
    history = []
    for doctype, doc_name in [(INVOICE, name)] + [(d, e["name"]) for d, items in events.items() for e in items]:
        try:
            from frappe.beeone import change_log

            history += [{**h, "doctype": doctype, "docname": doc_name} for h in change_log.get_history(doctype, doc_name, 20)]
        except frappe.PermissionError:
            continue
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
        "events": events, "payments": payments, "tax_events": tax_events, "prints": prints,
        "adjustments": [a.as_dict() for a in inv.get("adjustments") or []], "history": history[:50],
    }
