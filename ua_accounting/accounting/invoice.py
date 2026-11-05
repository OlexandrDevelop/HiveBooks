"""Invoice (Інвойс): one document for the whole sale of goods and services (T-533, T-705).

The Invoice is the UA Payment Invoice. It is the only sales document of the user: there is no shipment, act or
return document. The sale is a state of the Invoice, and its events (shipments, service provision, returns) are
rows of the Invoice (tables `events` and `event_lines`) with their own number, date, lines and movements
(accounting/invoice_events.py). Payments stay in the finance documents (UA Cash Receipt with allocations,
UA Bank Statement lines): the Invoice only reads them from the ledger, by the settlement document
(UA Payment Invoice, name) on the accounts 361, 362 and 681.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting.documents import base_currency, slot_of

INVOICE = "UA Payment Invoice"
ADVANCE_ACCOUNT = "681"
CASH_IN = "UA Cash Receipt"
BANK = "UA Bank Statement"
PAYMENT_REGISTRARS = (CASH_IN, BANK, "UA Cash Payment")

KIND_SHIPMENT, KIND_SERVICES, KIND_RETURN = "Відвантаження", "Надання послуг", "Повернення"
SHIPPING = (KIND_SHIPMENT, KIND_SERVICES)
POSTED, CANCELLED = "Проведено", "Скасовано"

COMMERCIAL = {0: "Чернетка", 1: "Підтверджено", 2: "Скасовано"}
NOT_FULFILLED, PARTLY_FULFILLED, FULFILLED = "Не виконано", "Частково виконано", "Виконано"
UNPAID, PARTLY_PAID, PAID = "Не оплачено", "Частково оплачено", "Оплачено"


# ---------------------------------------------------------------- quantities


def posted_events(inv, exclude=None):
    """{number: event row} of the posted events of an Invoice document."""
    return {
        e.number: e for e in inv.get("events") or [] if e.status == POSTED and e.number != exclude
    }


def _sum_by_row(inv, kinds, exclude=None):
    """{invoice row: quantity, amount, vat, total} of the posted events of the given kinds."""
    events = posted_events(inv, exclude)
    result = {}
    for line in inv.get("event_lines") or []:
        event = events.get(line.event)
        if not event or event.kind not in kinds or line.line_type == "packaging" or not line.invoice_row:
            continue
        item = result.setdefault(line.invoice_row, frappe._dict(quantity=0.0, amount=0.0, vat_amount=0.0, total=0.0))
        item.quantity = flt(item.quantity + flt(line.quantity), 3)
        item.amount = flt(item.amount + flt(line.amount), 2)
        item.vat_amount = flt(item.vat_amount + flt(line.vat_amount), 2)
        item.total = flt(item.total + flt(line.total), 2)
    return result


def adjustments_of(inv):
    result = {}
    for row in inv.get("adjustments") or []:
        result[row.invoice_row] = flt(result.get(row.invoice_row, 0) + flt(row.quantity_delta), 3)
    return result


def effective_lines(inv, exclude=None):
    """Rows of the Invoice with what was done: quantity, adjustments, shipped (or provided), returned, left.

    `exclude` is an event (number) that is not counted. The Invoice document must be read after the lock of the
    Invoice (`get_doc(for_update=True)`) when the result is used for a check.
    """
    shipped = _sum_by_row(inv, SHIPPING, exclude)
    returned = _sum_by_row(inv, (KIND_RETURN,), exclude)
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
    """The Invoice document, locked until the end of the transaction and read fresh with its events."""
    return frappe.get_doc(INVOICE, name, for_update=True)


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
                f" and registrar_type = %s and account_dr = %s and subconto_dr{adv_slot} != %s",
                (INVOICE, ADVANCE_ACCOUNT, inv.name),
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


def contract_credit(organization, counterparty, contract, account):
    """Net credit of an account for a contract from the documents that are not linked to an Invoice (base currency).

    Unallocated receipts, bank lines without an Invoice, refunds, journal operations and opening balances:
    credits minus debits of the rows whose settlement document is not an Invoice.
    """
    ctx = {}
    cp, ct, doc = (slot_of(account, name, ctx) for name in ("Counterparty", "Contract", "SettlementDoc"))
    if not cp:
        return 0.0
    total = 0.0
    for side, sign in (("cr", 1), ("dr", -1)):
        where = f"organization = %s and account_{side} = %s and subconto_{side}{cp} = %s"
        params = [organization, account, counterparty or ""]
        if ct:
            where += f" and subconto_{side}{ct} = %s"
            params.append(contract or "")
        if doc:
            where += f" and coalesce(subconto_{side}{doc}_type, '') != %s"
            params.append(INVOICE)
        total += sign * flt(
            frappe.db.sql(f"select coalesce(sum(amount), 0) from `tabUA Accounting Entry` where {where}", params)[0][0]
        )
    return flt(total, 2)


def fifo_shares(organization, counterparty, contract, account):
    """{invoice: base amount} of the payments that are not linked to an Invoice (T-705, plan 3.2).

    The net unlinked credit of the contract is spread over its submitted Invoices by date, each up to its own debt.
    The ledger keeps such payments unlinked; this is only how the Invoice states count them.
    """
    left = contract_credit(organization, counterparty, contract, account)
    shares = {}
    if left <= 0:
        return shares
    ctx = {}
    for name in frappe.get_all(
        INVOICE,
        filters={"organization": organization, "counterparty": counterparty, "contract": contract, "docstatus": 1},
        order_by="posting_date asc, name asc",
        pluck="name",
    ):
        debt = max(settlement_debt(account, name, "9999-12-31", ctx), 0)
        take = flt(min(left, debt), 2)
        if take > 0:
            shares[name] = take
            left = flt(left - take, 2)
        if left <= 0:
            break
    return shares


def settle_account(inv):
    return "361" if inv.currency == base_currency() else "362"


def invoice_fifo(inv, shares=None):
    """The FIFO part of the payments of an Invoice in its currency."""
    if shares is None:
        shares = fifo_shares(inv.organization, inv.counterparty, inv.contract, settle_account(inv))
    amount = flt(shares.get(inv.name, 0))
    return flt(amount / (flt(inv.exchange_rate) or 1), 2) if inv.currency != base_currency() else flt(amount, 2)


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


def states(inv, shares=None):
    """The four independent states of the Invoice and the derived amounts.

    Paid = payments linked to the Invoice (allocations, bank lines, advances) + its FIFO part of the unlinked ones.
    `shares` are the FIFO shares of the contract (see `fifo_shares`), computed when not given.
    """
    lines = effective_lines(inv)
    total = effective_total(inv)
    paid = flt(invoice_paid(inv) + invoice_fifo(inv, shares), 2) if inv.docstatus == 1 else 0.0
    fulfilled = 0.0
    for event in posted_events(inv).values():
        fulfilled += (-1 if event.kind == KIND_RETURN else 1) * flt(event.total_amount)
    return {
        "commercial_status": COMMERCIAL.get(inv.docstatus, "Чернетка"),
        "fulfilment_status": fulfilment_state(lines) if inv.docstatus == 1 else "",
        "payment_status": payment_state(paid, total) if inv.docstatus == 1 else "",
        "effective_total": total,
        "fulfilled_amount": flt(fulfilled, 2),
        "paid_amount": paid,
        "debt_amount": flt(total - paid, 2) if inv.docstatus == 1 else 0.0,
    }


def refresh(name, shares=None):
    """Recompute the derived states and amounts of an Invoice (after an event, a payment or an adjustment)."""
    if not name or not frappe.db.exists(INVOICE, name):
        return
    inv = frappe.get_doc(INVOICE, name)
    frappe.db.set_value(INVOICE, name, states(inv, shares), update_modified=False)


def refresh_contract(organization, counterparty, contract):
    """Recompute all submitted Invoices of a contract: the unlinked payments move between them (FIFO)."""
    if not (organization and counterparty):
        return
    filters = {"organization": organization, "counterparty": counterparty, "docstatus": 1}
    if contract:
        filters["contract"] = contract
    docs = frappe.get_all(INVOICE, filters=filters, fields=["name", "currency", "contract"], order_by="posting_date, name")
    cache = {}
    for row in docs:
        account = "361" if row.currency == base_currency() else "362"
        key = (row.contract, account)
        if key not in cache:
            cache[key] = fifo_shares(organization, counterparty, row.contract, account)
        refresh(row.name, cache[key])


def registrar_contracts(doctype, name):
    """{(organization, counterparty, contract)} of the buyer rows (361, 362, 681) that a registrar wrote."""
    ctx, keys = {}, set()
    for account in ("361", "362", ADVANCE_ACCOUNT):
        cp, ct = slot_of(account, "Counterparty", ctx), slot_of(account, "Contract", ctx)
        if not cp:
            continue
        for side in ("dr", "cr"):
            for org, party, contract in frappe.db.sql(
                f"""select distinct organization, subconto_{side}{cp}, {f"subconto_{side}{ct}" if ct else "''"}
                from `tabUA Accounting Entry` where registrar_type = %s and registrar = %s and account_{side} = %s""",
                (doctype, name, account),
            ):
                if party:
                    keys.add((org, party, contract or ""))
    return keys


def refresh_registrar(doctype, name, keys=None):
    """After a registrar wrote or deleted its rows: the contract of its buyer rows is recomputed (plan 3.4).

    The events of an Invoice refresh themselves (`after_event`). `keys` are the contracts read before a delete.
    """
    if doctype == INVOICE:
        return
    for key in keys if keys is not None else registrar_contracts(doctype, name):
        refresh_contract(*key)


def after_event(inv):
    """After an event was posted, cancelled or an adjustment was made: states of the Invoice, its contract and order."""
    refresh(inv.name)
    refresh_contract(inv.organization, inv.counterparty, inv.contract)
    if inv.customer_order:
        set_order_status(inv.customer_order)


def set_order_status(order):
    """Status of a customer order from its Invoices: shipments + acts - returns per item against the order rows."""
    doc = frappe.get_doc("UA Customer Order", order)
    invoices = frappe.get_all(INVOICE, filters={"customer_order": order, "docstatus": 1}, pluck="name")
    done = {}
    started = False
    for name in invoices:
        for line in effective_lines(frappe.get_doc(INVOICE, name)):
            net = flt(line.shipped - line.returned, 3)
            started = started or line.shipped > 0
            done[line.item] = flt(done.get(line.item, 0) + net, 3)
    wanted = [*(doc.get("goods") or []), *(doc.get("services") or [])]
    if not started:
        status = "Відкрито"
    elif all(done.get(row.item, 0) >= flt(row.quantity, 3) for row in wanted):
        status = "Виконано"
    else:
        status = "Виконується"
    from ua_accounting.administration import set_status

    set_status("UA Customer Order", order, status)
