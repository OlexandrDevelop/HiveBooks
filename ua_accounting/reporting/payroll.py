"""Payroll reports: розрахунковий листок, звіт по нарахуваннях, Додаток 4ДФ (data and XML of the ДПС format)."""

import xml.etree.ElementTree as ET
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from ua_accounting.accounting import payroll as calc

SIGN_SALARY = "101"  # ознака доходу: заробітна плата
SIGN_CIVIL = "102"  # ознака доходу: виплати за цивільно-правовими договорами

# header of the ДПС file of the combined report (Додаток 4ДФ)
C_DOC, C_DOC_SUB, C_DOC_VER = "F01", "034", "5"
PERIOD_QUARTER = "2"


def check_access(organization):
    if not organization:
        frappe.throw(_("Вкажіть організацію"))
    frappe.has_permission("UA Payroll", "read", throw=True)
    frappe.has_permission("UA Organization", "read", organization, throw=True)


def money(value):
    return float(calc.q2(value))


# ---------------------------------------------------------------- розрахунковий листок


def payslip_rows(organization, employee, month_start):
    first = calc.month_bounds(month_start)[0]
    lines = frappe.db.sql(
        """select l.accrual_type, sum(l.amount) amount, sum(l.pdfo) pdfo, sum(l.military_levy) military_levy,
        sum(l.esv) esv, sum(l.net) net from `tabUA Payroll Line` l
        join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %s and p.month_start = %s and l.employee = %s
        group by l.accrual_type order by min(l.idx)""",
        (organization, first, employee),
        as_dict=True,
    )
    if not lines:
        return []
    paid = frappe.db.sql(
        """select coalesce(sum(r.amount), 0) from `tabUA Salary Payment Line` r
        join `tabUA Salary Payment` s on s.name = r.parent and r.parenttype = 'UA Salary Payment'
        join `tabUA Payroll` p on p.name = s.payroll
        where s.docstatus = 1 and p.organization = %s and p.month_start = %s and r.employee = %s""",
        (organization, first, employee),
    )[0][0]
    rows = [{"section": _("Нараховано"), "item": _(l.accrual_type), "amount": money(l.amount)} for l in lines]
    rows.append({"section": _("Утримано"), "item": _("ПДФО"), "amount": money(sum(l.pdfo for l in lines))})
    rows.append({"section": _("Утримано"), "item": _("Військовий збір"),
                 "amount": money(sum(l.military_levy for l in lines))})
    rows.append({"section": _("Нараховано роботодавцем"), "item": _("ЄСВ"), "amount": money(sum(l.esv for l in lines))})
    rows.append({"section": _("До виплати"), "item": _("До виплати"), "amount": money(sum(l.net for l in lines))})
    rows.append({"section": _("Виплачено"), "item": _("Виплачено"), "amount": money(paid)})
    return rows


# ---------------------------------------------------------------- звіт по нарахуваннях


def accrual_rows(organization, date_from, date_to):
    accrued = frappe.db.sql(
        """select l.employee, sum(l.amount) accrued, sum(l.pdfo) pdfo, sum(l.military_levy) military_levy,
        sum(l.esv) esv, sum(l.net) net from `tabUA Payroll Line` l
        join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %s and p.posting_date between %s and %s group by l.employee""",
        (organization, date_from, date_to),
        as_dict=True,
    )
    paid = dict(
        frappe.db.sql(
            """select r.employee, sum(r.amount) from `tabUA Salary Payment Line` r
            join `tabUA Salary Payment` s on s.name = r.parent and r.parenttype = 'UA Salary Payment'
            where s.docstatus = 1 and s.organization = %s and s.posting_date between %s and %s group by r.employee""",
            (organization, date_from, date_to),
        )
    )
    by = {r.employee: r for r in accrued}
    for employee in paid:
        by.setdefault(employee, frappe._dict(accrued=0, pdfo=0, military_levy=0, esv=0, net=0))
    names = dict(frappe.get_all("UA Employee", filters={"name": ("in", list(by) or [""])},
                                fields=["name", "employee_name"], as_list=True))
    rows = []
    for employee in sorted(by, key=lambda e: names.get(e) or e):
        r = by[employee]
        rows.append(
            {
                "employee": employee,
                "accrued": money(r.accrued),
                "pdfo": money(r.pdfo),
                "military_levy": money(r.military_levy),
                "esv": money(r.esv),
                "net": money(r.net),
                "paid": money(paid.get(employee)),
                "to_pay": money(calc.D(r.net) - calc.D(paid.get(employee))),
            }
        )
    return rows


# ---------------------------------------------------------------- Додаток 4ДФ


def quarter_bounds(year, quarter):
    year, quarter = cint(year), cint(quarter)
    if not 1 <= quarter <= 4 or not 2000 <= year <= 2100:
        frappe.throw(_("Вкажіть рік і квартал (1–4)"))
    first = date(year, 3 * quarter - 2, 1)
    return first, calc.month_bounds(date(year, 3 * quarter, 1))[1]


def form_4df_rows(organization, year, quarter):
    first, last = quarter_bounds(year, quarter)
    accrued = frappe.db.sql(
        """select l.employee, sum(l.amount) income_accrued, sum(l.pdfo) pdfo_accrued,
        sum(l.military_levy) military_levy, sum(l.esv_base) esv_base, sum(l.esv) esv
        from `tabUA Payroll Line` l join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %s and p.month_start between %s and %s group by l.employee""",
        (organization, first, last),
        as_dict=True,
    )
    income_paid, withheld = _paid_in_period(organization, first, last)
    by = {r.employee: r for r in accrued}
    for employee in set(income_paid) | set(withheld):
        # a payment of an earlier quarter without accruals in this one
        by.setdefault(
            employee,
            frappe._dict(employee=employee, income_accrued=0, pdfo_accrued=0, military_levy=0, esv_base=0, esv=0),
        )
    if not by:
        return []
    cards = {
        c.name: c
        for c in frappe.get_all(
            "UA Employee",
            filters={"name": ("in", list(by))},
            fields=["name", "employee_name", "ipn", "contract_type", "hire_date", "dismissal_date"],
        )
    }
    rows = []
    for r in by.values():
        card = cards[r.employee]
        hired, fired = card.hire_date, card.dismissal_date
        rows.append(
            {
                "employee": r.employee,
                "ipn": card.ipn or "",
                "income_accrued": money(r.income_accrued),
                "income_paid": money(income_paid.get(r.employee)),
                "pdfo_accrued": money(r.pdfo_accrued),
                "pdfo_withheld": money(withheld.get(r.employee)),
                "military_levy": money(r.military_levy),
                "esv_base": money(r.esv_base),
                "esv": money(r.esv),
                "income_sign": SIGN_CIVIL if card.contract_type == calc.CONTRACT_CIVIL else SIGN_SALARY,
                "hire_date": str(hired) if hired and first <= getdate(hired) <= last else "",
                "dismissal_date": str(fired) if fired and first <= getdate(fired) <= last else "",
            }
        )
    rows.sort(key=lambda x: (x["ipn"], x["employee"]))
    return rows


def _paid_in_period(organization, first, last):
    """Income paid and ПДФО withheld at the payments of the period (a payment is a share of the net of its payroll)."""
    payments = frappe.db.sql(
        """select s.payroll, r.employee, sum(r.amount) amount from `tabUA Salary Payment Line` r
        join `tabUA Salary Payment` s on s.name = r.parent and r.parenttype = 'UA Salary Payment'
        where s.docstatus = 1 and s.organization = %s and s.posting_date between %s and %s
        group by s.payroll, r.employee""",
        (organization, first, last),
        as_dict=True,
    )
    income, tax = {}, {}
    for p in payments:
        gross, pdfo, net = frappe.db.sql(
            """select coalesce(sum(amount), 0), coalesce(sum(pdfo), 0), coalesce(sum(net), 0)
            from `tabUA Payroll Line` where parent = %s and parenttype = 'UA Payroll' and employee = %s""",
            (p.payroll, p.employee),
        )[0]
        if not net:
            continue
        share = calc.D(p.amount) / calc.D(net)
        income[p.employee] = income.get(p.employee, calc.D(0)) + calc.D(gross) * share
        tax[p.employee] = tax.get(p.employee, calc.D(0)) + calc.D(pdfo) * share
    return income, tax


def _amount(value):
    return f"{calc.q2(value):.2f}"


def _date(value):
    return getdate(value).strftime("%d%m%Y") if value else ""


@frappe.whitelist(methods=["GET"])
def export_4df_xml(organization, year, quarter):
    """XML of the Додаток 4ДФ for the quarter (root DECLAR, head and body)."""
    check_access(organization)
    rows = form_4df_rows(organization, year, quarter)
    if not rows:
        frappe.throw(_("За цей квартал немає нарахувань зарплати"))
    missing = [r["employee"] for r in rows if not r["ipn"]]
    if missing:
        names = [frappe.db.get_value("UA Employee", e, "employee_name") or e for e in missing]
        frappe.throw(_("Не вказано ІПН: {0}").format(", ".join(names)))
    org = frappe.db.get_value("UA Organization", organization, ["edrpou", "full_name"], as_dict=True)
    year = cint(year)
    last_month = 3 * cint(quarter)

    root = ET.Element("DECLAR")
    head = ET.SubElement(root, "DECLARHEAD")
    for tag, value in (
        ("TIN", org.edrpou or ""),
        ("C_DOC", C_DOC),
        ("C_DOC_SUB", C_DOC_SUB),
        ("C_DOC_VER", C_DOC_VER),
        ("C_DOC_TYPE", "0"),
        ("C_DOC_CNT", "1"),
        ("PERIOD_MONTH", str(last_month)),
        ("PERIOD_TYPE", PERIOD_QUARTER),
        ("PERIOD_YEAR", str(year)),
        ("D_FILL", getdate(today()).strftime("%d%m%Y")),
        ("SOFTWARE", "ua_accounting"),
    ):
        ET.SubElement(head, tag).text = value
    body = ET.SubElement(root, "DECLARBODY")
    ET.SubElement(body, "HNAME").text = org.full_name or ""
    ET.SubElement(body, "HZY").text = str(year)
    ET.SubElement(body, "HZKV").text = str(cint(quarter))
    totals = {k: calc.D(0) for k in ("income_accrued", "income_paid", "pdfo_accrued", "pdfo_withheld", "military_levy",
                                      "esv_base", "esv")}
    for number, r in enumerate(rows, start=1):
        row = ET.SubElement(body, "T1RXXXXG1", {"ROWNUM": str(number)})
        ET.SubElement(row, "TIN").text = r["ipn"]
        ET.SubElement(row, "INCOME_ACCRUED").text = _amount(r["income_accrued"])
        ET.SubElement(row, "INCOME_PAID").text = _amount(r["income_paid"])
        ET.SubElement(row, "PDFO_ACCRUED").text = _amount(r["pdfo_accrued"])
        ET.SubElement(row, "PDFO_WITHHELD").text = _amount(r["pdfo_withheld"])
        ET.SubElement(row, "MILITARY_LEVY").text = _amount(r["military_levy"])
        ET.SubElement(row, "ESV_BASE").text = _amount(r["esv_base"])
        ET.SubElement(row, "ESV").text = _amount(r["esv"])
        ET.SubElement(row, "INCOME_SIGN").text = r["income_sign"]
        if r["hire_date"]:
            ET.SubElement(row, "DATE_HIRE").text = _date(r["hire_date"])
        if r["dismissal_date"]:
            ET.SubElement(row, "DATE_DISMISSAL").text = _date(r["dismissal_date"])
        for k in totals:
            totals[k] += calc.D(r[k])
    ET.SubElement(body, "R01G1").text = str(len(rows))
    for tag, key in (("R01G2", "income_accrued"), ("R01G3", "income_paid"), ("R01G4", "pdfo_accrued"),
                     ("R01G5", "pdfo_withheld"), ("R01G6", "military_levy"), ("R01G7", "esv_base"), ("R01G8", "esv")):
        ET.SubElement(body, tag).text = _amount(totals[key])
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
