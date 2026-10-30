"""Декларація з ПДВ: rows and appendices are filled from the VAT registers."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import tax, vat
from ua_accounting.accounting.documents import vat_info

RET = "UA VAT Return"
ALLOCATION = "UA VAT Allocation"
FORM_VERSION = "J0200126"

# rows of the main part (spec_gap: numbers follow the form J0200123, to verify against the current ДПС form)
TITLES = {
    "1": "Постачання за ставкою 20 % (база)",
    "2": "Постачання за ставкою 0 % (база)",
    "3": "Постачання за іншими ставками (база)",
    "3.7": "Постачання за ставкою 7 % (база)",
    "3.14": "Постачання за ставкою 14 % (база)",
    "6.1": "Податкові зобов'язання за ставкою 20 %",
    "6.3": "Податкові зобов'язання за іншими ставками",
    "6.7": "Податкові зобов'язання за ставкою 7 %",
    "6.14": "Податкові зобов'язання за ставкою 14 %",
    "10.1": "Усього податкових зобов'язань",
    "13": "Податковий кредит за зареєстрованими податковими накладними",
    "15": "Коригування кредиту за розподілом (ст. 198/199)",
    "16": "Усього податкового кредиту",
    "17": "Сума ПДВ до сплати",
    "18": "Від'ємне значення",
}


def _period(doc):
    return {"organization": doc.organization, "posting_date": ("between", [getdate(doc.period_from), getdate(doc.period_to)])}


def registered_names():
    """ПН and РК registered in ЄРПН: name -> registration date (the credit belongs to this period)."""
    out = {}
    for doctype in (tax.PN, tax.RK):
        for r in frappe.get_all(
            doctype,
            filters={"docstatus": 1, "erpn_status": tax.STATUS_REGISTERED},
            fields=["name", "erpn_reg_date", "posting_date"],
            limit_page_length=0,
        ):
            out[r.name] = getdate(r.erpn_reg_date or r.posting_date)
    return out


def _in_period(doc, day):
    return getdate(doc.period_from) <= day <= getdate(doc.period_to)


def fill(doc):
    manual = {str(l.row): l for l in doc.lines if l.manual}
    vals = {}

    def put(row, base, vat_amount):
        if row in manual:
            base, vat_amount = manual[row].base_amount, manual[row].vat_amount
        vals[row] = (flt(base, 2), flt(vat_amount, 2))

    cache = {}
    bases = {"1": 0.0, "2": 0.0, "3.7": 0.0, "3.14": 0.0}
    vats = {"6.1": 0.0, "6.7": 0.0, "6.14": 0.0}
    for r in frappe.get_all(vat.LIABILITY, filters=_period(doc), fields=["vat_rate", "base_amount", "vat_amount"], limit_page_length=0):
        percent, _taxable = vat_info(r.vat_rate, cache)
        if percent == 20:
            base_row, vat_row = "1", "6.1"
        elif percent == 0:
            base_row, vat_row = "2", None
        elif percent in (7, 14):
            base_row, vat_row = f"3.{int(percent)}", f"6.{int(percent)}"
        else:
            frappe.throw(_("Ставка ПДВ {0} не підтримується декларацією").format(r.vat_rate))
        bases[base_row] += flt(r.base_amount)
        if vat_row:
            vats[vat_row] += flt(r.vat_amount)
    put("1", bases["1"], 0)
    put("2", bases["2"], 0)
    for row in ("3.7", "3.14"):
        put(row, bases[row], 0)
    put("3", sum(vals[k][0] for k in ("3.7", "3.14")), 0)
    put("6.1", 0, vats["6.1"])
    for row in ("6.7", "6.14"):
        put(row, 0, vats[row])
    put("6.3", 0, sum(vals[k][1] for k in ("6.7", "6.14")))
    put("10.1", sum(vals[k][0] for k in ("1", "2", "3")), sum(vals[k][1] for k in ("6.1", "6.3")))

    reg = registered_names()
    credit_base = credit_vat = 0.0
    credit_filters = {"organization": doc.organization, "posting_date": ("<=", getdate(doc.period_to))}
    for r in frappe.get_all(vat.CREDIT, filters=credit_filters, fields=["tax_invoice", "base_amount", "vat_amount"], limit_page_length=0):
        if r.tax_invoice and r.tax_invoice in reg and _in_period(doc, reg[r.tax_invoice]):
            credit_base += flt(r.base_amount)
            credit_vat += flt(r.vat_amount)
    put("13", credit_base, credit_vat)
    d5 = d5_rows(doc)
    put("15", 0, -sum(r["vat_amount"] for r in d5))
    put("16", vals["13"][0], vals["13"][1] + vals["15"][1])
    diff = flt(vals["10.1"][1] - vals["16"][1], 2)
    put("17", 0, max(diff, 0))
    put("18", 0, max(-diff, 0))

    doc.set("lines", [])
    for row, (base, vat_amount) in vals.items():
        doc.append(
            "lines",
            {"row": row, "description": _(TITLES[row]), "base_amount": base, "vat_amount": vat_amount, "manual": 1 if row in manual else 0},
        )
    doc.vat_to_pay = vals["17"][1]
    doc.vat_negative = vals["18"][1]
    doc.set("appendix_d1", [])
    for r in d1_rows(doc, reg):
        doc.append("appendix_d1", r)
    doc.set("appendix_d5", [])
    for r in d5:
        doc.append("appendix_d5", r)


def d1_rows(doc, registered):
    """Rows of the appendix Д1 (J0200526): I = issued, not registered at filing (table 1.1/1.2.1);
    II = received, registered in the period but issued earlier (table 2.1)."""
    cp_cache = {}

    def ipn_of(cp):
        if not cp:
            return "Неплатник"
        if cp not in cp_cache:
            row = frappe.db.get_value("UA Counterparty", cp, ["ipn", "edrpou", "vat_payer"], as_dict=True)
            cp_cache[cp] = "Неплатник" if not row or not row.vat_payer else (row.ipn or row.edrpou or "")
        return cp_cache[cp]

    out = []
    for doctype, base_f, vat_f in ((tax.PN, "total_base", "total_vat"), (tax.RK, "total_delta_base", "total_delta_vat")):
        for r in frappe.get_all(
            doctype,
            filters={
                "organization": doc.organization,
                "posting_date": ("<=", getdate(doc.period_to)),
                "docstatus": 1,
            },
            fields=["name", "number", "posting_date", "direction", "counterparty", base_f, vat_f],
            order_by="posting_date asc, name asc",
            limit_page_length=0,
        ):
            section = "I" if r.direction == tax.ISSUED else "II"
            if section == "II":
                # Д1 table 2.1: received ПН registered in this period but issued in an earlier one
                if r.name not in registered or not _in_period(doc, registered[r.name]):
                    continue
                if getdate(r.posting_date) >= getdate(doc.period_from):
                    continue
            elif r.name in registered or not _in_period(doc, getdate(r.posting_date)):
                # Д1 table 1.1: issued ПН/РК of the period that are not registered in ЄРПН at the filing date
                continue
            out.append(
                {
                    "section": section,
                    "tax_invoice_type": doctype,
                    "tax_invoice": r.name,
                    "number": r.number,
                    "date": r.posting_date,
                    "counterparty_ipn": ipn_of(r.counterparty),
                    "base_amount": flt(r.get(base_f), 2),
                    "vat_amount": flt(r.get(vat_f), 2),
                }
            )
    out.sort(key=lambda r: (r["section"], str(r["date"]), r["tax_invoice"]))
    return out


def d5_rows(doc):
    out = []
    for a in frappe.get_all(
        ALLOCATION,
        filters={**_period(doc), "docstatus": 1, "disallowed_credit": (">", 0)},
        fields=["name", "disallowed_credit", "taxable_share"],
        limit_page_length=0,
    ):
        out.append(
            {
                "description": _("Розподіл ПДВ, ст. 198/199 ПКУ ({0}): частка оподатковуваних операцій {1} %").format(a.name, a.taxable_share),
                "base_amount": 0,
                "vat_amount": flt(a.disallowed_credit, 2),
            }
        )
    return out


def summary(doc):
    rows = {str(l.row): l for l in doc.lines}

    def v(row, field):
        return flt(rows[row].get(field), 2) if row in rows else 0.0

    def plain(rows_):
        return [
            {
                "section": r.section,
                "tax_invoice": r.tax_invoice,
                "number": r.number,
                "date": str(r.date) if r.date else "",
                "counterparty_ipn": r.counterparty_ipn,
                "base_amount": flt(r.base_amount, 2),
                "vat_amount": flt(r.vat_amount, 2),
            }
            for r in rows_
        ]

    return {
        "liability_base": v("10.1", "base_amount"),
        "liability_vat": v("10.1", "vat_amount"),
        "credit_vat": v("16", "vat_amount"),
        "to_pay": v("17", "vat_amount"),
        "negative": v("18", "vat_amount"),
        "d1_rows": plain(doc.appendix_d1),
        "d5_rows": [
            {"description": r.description, "base_amount": flt(r.base_amount, 2), "vat_amount": flt(r.vat_amount, 2)}
            for r in doc.appendix_d5
        ],
    }
