"""Whitelisted methods of the app: ua_accounting.api.<module>.<function>.

tax_invoice, tax_adjustment, vat_return, vat_allocation, registration_limit (T-437).
simplified_tax (T-454: get_tax_system, get_income_book, income_limit_status, calculate_esv, ...).
Functions of the package itself: tax_differences, tax_ledger_balance (T-453); fill_report, set_report_line,
reset_report_line, export_report_xml, reporting_calendar (T-442, defined in regulated_report).
"""
import frappe

from ua_accounting.accounting import tax_ledger
from ua_accounting.api.regulated_report import (  # noqa: F401
    export_report_xml,
    fill_report,
    reporting_calendar,
    reset_report_line,
    set_report_line,
)

from ua_accounting.accounting.regulatory import (  # noqa: F401,E402
    get_form_version,
    get_parameter,
    get_release_notes,
)
from ua_accounting.api.simplified_tax import (  # noqa: F401,E402
    calculate_esv,
    export_single_tax_declaration_xml,
    fill_single_tax_declaration,
    get_chart_accounts,
    get_income_book,
    get_tax_system,
    income_limit_status,
)


@frappe.whitelist(methods=["POST"])
def tax_differences(organization, date_from, date_to):
    """Податкові різниці за період; обов'язкові, якщо дохід минулого року більший за 40 млн грн."""
    return tax_ledger.tax_differences(organization, date_from, date_to)


@frappe.whitelist(methods=["POST"])
def tax_ledger_balance(organization, account, date):
    """Сальдо рахунку (Дт - Кт) за БО і ПО на дату."""
    tax_ledger._check_access(organization)
    return tax_ledger.ledger_balance(organization, account, date)
