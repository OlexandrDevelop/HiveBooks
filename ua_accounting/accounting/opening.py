"""Assistant of the opening balances: sections of the chart and the subconto each account needs."""

import frappe
from frappe import _

# section -> accounts. Only leaf accounts that exist in the chart are shown.
SECTIONS = {
    "Основні засоби": ["100", "101", "102", "103", "104", "105", "106", "107", "108", "109", "111", "112", "113", "114",
                       "115", "116", "117", "131", "132", "152", "153"],
    "Нематеріальні активи": ["121", "122", "123", "124", "125", "127", "133", "154"],
    "Запаси": ["201", "202", "203", "204", "205", "206", "207", "208", "209", "211", "212", "213", "214", "215", "22",
               "25", "26", "27", "281", "282", "283", "284", "285", "286"],
    "Каса": ["301", "302"],
    "Банківські рахунки": ["311", "312", "313", "314", "315", "316", "321", "322", "323", "324", "331", "332", "333",
                           "334", "335"],
    "Розрахунки з покупцями": ["361", "362", "363", "364", "681"],
    "Розрахунки з постачальниками": ["371", "631", "632", "633"],
    "Підзвітні особи": ["372"],
    "Розрахунки з працівниками": ["661", "662", "663", "672", "376"],
    "Розрахунки з бюджетом": ["641", "642", "643", "644", "651", "652", "653", "654", "655"],
    "Розрахунки з засновниками": ["46", "671"],
    "Капітал": ["401", "402", "403", "404", "411", "412", "413", "414", "421", "422", "423", "424", "425", "43", "441",
               "442", "443", "451", "452", "453"],
    "Кредити і позики": ["501", "502", "505", "506", "601", "602", "605", "606", "684", "685"],
}

# the subconto of these sections may be filled later (1C also allows a loan balance without the lender)
SUBCONTO_OPTIONAL = ("Кредити і позики",)

TECHNICAL_ACCOUNT = "ТЕХ"  # counter-account of the assistant
ACTIVE, PASSIVE = "А", "П"
# active-passive accounts: the side of the balance when the row does not tell it
DEBIT_BY_DEFAULT = ("442", "443")


def account_info(code):
    """Account settings and the subconto types of one account, or None."""
    acc = frappe.db.get_value(
        "UA Account", code, ["account_type", "is_group", "off_balance", "currency_accounting", "quantity_accounting"],
        as_dict=True)
    if not acc or acc.is_group or acc.off_balance:
        return None
    acc.subconto = frappe.db.sql(
        """select s.subconto_type, s.turnover_only, t.reference_doctype, t.is_dynamic
        from `tabUA Account Subconto` s left join `tabUA Subconto Type` t on t.name = s.subconto_type
        where s.parent = %s and s.parenttype = 'UA Account' order by s.idx""",
        code, as_dict=True)
    return acc


def section_of(account):
    for section, codes in SECTIONS.items():
        if account in codes:
            return section
    return None


@frappe.whitelist(methods=["GET"])
def get_sections():
    """Sections of the assistant with accounts and their subconto types."""
    frappe.has_permission("UA Opening Balances", "read", throw=True)
    result = []
    for section, codes in SECTIONS.items():
        accounts = []
        for code in codes:
            acc = account_info(code)
            if not acc:
                continue
            kinds = [s for s in acc.subconto if not s.turnover_only and not s.is_dynamic and s.reference_doctype]
            accounts.append({
                "account": code,
                "name": frappe.db.get_value("UA Account", code, "account_name"),
                "account_type": acc.account_type,
                "subconto_types": [s.subconto_type for s in kinds],
                "subconto_doctypes": [s.reference_doctype for s in kinds],
                "quantity": acc.quantity_accounting,
                "currency": acc.currency_accounting,
            })
        result.append({"section": section, "accounts": accounts, "subconto_optional": section in SUBCONTO_OPTIONAL})
    return result


def row_subconto(row, acc, section):
    """{subconto type: value} of one row. Checks the types and the required values."""
    values = {}
    for i in (1, 2, 3):
        doctype, value = row.get(f"subconto{i}_type"), row.get(f"subconto{i}")
        if not value:
            continue
        kind = next((s for s in acc.subconto if s.reference_doctype == doctype and not s.is_dynamic), None)
        if not kind or kind.turnover_only:
            frappe.throw(_("Рядок {0}: рахунок {1} не має субконто {2}").format(row.idx, row.account, doctype))
        values[kind.subconto_type] = value
    if section not in SUBCONTO_OPTIONAL:
        for s in acc.subconto:
            if not s.turnover_only and not s.is_dynamic and s.reference_doctype and s.subconto_type not in values:
                frappe.throw(_("Рядок {0}: вкажіть субконто {1} рахунку {2}").format(
                    row.idx, _(s.reference_doctype), row.account))
    return values
