"""VAT assistant: tax invoices to issue and to register, deadlines and comparison with the ЄРПН register."""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from ua_accounting.accounting import deadlines as dl
from ua_accounting.accounting import tax
from ua_accounting.accounting.utils import title_of

DIRECTIONS = (tax.ISSUED, tax.RECEIVED)
TOLERANCE = 0.01
# fine for a late registration (ПКУ ст. 120-1): (days late up to, percent of the VAT)
PENALTY_SCALE = ((15, 10), (30, 20), (60, 30))
PENALTY_MAX = 40


def penalty_pct(days_late):
    if days_late <= 0:
        return 0
    for limit, pct in PENALTY_SCALE:
        if days_late <= limit:
            return pct
    return PENALTY_MAX


def _liability_rows(organization, date_from, date_to, payers):
    """Open VAT liability rows of sales (no ПН linked) by sale, for buyers who are (not) VAT payers.

    A sale that has a submitted ПН is not open even if a repost of the register lost the link.
    """
    rows = frappe.db.sql(
        """select l.registrar as basis, min(l.posting_date) as date, l.counterparty, sum(l.base_amount) as base,
        sum(l.vat_amount) as vat from `tabUA VAT Liability Entry` l
        join `tabUA Counterparty` c on c.name = l.counterparty
        where l.organization = %s and l.registrar_type = %s and l.posting_date between %s and %s
        and l.event != %s and coalesce(l.tax_invoice, '') = '' and c.vat_payer = %s
        and not exists (select 1 from `tabUA Tax Invoice` t where t.docstatus = 1 and t.basis_type = l.registrar_type
                        and t.basis = l.registrar)
        group by l.registrar, l.counterparty order by min(l.posting_date), l.registrar""",
        (organization, tax.SALE, date_from, date_to, tax.EVENT_ADJUSTMENT, 1 if payers else 0),
        as_dict=True,
    )
    return rows


def to_issue(organization, date_from, date_to):
    out = []
    for r in _liability_rows(organization, date_from, date_to, True):
        out.append(
            {
                "basis_doctype": tax.SALE, "basis": r.basis, "counterparty": r.counterparty,
                "counterparty_title": title_of("UA Counterparty", r.counterparty), "date": str(r.date),
                "base": flt(r.base, 2), "vat": flt(r.vat, 2), "total": flt(r.base + r.vat, 2),
                "deadline": str(tax.deadline_of(r.date)),
            }
        )
    return out


def consolidated(organization, date_from, date_to):
    rows = _liability_rows(organization, date_from, date_to, False)
    return {
        "base": flt(sum(r.base for r in rows), 2), "vat": flt(sum(r.vat for r in rows), 2), "count": len(rows),
    }


def to_register(organization, date_from, date_to, as_of):
    invoices = frappe.get_all(
        tax.PN,
        filters={
            "organization": organization, "docstatus": 1, "direction": tax.ISSUED,
            "posting_date": ("between", [date_from, date_to]), "erpn_status": ("!=", tax.STATUS_REGISTERED),
        },
        fields=["name", "number", "posting_date", "counterparty", "total_vat", "erpn_status"], limit_page_length=0,
    )
    out = []
    for pn in invoices:
        deadline = tax.deadline_of(pn.posting_date)
        left = date_diff(deadline, as_of)
        late = max(0, -left)
        pct = penalty_pct(late)
        out.append(
            {
                "tax_invoice": pn.name, "number": pn.number, "date": str(pn.posting_date), "counterparty": pn.counterparty,
                "counterparty_title": title_of("UA Counterparty", pn.counterparty),
                "vat": flt(pn.total_vat, 2), "deadline": str(deadline), "days_left": left, "overdue_days": late,
                "erpn_status": pn.erpn_status, "penalty_pct": pct, "penalty": flt(flt(pn.total_vat) * pct / 100, 2),
            }
        )
    out.sort(key=lambda r: (r["deadline"], r["tax_invoice"]))
    return out


def get_status(organization, date_from, date_to, as_of):
    date_from, date_to, as_of = getdate(date_from), getdate(date_to), getdate(as_of)
    declaration, payment = dl.vat_return(date_to)
    return {
        "to_issue": to_issue(organization, date_from, date_to),
        "consolidated": consolidated(organization, date_from, date_to),
        "to_register": to_register(organization, date_from, date_to, as_of),
        "deadlines": {"declaration": str(declaration), "payment": str(payment)},
    }


def _sides(base, vat_amount):
    return {"base": flt(base, 2), "vat": flt(vat_amount, 2)}


def compare_with_erpn(organization, direction, rows, date_from=None, date_to=None):
    """Compare the ЄРПН register (rows) with the registered ПН of the books by number and date."""
    if direction not in DIRECTIONS:
        frappe.throw(_("Невідомий напрям податкових накладних: {0}").format(direction), frappe.ValidationError)
    filters = {"organization": organization, "docstatus": 1, "direction": direction}
    if date_from and date_to:
        filters["posting_date"] = ("between", [getdate(date_from), getdate(date_to)])
    books = {}
    for pn in frappe.get_all(
        tax.PN, filters=filters, fields=["number", "posting_date", "total_base", "total_vat", "erpn_status"], limit_page_length=0
    ):
        books[(str(pn.number), str(pn.posting_date))] = pn
    matched, mismatches, seen = 0, [], set()
    for row in rows or []:
        key = (str(row.get("number")), str(getdate(row.get("date"))))
        theirs = _sides(row.get("base"), row.get("vat"))
        seen.add(key)
        pn = books.get(key)
        if not pn:
            mismatches.append({"kind": "missing_in_books", "number": key[0], "date": key[1], "ours": None, "theirs": theirs})
            continue
        ours = _sides(pn.total_base, pn.total_vat)
        if max(abs(ours["base"] - theirs["base"]), abs(ours["vat"] - theirs["vat"])) > TOLERANCE + 1e-9:
            mismatches.append({"kind": "amount_differs", "number": key[0], "date": key[1], "ours": ours, "theirs": theirs})
        else:
            matched += 1
    for key, pn in sorted(books.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if key not in seen and pn.erpn_status == tax.STATUS_REGISTERED:
            mismatches.append(
                {"kind": "missing_in_erpn", "number": key[0], "date": key[1], "ours": _sides(pn.total_base, pn.total_vat), "theirs": None}
            )
    return {"matched": matched, "mismatches": mismatches}
