"""Статистична звітність малих підприємств: 1-підприємництво (коротка) — квартальна, 1-ПВ — місячна.

Lines are filled from the ledger where a source exists; the others (number of employees, payroll fund)
are typed by hand and kept on re-fill.
spec_gap: the row layout and the schema codes of the Держстат forms must be checked with the official schemas;
the semantic line codes below are the contract of the app.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate, today

from ua_accounting.accounting import regulated_report as rr
from ua_accounting.accounting import tax_xml

DOCTYPE = "UA Statistical Report"
F_ENTERPRISE, F_PV = "1-підприємництво (коротка)", "1-ПВ"
DRAFT, FILLED, EXPORTED = "Чернетка", "Заповнено", "Експортовано"

# form -> (C_DOC, C_DOC_SUB, C_DOC_VER, schema version, months in the period)
FORMS = {
    F_ENTERPRISE: ("S01", "002", 3, "S0100203 v.1", 3),
    F_PV: ("S03", "001", 3, "S0300103 v.1", 1),
}

LINES = {
    F_ENTERPRISE: [
        ("revenue", "Чистий дохід від реалізації продукції (без ПДВ)"),
        ("cost_of_sales", "Собівартість реалізованої продукції"),
        ("employees_avg", "Середня кількість працівників"),
    ],
    F_PV: [
        ("employees_avg", "Середньооблікова кількість працівників"),
        ("payroll_fund", "Фонд оплати праці"),
    ],
}


def check_period(doc):
    if doc.form not in FORMS:
        frappe.throw(_("Невідома форма {0}").format(doc.form))
    d1, d2 = getdate(doc.period_from), getdate(doc.period_to)
    months = FORMS[doc.form][4]
    start_ok = d1 == get_first_day(d1) and (d1.month - 1) % months == 0
    if months == 3:
        end_ok = d2 == get_last_day(d1.replace(month=d1.month + 2))
    else:
        end_ok = d2 == get_last_day(d1)
    if not (start_ok and end_ok):
        frappe.throw(
            _("Період форми {0} має бути {1}").format(doc.form, _("календарним кварталом") if months == 3 else _("календарним місяцем"))
        )


def compute(doc):
    """{code: value} that come from the ledger (Kt 70 and Dt 90 turnover of the period)."""
    net = rr.turnovers(doc.organization, doc.period_from, doc.period_to)
    if doc.form == F_ENTERPRISE:
        return {"revenue": flt(-rr._sum(net, ("70",)), 2), "cost_of_sales": flt(rr._sum(net, ("90",)), 2)}
    return {}


def fill(doc):
    """Lines of the form; computed_value follows the ledger, manual lines keep the typed value."""
    manual = {r.code: r for r in doc.lines if r.manual}
    values = compute(doc)
    doc.set("lines", [])
    for code, label in LINES[doc.form]:
        computed = flt(values.get(code, 0.0), 2)
        row = {"code": code, "label": label, "value": computed, "computed_value": computed, "manual": 0}
        if code in manual:
            row["value"], row["manual"] = flt(manual[code].value, 2), 1
        doc.append("lines", row)
    doc.status = FILLED
    doc.save()
    return doc


def export_xml(doc, fill_date=None):
    """DPS-style DECLAR (windows-1251). The file is built from the saved lines."""
    if doc.status == DRAFT:
        frappe.throw(_("Спочатку заповніть звіт"))
    org = frappe.get_doc("UA Organization", doc.organization)
    form, sub, version, schema, _months = FORMS[doc.form]
    d2 = getdate(doc.period_to)
    ptype = rr.period_type(doc.period_from, doc.period_to)
    reg, raj, stan, count, doc_type, sti = "00", "00", 1, 1, 0, "0000"
    root = tax_xml.new_root(f"{form}{sub}.xsd")
    head = tax_xml.ET.SubElement(root, "DECLARHEAD")
    for tag, text in (
        ("TIN", org.edrpou or ""), ("C_DOC", form), ("C_DOC_SUB", sub), ("C_DOC_VER", version),
        ("C_DOC_TYPE", doc_type), ("C_DOC_CNT", count), ("C_REG", reg), ("C_RAJ", raj),
        ("PERIOD_MONTH", d2.month), ("PERIOD_TYPE", ptype), ("PERIOD_YEAR", d2.year),
        ("C_STI_ORIG", sti), ("C_DOC_STAN", stan),
    ):
        tax_xml.add(head, tag, text)
    tax_xml.add(head, "D_FILL", tax_xml.ddmmyyyy(fill_date or today()))
    tax_xml.add(head, "SOFTWARE", tax_xml.SOFTWARE)
    body = tax_xml.ET.SubElement(root, "DECLARBODY")
    tax_xml.add(body, "HNAME", org.full_name or org.org_name)
    tax_xml.add(body, "HZY", d2.year)
    tax_xml.add(body, "HZP", ptype)
    for row in doc.lines:
        tax_xml.add(body, row.code.upper(), tax_xml.money(row.value))
    filename = (
        f"{reg}{raj}{(org.edrpou or '').zfill(10)}{form}{sub}{version:02d}{stan}{count:08d}{doc_type:02d}"
        f"{ptype}{d2.month:02d}{d2.year}{sti}.xml"
    )
    return {"filename": filename, "xml": tax_xml.serialize(root), "schema_version": schema}
