"""Tax invoices (ПН) and adjustment calculations (РК): shared logic.

The documents themselves are in ua_documents (UA Tax Invoice, UA Tax Adjustment).
A ПН posts no entries: it only links the VAT registers rows of its basis document.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_last_day, getdate

from ua_accounting.accounting import vat

PN = "UA Tax Invoice"
RK = "UA Tax Adjustment"
ISSUED = "Видана"
RECEIVED = "Отримана"

SALE = "UA Sales Invoice"
PURCHASE = "UA Purchase Receipt"
CASH_IN = "UA Cash Receipt"
CASH_OUT = "UA Cash Payment"

# basis document -> direction of its tax invoice
BASIS_DIRECTION = {SALE: ISSUED, CASH_IN: ISSUED, PURCHASE: RECEIVED, CASH_OUT: RECEIVED}

KIND_ORDINARY = "Звичайна"
KIND_NO_PN = "Зведена: постачання без ПН"
KIND_OWN = "Зведена: власні потреби"

STATUS_NONE = "Не зареєстровано"
STATUS_SENT = "Надіслано"
STATUS_REGISTERED = "Зареєстровано"
STATUS_REJECTED = "Відхилено"
STATUSES = (STATUS_NONE, STATUS_SENT, STATUS_REGISTERED, STATUS_REJECTED)

EVENT_ADJUSTMENT = "Коригування"
DEADLINE_DAYS = 15  # ПКУ ст. 201.10


def register_of(direction):
    return vat.LIABILITY if direction == ISSUED else vat.CREDIT


# ---------------------------------------------------------------- cancel guards


def check_cancel_allowed(doc):
    """A basis document with a submitted ПН is cancelled only after the ПН."""
    if doc.doctype not in BASIS_DIRECTION:
        return
    name = frappe.db.exists(PN, {"basis_type": doc.doctype, "basis": doc.name, "docstatus": 1})
    if name:
        frappe.throw(_("Спочатку скасуйте податкову накладну {0}").format(name))


# ---------------------------------------------------------------- register links


def link_registers(pn):
    """Write the ПН name into the VAT register rows of its basis."""
    table = register_of(pn.direction)
    if pn.invoice_kind == KIND_ORDINARY:
        if not pn.basis:
            return
        filters = {"registrar_type": pn.basis_type, "registrar": pn.basis, "event": ("!=", EVENT_ADJUSTMENT)}
    else:
        filters = consolidated_filters(pn.organization, pn.period_from, pn.period_to)
    for name in frappe.get_all(table, filters=filters, pluck="name", limit_page_length=0):
        frappe.db.set_value(table, name, {"tax_invoice_type": PN, "tax_invoice": pn.name}, update_modified=False)


def unlink_registers(doctype, name):
    for table in (vat.LIABILITY, vat.CREDIT):
        frappe.db.sql(
            f"update `tab{table}` set tax_invoice_type = '', tax_invoice = '' "
            "where tax_invoice_type = %s and tax_invoice = %s",
            (doctype, name),
        )


def consolidated_filters(organization, date_from, date_to):
    """Liability rows of buyers who are not VAT payers and have no ПН yet."""
    non_payers = frappe.get_all("UA Counterparty", filters={"vat_payer": 0}, pluck="name", limit_page_length=0)
    return {
        "organization": organization,
        "posting_date": ("between", [getdate(date_from), getdate(date_to)]),
        "counterparty": ("in", non_payers or [""]),
        "event": ("!=", EVENT_ADJUSTMENT),
        "tax_invoice": ("is", "not set"),
    }


# ---------------------------------------------------------------- creation on basis


def _group(rows):
    out = {}
    for r in rows:
        g = out.setdefault(r.vat_rate, [0.0, 0.0])
        g[0] = flt(g[0] + r.base_amount, 2)
        g[1] = flt(g[1] + r.vat_amount, 2)
    return out


def _fit(lines, base, vat_amount):
    """Scale the lines of one rate to the register amounts (a part is covered by an advance)."""
    line_base = flt(sum(l["base_amount"] for l in lines), 2)
    line_vat = flt(sum(l["vat_amount"] for l in lines), 2)
    if line_base == flt(base, 2) and line_vat == flt(vat_amount, 2):
        return lines
    k = flt(base) / line_base if line_base else 0
    left_base, left_vat = flt(base, 2), flt(vat_amount, 2)
    for i, l in enumerate(lines):
        if i == len(lines) - 1:
            new_base, new_vat = left_base, left_vat
        else:
            new_base, new_vat = flt(l["base_amount"] * k, 2), flt(l["vat_amount"] * k, 2)
        l["quantity"] = flt(l["quantity"] * k, 3)
        l["base_amount"], l["vat_amount"] = new_base, new_vat
        left_base, left_vat = flt(left_base - new_base, 2), flt(left_vat - new_vat, 2)
    return lines


def invoice_from_basis(basis):
    """Values for a new ПН made from a submitted basis document."""
    if basis.doctype not in BASIS_DIRECTION:
        frappe.throw(_("Для документа {0} податкова накладна не створюється").format(basis.doctype))
    if basis.docstatus != 1:
        frappe.throw(_("Документ-підстава {0} не проведений").format(basis.name))
    direction = BASIS_DIRECTION[basis.doctype]
    rows = frappe.get_all(
        register_of(direction),
        filters={"registrar_type": basis.doctype, "registrar": basis.name, "event": ("!=", EVENT_ADJUSTMENT)},
        fields=["vat_rate", "base_amount", "vat_amount"],
        order_by="line_no asc",
        limit_page_length=0,
    )
    if not rows:
        frappe.throw(_("Документ {0} не має операцій, що оподатковуються ПДВ: податкова накладна не потрібна").format(basis.name))
    reg = _group(rows)

    lines = []
    if basis.doctype in (SALE, PURCHASE):
        k = flt(basis.exchange_rate) or 1
        by_rate = {}
        for table in ("goods", "services"):
            for row in basis.get(table) or []:
                base = flt((flt(row.total) - flt(row.vat_amount)) * k, 2)
                qty = flt(row.quantity, 3)
                by_rate.setdefault(row.vat_rate, []).append(
                    {
                        "description": row.item_name,
                        "uom": row.uom,
                        "quantity": qty,
                        "price": flt(base / qty, 2) if qty else base,
                        "vat_rate": row.vat_rate,
                        "base_amount": base,
                        "vat_amount": flt(flt(row.vat_amount) * k, 2),
                    }
                )
        for rate, (base, vat_amount) in reg.items():
            if rate in by_rate:
                lines.extend(_fit(by_rate[rate], base, vat_amount))
            else:
                lines.append(_synthetic_line(_("Постачання за документом {0}").format(basis.name), rate, base, vat_amount))
    else:
        text = _("Попередня оплата (аванс)") if direction == ISSUED else _("Попередня оплата постачальнику")
        for rate, (base, vat_amount) in reg.items():
            lines.append(_synthetic_line(text, rate, base, vat_amount))

    return {
        "organization": basis.organization,
        "posting_date": basis.posting_date,
        "direction": direction,
        "invoice_kind": KIND_ORDINARY,
        "counterparty": basis.counterparty,
        "contract": basis.contract,
        "currency": basis.currency,
        "exchange_rate": basis.exchange_rate,
        "basis_type": basis.doctype,
        "basis": basis.name,
        "lines": lines,
    }


def _synthetic_line(description, rate, base, vat_amount):
    return {
        "description": description,
        "quantity": 1,
        "price": flt(base, 2),
        "vat_rate": rate,
        "base_amount": flt(base, 2),
        "vat_amount": flt(vat_amount, 2),
    }


def consolidated_invoice(organization, date_from, date_to, kind):
    if kind == KIND_OWN:
        frappe.throw(_("Зведена накладна на власні потреби: немає операцій-джерел для вибраного періоду"))
    if kind != KIND_NO_PN:
        frappe.throw(_("Невідомий вид зведеної накладної {0}").format(kind))
    date_from, date_to = getdate(date_from), getdate(date_to)
    if date_to < date_from:
        frappe.throw(_("Дата «по» раніше за дату «з»"))
    rows = frappe.get_all(
        vat.LIABILITY,
        filters=consolidated_filters(organization, date_from, date_to),
        fields=["vat_rate", "base_amount", "vat_amount"],
        limit_page_length=0,
    )
    if not rows:
        frappe.throw(_("За період немає постачань покупцям, які не є платниками ПДВ"))
    lines = [
        _synthetic_line(_("Постачання товарів/послуг особам без ІПН за період"), rate, base, vat_amount)
        for rate, (base, vat_amount) in _group(rows).items()
    ]
    return {
        "organization": organization,
        "posting_date": get_last_day(date_to),
        "direction": ISSUED,
        "invoice_kind": kind,
        "period_from": date_from,
        "period_to": date_to,
        "lines": lines,
    }


def effective_lines(pn, exclude=None):
    """Line state of a ПН after its submitted РК: the 'after' values of the last one, else the ПН lines."""
    filters = {"tax_invoice": pn.name, "docstatus": 1}
    if exclude:
        filters["name"] = ("!=", exclude)
    last = frappe.get_all(RK, filters=filters, pluck="name", order_by="creation desc", limit=1)
    if last:
        rows = frappe.get_doc(RK, last[0]).lines
        return [
            {"quantity": r.quantity_after, "price": r.price_after, "base": r.base_after, "vat": r.vat_after}
            for r in rows
        ]
    return [{"quantity": l.quantity, "price": l.price, "base": l.base_amount, "vat": l.vat_amount} for l in pn.lines]


def adjustment_from_invoice(pn):
    if pn.docstatus != 1:
        frappe.throw(_("Податкова накладна {0} не проведена").format(pn.name))
    lines = []
    state = effective_lines(pn)
    for l, s in zip(pn.lines, state):
        lines.append(
            {
                "description": l.description,
                "vat_rate": l.vat_rate,
                "quantity_before": s["quantity"],
                "quantity_after": s["quantity"],
                "price_before": s["price"],
                "price_after": s["price"],
                "base_before": s["base"],
                "base_after": s["base"],
                "vat_before": s["vat"],
                "vat_after": s["vat"],
                "delta_base": 0,
                "delta_vat": 0,
            }
        )
    return {
        "organization": pn.organization,
        "posting_date": pn.posting_date,
        "tax_invoice": pn.name,
        "direction": pn.direction,
        "counterparty": pn.counterparty,
        "contract": pn.contract,
        "reason": "Зміна ціни",
        "lines": lines,
    }


# ---------------------------------------------------------------- ЄРПН status


def tax_doctype_of(name):
    for doctype in (PN, RK):
        if frappe.db.exists(doctype, name):
            return doctype
    frappe.throw(_("Документ {0} не знайдено").format(name), frappe.DoesNotExistError)


def set_status(name, status, reg_number=None, reg_date=None, doctype=None):
    doctype = doctype or tax_doctype_of(name)
    if doctype not in (PN, RK):
        frappe.throw(_("Недопустимий тип документа"))
    frappe.has_permission(doctype, "write", throw=True)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    if status not in STATUSES:
        frappe.throw(_("Невідомий статус ЄРПН {0}").format(status))
    if doc.docstatus != 1:
        frappe.throw(_("Статус ЄРПН задають для проведеного документа"))
    if doc.erpn_status == STATUS_REGISTERED and status != STATUS_REGISTERED:
        frappe.throw(_("Зареєстрований документ не можна повернути до іншого статусу: його виправляють розрахунком коригування"))
    values = {"erpn_status": status, "erpn_reg_number": "", "erpn_reg_date": None}
    if status == STATUS_REGISTERED:
        reg_number = (reg_number or "").strip()
        if not reg_number or not reg_date:
            frappe.throw(_("Для статусу «Зареєстровано» вкажіть номер і дату реєстрації"))
        reg_date = getdate(reg_date)
        if reg_date < getdate(doc.posting_date):
            frappe.throw(_("Дата реєстрації не може бути раніше за дату документа"))
        if frappe.db.exists(
            doctype,
            {
                "organization": doc.organization,
                "erpn_reg_number": reg_number,
                "name": ("!=", doc.name),
                "docstatus": ("<", 2),
            },
        ):
            frappe.throw(_("Номер реєстрації {0} вже використано").format(reg_number))
        values.update(erpn_reg_number=reg_number, erpn_reg_date=reg_date)
    doc.db_set(values)
    doc.add_comment("Info", _("Статус ЄРПН: {0}").format(status))
    return frappe.get_doc(doctype, name).as_dict()


# ---------------------------------------------------------------- register of ПН


def register_data(organization, date_from, date_to, direction=None, erpn_status=None, counterparty=None):
    for doctype in (PN, RK):
        frappe.has_permission(doctype, "read", throw=True)
    date_from, date_to = getdate(date_from), getdate(date_to)
    rows = []
    for doctype in (PN, RK):
        filters = {"docstatus": 1, "posting_date": ("between", [date_from, date_to])}
        if organization:
            filters["organization"] = organization
        if direction:
            filters["direction"] = direction
        if erpn_status:
            filters["erpn_status"] = erpn_status
        if counterparty:
            filters["counterparty"] = counterparty
        if doctype == PN:
            fields = ["name", "number", "posting_date", "direction", "counterparty", "total_base", "total_vat", "total_amount"]
        else:
            fields = ["name", "number", "posting_date", "direction", "counterparty", "total_delta_base", "total_delta_vat"]
        fields += ["erpn_status", "erpn_reg_number"]
        for r in frappe.get_all(doctype, filters=filters, fields=fields, order_by="posting_date asc, name asc", limit_page_length=0):
            if doctype == PN:
                base, vat_amount, total = r.total_base, r.total_vat, r.total_amount
            else:
                base, vat_amount = r.total_delta_base, r.total_delta_vat
                total = flt(base + vat_amount, 2)
            rows.append(
                {
                    "name": r.name,
                    "doctype": doctype,
                    "number": r.number,
                    "date": str(r.posting_date),
                    "direction": r.direction,
                    "counterparty": r.counterparty,
                    "base": flt(base, 2),
                    "vat": flt(vat_amount, 2),
                    "total": flt(total, 2),
                    "erpn_status": r.erpn_status,
                    "erpn_reg_number": r.erpn_reg_number,
                }
            )
    rows.sort(key=lambda r: (r["date"], r["name"]))
    totals = {k: flt(sum(r[k] for r in rows), 2) for k in ("base", "vat", "total")}
    return {"rows": rows, "totals": totals}


def deadline_of(posting_date):
    return add_days(getdate(posting_date), DEADLINE_DAYS)
