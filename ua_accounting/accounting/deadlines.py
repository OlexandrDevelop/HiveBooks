"""Deadlines of taxes and reports (ПКУ) for the accountant calendar and the helpers.

A last day on a Saturday or a Sunday moves to the next Monday (ПКУ ст. 49.18.4).
Public holidays are not known here and are ignored.
"""

import calendar

from frappe.utils import add_days, add_months, getdate

MONTHS = (
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
)

VAT_DECL = "VAT_DECL"
VAT_PAY = "VAT_PAY"
CIT_DECL = "CIT_DECL"
CIT_PAY = "CIT_PAY"
SINGLE_DECL = "SINGLE_DECL"
SINGLE_PAY = "SINGLE_PAY"
ESV_REPORT = "ESV_REPORT"


def move_weekend(day):
    """Saturday and Sunday move to the next Monday."""
    day = getdate(day)
    return add_days(day, {5: 2, 6: 1}.get(day.weekday(), 0))


def month_end(year, month):
    return getdate(f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}")


def month_title(year, month):
    return f"{MONTHS[month - 1]} {year}"


def quarter_title(year, quarter):
    return f"{quarter} квартал {year}"


def nominal_20(period_end):
    """The 20th of the month that follows the period."""
    nxt = add_months(getdate(period_end).replace(day=1), 1)
    return nxt.replace(day=20)


def vat_return(period_end):
    """(filing day, payment day) of the VAT return of a month (ст. 203.1, 203.2).

    The payment is counted from the nominal 20th, not from the moved filing day.
    """
    nominal = nominal_20(period_end)
    return move_weekend(nominal), move_weekend(add_days(nominal, 10))


def quarter_return(period_end):
    """(filing day, payment day) of the profit tax or the single tax of a quarter.

    The 4th quarter is the annual return: the year end + 60 days (ст. 49.18.2), else + 40 days.
    """
    period_end = getdate(period_end)
    nominal = add_days(period_end, 60 if period_end.month == 12 else 40)
    return move_weekend(nominal), move_weekend(add_days(nominal, 10))


def esv_report(period_end):
    return move_weekend(nominal_20(period_end))


def quarter_of(day):
    return (getdate(day).month - 1) // 3 + 1


def quarter_end(year, quarter):
    return month_end(year, quarter * 3)
