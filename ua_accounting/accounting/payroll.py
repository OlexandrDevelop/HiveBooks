"""Payroll rules: working time, dated rates, average pay (vacation, sick leave), taxes of a pay line.

Amounts are Decimal inside and floats at the border. Rounding is to kopecks, half up.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import add_months, get_first_day, get_last_day, getdate

SALARY = "Оклад"
PREMIUM = "Премія"
SICK = "Лікарняні"
VACATION = "Відпускні"
CIVIL = "ЦПХ"
INPUT_TYPES = (PREMIUM, CIVIL)  # the amount is typed by the user
PERIOD_TYPES = (SICK, VACATION)
ESV_HISTORY_TYPES = (SALARY, PREMIUM)  # pay that makes the average of the vacation pay
SICK_HISTORY_TYPES = (SALARY, PREMIUM, VACATION)  # pay that makes the average of the sick pay

CONTRACT_LABOR = "Трудовий договір"
CONTRACT_CIVIL = "Цивільно-правовий договір"
STATUS_WORKS = "Працює"
STATUS_FIRED = "Звільнений"

VACATION_DAYS_IN_MONTH = Decimal("29.3")  # Постанова КМУ №100
SICK_EMPLOYER_DAYS = 5  # Закон 1105-XIV: the first 5 days are paid by the employer

ONE_KOPECK = Decimal("0.01")


# ---------------------------------------------------------------- numbers


def D(value):
    return Decimal(str(value or 0))


def q2(value):
    return D(value).quantize(ONE_KOPECK, rounding=ROUND_HALF_UP)


def pct(amount, rate):
    return q2(D(amount) * D(rate))


def rates_for(day):
    """Dated legal values of the day (UA Regulatory Parameter): rates in fractions, amounts in UAH."""
    from ua_accounting.accounting.regulatory import parameter_row

    def value(code):
        return D(parameter_row(code, day).value)

    return {
        "min_wage": value("MIN_WAGE"), "psp": value("PSP"), "psp_limit": value("PSP_LIMIT"),
        "pdfo": value("PDFO_RATE") / 100, "military_levy": value("VZ_RATE") / 100,
        "esv": value("ESV_RATE") / 100, "esv_max_factor": value("ESV_MAX_BASE_MULT"),
    }


# ---------------------------------------------------------------- working time


def working_days(days_per_week, start, end):
    """Number of working days between two dates (both included). 5 days: Monday to Friday."""
    start, end = getdate(start), getdate(end)
    count, day = 0, start
    while day <= end:
        if day.weekday() < int(days_per_week or 5):
            count += 1
        day += timedelta(days=1)
    return count


def month_bounds(day):
    first = get_first_day(getdate(day))
    return first, get_last_day(first)


def employee_info(employee):
    info = frappe.db.get_value(
        "UA Employee",
        employee,
        [
            "name", "person", "employee_name", "organization", "department", "salary", "hire_date", "dismissal_date",
            "status", "contract_type", "insured_years", "psp_applies", "work_schedule",
        ],
        as_dict=True,
    )
    if not info:
        frappe.throw(_("Співробітника {0} не знайдено").format(employee))
    info.days_per_week = (
        frappe.db.get_value("UA Work Schedule", info.work_schedule, "days_per_week") if info.work_schedule else 0
    ) or 5
    return info


def salary_changes(employee):
    """[(date, new salary, salary before)] from the submitted hiring and transfer documents."""
    rows = []
    for r in frappe.get_all(
        "UA Staff Transfer",
        filters={"employee": employee, "docstatus": 1},
        fields=["transfer_date", "new_salary", "old_salary"],
    ):
        rows.append((getdate(r.transfer_date), D(r.new_salary), D(r.old_salary)))
    for r in frappe.get_all(
        "UA Hiring", filters={"employee": employee, "docstatus": 1}, fields=["start_date", "salary"]
    ):
        rows.append((getdate(r.start_date), D(r.salary), None))
    rows.sort(key=lambda x: x[0])
    return rows


def salary_on(card_salary, changes, day):
    """Salary of an employee on a day. Without HR documents it is the salary of the card."""
    if not changes:
        return D(card_salary)
    day = getdate(day)
    current = None
    for date, new, _old in changes:
        if date <= day:
            current = new
    if current is not None:
        return current
    first = changes[0]
    return first[2] if first[2] is not None else first[1]


def timesheet_days(organization, employee, month_start):
    """Worked days of the submitted timesheet of the month, or None when there is no row."""
    row = frappe.db.sql(
        """select r.worked_days from `tabUA Timesheet Row` r
        join `tabUA Timesheet` t on t.name = r.parent and r.parenttype = 'UA Timesheet'
        where t.docstatus = 1 and t.organization = %s and t.month_start = %s and r.employee = %s
        order by t.creation desc limit 1""",
        (organization, month_start, employee),
    )
    return D(row[0][0]) if row else None


def month_salary(emp, organization, month_start):
    """(amount, worked days, norm days) of the salary of one month."""
    first, last = month_bounds(month_start)
    norm = working_days(emp.days_per_week, first, last)
    if not norm:
        return D(0), D(0), D(0)
    start = max(first, getdate(emp.hire_date)) if emp.hire_date else first
    end = min(last, getdate(emp.dismissal_date)) if emp.dismissal_date else last
    changes = salary_changes(emp.name)
    worked_input = timesheet_days(organization, emp.name, first)
    if start > end:
        return D(0), D(0), D(norm)
    points = sorted({start} | {d for d, _n, _o in changes if start < d <= end})
    total, worked = D(0), 0
    for i, point in enumerate(points):
        seg_end = points[i + 1] - timedelta(days=1) if i + 1 < len(points) else end
        days = working_days(emp.days_per_week, point, seg_end)
        total += salary_on(emp.salary, changes, point) * days / norm
        worked += days
    if worked_input is not None:
        # the timesheet days are limited to the employed part of the month; the pay keeps the salary split
        days = min(worked_input, D(worked))
        return q2(total * days / worked if worked else 0), days, D(norm)
    return q2(total), D(worked), D(norm)


# ---------------------------------------------------------------- average pay


def pay_of_months(organization, employee, month_starts, types):
    """{month start: accrued sum} of the submitted payrolls for the given accrual types."""
    rows = frappe.db.sql(
        """select p.month_start, coalesce(sum(l.amount), 0) from `tabUA Payroll Line` l
        join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %(org)s and l.employee = %(emp)s
        and p.month_start in %(months)s and l.accrual_type in %(types)s group by p.month_start""",
        {"org": organization, "emp": employee, "months": tuple(month_starts), "types": tuple(types)},
    )
    return {getdate(m): D(s) for m, s in rows}


def employed_days(emp, first, last):
    """Calendar days of the month while the employee was employed."""
    start = max(first, getdate(emp.hire_date)) if emp.hire_date else first
    end = min(last, getdate(emp.dismissal_date)) if emp.dismissal_date else last
    return max((end - start).days + 1, 0)


def vacation_average(emp, organization, period_from):
    """Average pay of a calendar day: pay of 2 full months before the vacation / 29,3 per month."""
    start = get_first_day(getdate(period_from))
    months = [add_months(start, -2), add_months(start, -1)]
    pay = pay_of_months(organization, emp.name, months, ESV_HISTORY_TYPES)
    total, days = D(0), D(0)
    for first in months:
        last = get_last_day(first)
        month_days = (last - first).days + 1
        worked = employed_days(emp, first, last)
        if not worked:
            continue
        days += VACATION_DAYS_IN_MONTH * worked / month_days
        total += pay.get(first, D(0))
    if total > 0 and days > 0:
        return q2(total / days)
    # no pay in the calculation period: the salary of the card
    return q2(salary_on(emp.salary, salary_changes(emp.name), period_from) / VACATION_DAYS_IN_MONTH)


def sick_average(emp, organization, period_from):
    """Average pay of a calendar day: pay of 6 months before the illness / their calendar days."""
    start = get_first_day(getdate(period_from))
    months = [add_months(start, -i) for i in range(6, 0, -1)]
    pay = pay_of_months(organization, emp.name, months, SICK_HISTORY_TYPES)
    total, days = D(0), 0
    for first in months:
        last = get_last_day(first)
        worked = employed_days(emp, first, last)
        if not worked:
            continue
        days += worked
        total += pay.get(first, D(0))
    if total > 0 and days > 0:
        return q2(total / days)
    last = get_last_day(start)
    return q2(salary_on(emp.salary, salary_changes(emp.name), period_from) / ((last - start).days + 1))


def sick_percent(insured_years):
    """Percent of the average pay by the insured years (Закон 1105-XIV)."""
    years = D(insured_years)
    if years < 3:
        return Decimal(50)
    if years < 5:
        return Decimal(60)
    if years < 8:
        return Decimal(70)
    return Decimal(100)


def sick_amounts(emp, organization, period_from, period_to, insured_years):
    """(average day, whole amount, employer part, ФСС part)."""
    days = (getdate(period_to) - getdate(period_from)).days + 1
    average = sick_average(emp, organization, period_from)
    per_day = q2(average * sick_percent(insured_years or emp.insured_years) / 100)
    employer_days = min(days, SICK_EMPLOYER_DAYS)
    employer = q2(per_day * employer_days)
    fss = q2(per_day * (days - employer_days))
    return average, employer + fss, employer, fss


# ---------------------------------------------------------------- taxes


def calculate_taxes(rows, emp, organization, month_start, doc_name):
    """ПДФО, військовий збір, ЄСВ and the net of the pay lines of one employee (rows are Payroll Line docs).

    ПСП: once a month, only if the income of the month is not above the limit. The ЄСВ base is limited to
    15 minimum wages a month. A full month of salary on the main job gets at least the ЄСВ of the minimum wage.
    """
    rate = rates_for(month_start)
    prior = frappe.db.sql(
        """select coalesce(sum(l.amount), 0), coalesce(sum(l.psp), 0), coalesce(sum(l.esv_base), 0)
        from `tabUA Payroll Line` l join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %s and p.month_start = %s and l.employee = %s and p.name != %s""",
        (organization, month_start, emp.name, doc_name or ""),
    )[0]
    prior_gross, prior_psp, prior_base = (D(x) for x in prior)
    labor = emp.contract_type != CONTRACT_CIVIL
    psp_left = D(0)
    if emp.psp_applies and labor and prior_gross + sum(D(r.amount) for r in rows) <= rate["psp_limit"]:
        psp_left = max(rate["psp"] - prior_psp, D(0))
    base_left = max(rate["esv_max_factor"] * rate["min_wage"] - prior_base, D(0))
    total_base = prior_base
    for row in rows:
        gross = D(row.amount)
        psp = min(psp_left, gross)
        psp_left -= psp
        base = D(row.employer_part) if row.accrual_type == SICK else gross
        base = min(base, base_left)
        base_left -= base
        total_base += base
        row.psp = float(psp)
        row.pdfo = float(pct(gross - psp, rate["pdfo"]))
        row.military_levy = float(pct(gross, rate["military_levy"]))
        row.esv_base = float(base)
        row.esv = float(pct(base, rate["esv"]))
        row.net = float(gross - D(row.pdfo) - D(row.military_levy))
    full_salary = [r for r in rows if r.accrual_type == SALARY and D(r.norm_days) and r.worked_days == r.norm_days]
    if full_salary and labor and not emp.psp_applies and total_base < rate["min_wage"]:
        row = full_salary[0]
        row.esv_base = float(D(row.esv_base) + rate["min_wage"] - total_base)
        row.esv = float(pct(row.esv_base, rate["esv"]))


# ---------------------------------------------------------------- payments


def payroll_due(payroll, exclude_payment=None):
    """{employee: net amount still unpaid} of a payroll."""
    due = {}
    for r in frappe.get_all("UA Payroll Line", filters={"parent": payroll, "parenttype": "UA Payroll"},
                            fields=["employee", "net"]):
        due[r.employee] = due.get(r.employee, D(0)) + D(r.net)
    paid = frappe.db.sql(
        """select r.employee, sum(r.amount) from `tabUA Salary Payment Line` r
        join `tabUA Salary Payment` s on s.name = r.parent and r.parenttype = 'UA Salary Payment'
        where s.docstatus = 1 and s.payroll = %s and s.name != %s group by r.employee""",
        (payroll, exclude_payment or ""),
    )
    for employee, amount in paid:
        due[employee] = due.get(employee, D(0)) - D(amount)
    return due
