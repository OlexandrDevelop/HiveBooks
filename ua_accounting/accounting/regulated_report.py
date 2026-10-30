"""Регламентована звітність: balance sheet, income statement, cash flow, profit tax, single tax, ЄСВ.

Every report is a list of lines (code, label, value). `fill` computes them from the ledger
(UA Accounting Entry); lines changed by hand (manual = 1) are kept on re-fill.

Sources: наказ Мінфіну №433 (codes of ф.1, ф.2, ф.3, 1-м, 2-м, 1-мс, 2-мс), ПКУ ст. 134–136 (profit tax),
ст. 291–296 (single tax, group 3), Закон №2464 (ЄСВ 22 %).
spec_gap: the exact line lists of the small forms and the DPS codes of the forms (C_DOC_SUB, version)
must be checked against the official XSD files; they are not in the repository.
"""

import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_last_day, getdate, today

from ua_accounting.accounting import regulatory, tax_xml

DOCTYPE = "UA Regulated Report"
READERS = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager")

BAL, BAL_M, BAL_MS = "Баланс (ф.1)", "Баланс (ф.1-м)", "Баланс (ф.1-мс)"
PL, PL_M, PL_MS = (
    "Звіт про фінансові результати (ф.2)",
    "Звіт про фінансові результати (ф.2-м)",
    "Звіт про фінансові результати (ф.2-мс)",
)
CF = "Звіт про рух грошових коштів (ф.3)"
PROFIT_TAX = "Декларація з податку на прибуток"
SINGLE_TAX = "Декларація платника єдиного податку (3 група)"
ESV = "Звіт ЄСВ (Додаток 4)"

NOT_FILED = "Не подано"
DRAFT, FILLED, EXPORTED = "Чернетка", "Заповнено", "Експортовано"
SINGLE_TAX_SYSTEM = "Єдиний податок, 3 група"

PROFIT_TAX_RATE = 18  # ПКУ ст. 136.1
SINGLE_RATE_VAT, SINGLE_RATE_NO_VAT = 3, 5  # ПКУ ст. 293.3
ESV_RATE = 22  # Закон №2464 ст. 8

CASH = ("30", "31", "33", "34")

LABELS = {
    # form 1: assets
    "1000": "Нематеріальні активи: залишкова вартість",
    "1010": "Незавершені капітальні інвестиції",
    "1011": "Основні засоби: залишкова вартість",
    "1015": "Інвестиційна нерухомість",
    "1020": "Довгострокові біологічні активи",
    "1030": "Довгострокові фінансові інвестиції",
    "1045": "Довгострокова дебіторська заборгованість",
    "1060": "Відстрочені податкові активи",
    "1090": "Інші необоротні активи",
    "1095": "Усього за розділом I",
    "1100": "Запаси",
    "1101": "Виробничі запаси",
    "1102": "Незавершене виробництво",
    "1103": "Товари",
    "1104": "Готова продукція",
    "1110": "Поточні біологічні активи",
    "1125": "Дебіторська заборгованість за товари, роботи, послуги",
    "1135": "Дебіторська заборгованість за розрахунками з бюджетом",
    "1140": "Дебіторська заборгованість за виданими авансами",
    "1145": "Дебіторська заборгованість з нарахованих доходів",
    "1155": "Інша поточна дебіторська заборгованість",
    "1160": "Поточні фінансові інвестиції",
    "1165": "Гроші та їх еквіваленти",
    "1170": "Витрати майбутніх періодів",
    "1190": "Інші оборотні активи",
    "1195": "Усього за розділом II",
    "1200": "Необоротні активи, утримувані для продажу, та групи вибуття",
    "1300": "Баланс (актив)",
    # form 1: liabilities
    "1400": "Зареєстрований (пайовий) капітал",
    "1405": "Капітал у дооцінках",
    "1410": "Додатковий капітал",
    "1415": "Резервний капітал",
    "1420": "Нерозподілений прибуток (непокритий збиток)",
    "1425": "Неоплачений капітал",
    "1430": "Вилучений капітал",
    "1435": "Інші резерви",
    "1495": "Усього за розділом I (пасив)",
    "1500": "Відстрочені податкові зобов'язання",
    "1510": "Довгострокові кредити банків",
    "1515": "Інші довгострокові зобов'язання",
    "1520": "Довгострокові забезпечення",
    "1525": "Цільове фінансування",
    "1595": "Усього за розділом II (пасив)",
    "1600": "Короткострокові кредити банків",
    "1605": "Векселі видані",
    "1610": "Поточна кредиторська заборгованість за довгостроковими зобов'язаннями",
    "1615": "Поточна кредиторська заборгованість за товари, роботи, послуги",
    "1620": "Поточна кредиторська заборгованість за розрахунками з бюджетом",
    "1625": "Поточна кредиторська заборгованість зі страхування",
    "1630": "Поточна кредиторська заборгованість з оплати праці",
    "1635": "Поточна кредиторська заборгованість за одержаними авансами",
    "1640": "Поточна кредиторська заборгованість за розрахунками з учасниками",
    "1660": "Поточні забезпечення",
    "1665": "Доходи майбутніх періодів",
    "1690": "Інші поточні зобов'язання",
    "1695": "Усього за розділом III",
    "1700": "Зобов'язання, пов'язані з необоротними активами, утримуваними для продажу",
    "1900": "Баланс (пасив)",
    # form 2
    "2000": "Чистий дохід від реалізації продукції (товарів, робіт, послуг)",
    "2050": "Собівартість реалізованої продукції (товарів, робіт, послуг)",
    "2090": "Валовий фінансовий результат: прибуток (збиток)",
    "2120": "Інші операційні доходи",
    "2130": "Адміністративні витрати",
    "2150": "Витрати на збут",
    "2180": "Інші операційні витрати",
    "2190": "Фінансовий результат від операційної діяльності: прибуток (збиток)",
    "2200": "Дохід від участі в капіталі",
    "2220": "Інші фінансові доходи",
    "2240": "Інші доходи",
    "2250": "Фінансові витрати",
    "2255": "Втрати від участі в капіталі",
    "2270": "Інші витрати",
    "2280": "Разом доходи",
    "2285": "Разом витрати",
    "2290": "Фінансовий результат до оподаткування: прибуток (збиток)",
    "2300": "Витрати (дохід) з податку на прибуток",
    "2350": "Чистий фінансовий результат: прибуток (збиток)",
    # form 3 (direct method)
    "3000": "Надходження від реалізації продукції (товарів, робіт, послуг)",
    "3005": "Надходження від податкового відшкодування",
    "3010": "Надходження від цільового фінансування",
    "3015": "Надходження авансів від покупців і замовників",
    "3095": "Інші надходження",
    "3100": "Витрачання на оплату товарів (робіт, послуг)",
    "3105": "Витрачання на оплату праці",
    "3110": "Витрачання на відрахування на соціальні заходи",
    "3115": "Витрачання на оплату зобов'язань з податків і зборів",
    "3135": "Витрачання на оплату авансів",
    "3190": "Інші витрачання",
    "3195": "Чистий рух коштів від операційної діяльності",
    "3200": "Надходження від реалізації фінансових інвестицій",
    "3250": "Інші надходження (інвестиційна діяльність)",
    "3255": "Витрачання на придбання фінансових інвестицій",
    "3260": "Витрачання на придбання необоротних активів",
    "3290": "Інші платежі (інвестиційна діяльність)",
    "3295": "Чистий рух коштів від інвестиційної діяльності",
    "3300": "Надходження від власного капіталу",
    "3305": "Надходження від отримання позик",
    "3340": "Інші надходження (фінансова діяльність)",
    "3345": "Погашення позик",
    "3350": "Сплачені дивіденди",
    "3390": "Інші платежі (фінансова діяльність)",
    "3395": "Чистий рух коштів від фінансової діяльності",
    "3400": "Чистий рух грошових коштів за звітний період",
    "3405": "Залишок коштів на початок року",
    "3410": "Вплив зміни валютних курсів на залишок коштів",
    "3415": "Залишок коштів на кінець року",
}

# ---------------------------------------------------------------- balance sheet layout

BAL_SECTIONS = {
    "NC": ["1000", "1010", "1011", "1015", "1020", "1030", "1045", "1060", "1090"],
    "CUR": ["1100", "1101", "1102", "1103", "1104", "1110", "1125", "1135", "1140", "1145", "1155",
            "1160", "1165", "1170", "1190"],
    "HELD": ["1200"],
    "EQ": ["1400", "1405", "1410", "1415", "1420", "1425", "1430", "1435"],
    "LT": ["1500", "1510", "1515", "1520", "1525"],
    "SL": ["1600", "1605", "1610", "1615", "1620", "1625", "1630", "1635", "1640", "1660", "1665", "1690"],
    "HELD_L": ["1700"],
}
INVENTORY = ("1101", "1102", "1103", "1104")
BAL_TOTALS = [("NC", "1095"), ("CUR", "1195"), ("EQ", "1495"), ("LT", "1595"), ("SL", "1695")]

# lines of the small forms (a subset of ф.1; the codes are the same)
SMALL_LINES = {
    BAL_M: {"1000", "1010", "1011", "1090", "1100", "1125", "1135", "1155", "1160", "1165", "1190",
            "1400", "1410", "1415", "1420", "1510", "1515", "1600", "1615", "1620", "1625", "1630", "1635", "1690"},
    BAL_MS: {"1000", "1011", "1125", "1165", "1190", "1400", "1420", "1515", "1615", "1690"},
}
SECTION_FALLBACK = {
    "NC": ["1090", "1011"],
    "CUR": ["1190", "1155"],
    "HELD": ["1190"],
    "EQ": ["1410", "1400"],
    "LT": ["1515", "1690"],
    "SL": ["1690", "1615"],
    "HELD_L": ["1690"],
}

# account prefix -> (line, net). net = the account is a contra account: its credit reduces the line
ASSET_ROUTES = {
    "10": ("1011", False), "11": ("1090", False), "12": ("1000", False), "13": ("1011", True),
    "131": ("1011", True), "132": ("1011", True), "133": ("1000", True), "134": ("1020", True),
    "135": ("1015", True), "14": ("1030", False), "15": ("1010", False), "16": ("1020", False),
    "17": ("1060", False), "18": ("1045", False), "19": ("1090", False),
    "20": ("1101", False), "21": ("1110", False), "22": ("1101", False), "23": ("1102", False),
    "24": ("1102", False), "25": ("1101", False), "26": ("1104", False), "27": ("1101", False),
    "28": ("1103", False), "285": ("1103", True),
    "30": ("1165", False), "31": ("1165", False), "33": ("1165", False), "34": ("1165", False),
    "35": ("1160", False), "36": ("1125", False), "37": ("1155", False), "371": ("1140", False),
    "373": ("1145", False), "38": ("1125", True), "39": ("1170", False),
    "60": ("1155", False), "61": ("1155", False), "62": ("1155", False), "63": ("1140", False),
    "64": ("1135", False), "65": ("1155", False), "66": ("1155", False), "67": ("1155", False),
    "68": ("1155", False),
}
ASSET_DEFAULT = "1190"
LIAB_ROUTES = {
    "36": "1635", "37": "1690", "38": "1690", "47": "1660", "48": "1525", "50": "1510", "51": "1515",
    "52": "1515", "53": "1515", "54": "1500", "55": "1515", "60": "1600", "61": "1610", "62": "1605",
    "63": "1615", "64": "1620", "65": "1625", "66": "1630", "67": "1640", "68": "1690", "681": "1635",
    "69": "1665",
}
LIAB_DEFAULT = "1690"
EQUITY_ROUTES = {"40": "1400", "41": "1405", "42": "1410", "43": "1415", "44": "1420", "45": "1430", "46": "1425"}
EQUITY_DEFAULT = "1435"

# ---------------------------------------------------------------- income statement layout

INCOME_PREFIX = {"2000": "70", "2120": "71", "2200": "72", "2220": "73", "2240": "74"}
EXPENSE_PREFIX = {"2050": ("90", "91"), "2130": ("92",), "2150": ("93",), "2180": ("94",), "2250": ("95",),
                  "2255": ("96",), "2270": ("97", "99"), "2300": ("98",)}
PL_FULL = ["2000", "2050", "2090", "2120", "2130", "2150", "2180", "2190", "2200", "2220", "2240", "2250",
           "2255", "2270", "2290", "2300", "2350"]
PL_SMALL = {
    PL_M: ["2000", "2050", "2090", "2120", "2130", "2150", "2180", "2190", "2240", "2250", "2270", "2290",
           "2300", "2350"],
    PL_MS: ["2000", "2120", "2240", "2280", "2285", "2290", "2300", "2350"],
}

# ---------------------------------------------------------------- cash flow layout

CF_IN_OP = {"681": "3015", "36": "3000", "70": "3000", "64": "3005", "48": "3010"}
CF_IN_INV = {"35": "3200", "14": "3200"}
CF_IN_FIN = {"40": "3300", "41": "3300", "42": "3300", "50": "3305", "60": "3305", "61": "3305"}
CF_OUT_OP = {"63": "3100", "20": "3100", "22": "3100", "26": "3100", "28": "3100", "66": "3105", "65": "3110",
             "64": "3115", "371": "3135"}
CF_OUT_INV = {"10": "3260", "11": "3260", "12": "3260", "14": "3255", "15": "3260", "35": "3255"}
CF_OUT_FIN = {"50": "3345", "60": "3345", "61": "3345", "67": "3350"}
CF_IN_DEFAULT, CF_OUT_DEFAULT = "3095", "3190"
CF_OP_IN = ("3000", "3005", "3010", "3015", "3095")
CF_OP_OUT = ("3100", "3105", "3110", "3115", "3135", "3190")
CF_INV_IN = ("3200", "3250")
CF_INV_OUT = ("3255", "3260", "3290")
CF_FIN_IN = ("3300", "3305", "3340")
CF_FIN_OUT = ("3345", "3350", "3390")


# ---------------------------------------------------------------- ledger helpers


def _prefix(name, table):
    """Value of the longest prefix of the account name found in the table, else None."""
    for n in range(len(name), 0, -1):
        if name[:n] in table:
            return table[name[:n]]
    return None


def _starts(name, prefixes):
    return bool(name) and name.startswith(tuple(prefixes))


def balances(organization, date):
    """{account: Дт - Кт} of all entries up to the date."""
    out = {}
    for side, sign in (("account_dr", 1), ("account_cr", -1)):
        for acc, amount in frappe.db.sql(
            f"""select {side}, coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where organization = %s and posting_date <= %s and {side} is not null and {side} != ''
            group by {side}""",
            (organization, getdate(date)),
        ):
            out[acc] = out.get(acc, 0.0) + sign * flt(amount)
    return out


def turnovers(organization, date_from, date_to, skip_closing=True):
    """{account: Дт - Кт} of the period. Closing entries (accounts 79) are left out, so the result of 70–99
    does not depend on the month closing."""
    out = {}
    extra = " and account_dr not like '79%%' and account_cr not like '79%%'" if skip_closing else ""
    for side, sign in (("account_dr", 1), ("account_cr", -1)):
        for acc, amount in frappe.db.sql(
            f"""select {side}, coalesce(sum(amount), 0) from `tabUA Accounting Entry`
            where organization = %s and posting_date between %s and %s and {side} is not null and {side} != ''
            {extra} group by {side}""",
            (organization, getdate(date_from), getdate(date_to)),
        ):
            out[acc] = out.get(acc, 0.0) + sign * flt(amount)
    return out


def _sum(net, prefixes):
    return sum(v for acc, v in net.items() if _starts(acc, prefixes))


# ---------------------------------------------------------------- income statement


def income_statement(organization, date_from, date_to):
    net = turnovers(organization, date_from, date_to)
    v = {}
    for code, prefix in INCOME_PREFIX.items():
        v[code] = -_sum(net, (prefix,))
    for code, prefixes in EXPENSE_PREFIX.items():
        v[code] = _sum(net, prefixes)
    v["2090"] = v["2000"] - v["2050"]
    v["2190"] = v["2090"] + v["2120"] - v["2130"] - v["2150"] - v["2180"]
    v["2290"] = v["2190"] + v["2200"] + v["2220"] + v["2240"] - v["2250"] - v["2255"] - v["2270"]
    v["2350"] = v["2290"] - v["2300"]
    v["2280"] = v["2000"] + v["2120"] + v["2200"] + v["2220"] + v["2240"]
    v["2285"] = v["2050"] + v["2130"] + v["2150"] + v["2180"] + v["2250"] + v["2255"] + v["2270"]
    return {k: flt(x, 2) for k, x in v.items()}


# ---------------------------------------------------------------- balance sheet


def _resolve(code, section, lines):
    if code in lines:
        return code
    if code in INVENTORY and "1100" in lines:
        return "1100"
    for fb in SECTION_FALLBACK[section]:
        if fb in lines:
            return fb
    return code


def balance_sheet(organization, date_to, kind):
    """{code: value} of the balance on the date. Result accounts 7–9 not yet closed go to line 1420."""
    section_of = {c: s for s, codes in BAL_SECTIONS.items() for c in codes}
    lines = SMALL_LINES.get(kind) or set(section_of)
    bal = balances(organization, date_to)
    v = {code: 0.0 for code in section_of if code in lines}

    def put(code, amount):
        code = _resolve(code, section_of[code], lines)
        v[code] = v.get(code, 0.0) + amount

    open_result = 0.0
    for acc, b in bal.items():
        if abs(b) < 0.005 or acc.startswith("0"):
            continue
        if acc[0] in "789":
            open_result -= b
            continue
        eq = _prefix(acc, EQUITY_ROUTES) if acc[:2] in EQUITY_ROUTES else None
        if eq:
            put(eq, -b)
            continue
        asset = _prefix(acc, ASSET_ROUTES)
        if asset and (asset[1] or b > 0):
            put(asset[0], b)
        elif b > 0:
            put(ASSET_DEFAULT, b)
        else:
            put(_prefix(acc, LIAB_ROUTES) or LIAB_DEFAULT, -b)
    put("1420", open_result)

    inv_in_form = [c for c in INVENTORY if c in lines] if "1100" in lines else []
    if inv_in_form:
        v["1100"] = v.get("1100", 0.0) + sum(v[c] for c in inv_in_form)
    for section, total in BAL_TOTALS:
        v[total] = sum(v.get(c, 0.0) for c in BAL_SECTIONS[section] if c not in (inv_in_form if section == "CUR" else ()))
    v["1300"] = v["1095"] + v["1195"] + v.get("1200", 0.0)
    v["1900"] = v["1495"] + v["1595"] + v["1695"] + v.get("1700", 0.0)
    return {k: flt(x, 2) for k, x in v.items()}


# ---------------------------------------------------------------- cash flow


def cash_flow(organization, date_from, date_to):
    v = {code: 0.0 for code in LABELS if code.startswith("3")}
    rows = frappe.db.sql(
        """select account_dr, account_cr, amount from `tabUA Accounting Entry`
        where organization = %s and posting_date between %s and %s""",
        (organization, getdate(date_from), getdate(date_to)),
        as_dict=True,
    )
    for r in rows:
        dr_cash, cr_cash = _starts(r.account_dr, CASH), _starts(r.account_cr, CASH)
        if dr_cash == cr_cash:
            continue  # not a cash entry, or a transfer between cash accounts
        amount = flt(r.amount)
        if dr_cash:
            counter = r.account_cr or ""
            code = (_prefix(counter, CF_IN_OP) or _prefix(counter, CF_IN_INV) or _prefix(counter, CF_IN_FIN)
                    or CF_IN_DEFAULT)
        else:
            counter = r.account_dr or ""
            code = (_prefix(counter, CF_OUT_OP) or _prefix(counter, CF_OUT_INV) or _prefix(counter, CF_OUT_FIN)
                    or CF_OUT_DEFAULT)
        v[code] += amount
    v["3195"] = sum(v[c] for c in CF_OP_IN) - sum(v[c] for c in CF_OP_OUT)
    v["3295"] = sum(v[c] for c in CF_INV_IN) - sum(v[c] for c in CF_INV_OUT)
    v["3395"] = sum(v[c] for c in CF_FIN_IN) - sum(v[c] for c in CF_FIN_OUT)
    v["3400"] = v["3195"] + v["3295"] + v["3395"]
    opening = balances(organization, add_days(getdate(date_from), -1))
    v["3405"] = _sum(opening, CASH)
    v["3410"] = 0.0
    v["3415"] = v["3400"] + v["3405"] + v["3410"]
    return {k: flt(x, 2) for k, x in v.items()}


# ---------------------------------------------------------------- tax returns


def profit_tax(organization, date_from, date_to):
    """{code: value}: 01 result before tax, 02 differences (T-453), 03 object, 04 tax, РІ.<n> appendix rows."""
    from ua_accounting.accounting import tax_ledger

    result = income_statement(organization, date_from, date_to)["2290"]
    extra = tax_ledger.profit_tax_lines(organization, date_from, date_to)
    adjust = flt(extra["02"], 2)
    base = flt(result + adjust, 2)
    values = {"01": result, "02": adjust, "03": base, "04": flt(max(base, 0) * PROFIT_TAX_RATE / 100, 2)}
    labels = {}
    for row in extra["appendix"]:
        values[row["code"]] = flt(row["value"], 2)
        labels[row["code"]] = f"Додаток РІ: {row['kind']} ({row['article']})"
    return values, labels


def _vat_allocator(organization, date_to):
    """Allocate buyer payments to sales invoices (linked invoice first, then the oldest open one of the
    counterparty) and return the VAT inside a payment; a refund takes back the latest allocations."""
    invoices = {}  # counterparty -> list of [date, name, total, vat, open amount]
    for r in frappe.db.sql(
        """select name, counterparty, posting_date, total_amount, vat_total from `tabUA Sales Invoice`
        where organization = %s and docstatus = 1 and posting_date <= %s order by posting_date, name""",
        (organization, getdate(date_to)),
        as_dict=True,
    ):
        invoices.setdefault(r.counterparty, []).append([r.posting_date, r.name, flt(r.total_amount), flt(r.vat_total), flt(r.total_amount)])
    stacks = {}  # counterparty -> [(invoice row, amount)] of payments, for refunds

    def take(row, amount, stack):
        used = min(amount, row[4])
        row[4] -= used
        if used:
            stack.append((row, used))
        return used, (row[3] / row[2] * used if row[2] else 0.0)

    def pay(counterparty, invoice, amount, day):
        # only invoices issued up to the payment date can be paid by it
        rows = [r for r in invoices.get(counterparty, []) if r[0] <= day]
        stack = stacks.setdefault(counterparty, [])
        left, vat = amount, 0.0
        ordered = sorted(rows, key=lambda x: x[1] != invoice)  # the linked invoice first, others by date
        for row in ordered:
            if left <= 0.005:
                break
            used, v = take(row, left, stack)
            left -= used
            vat += v
        return vat

    def refund(counterparty, amount):
        stack = stacks.setdefault(counterparty, [])
        left, vat = amount, 0.0
        while stack and left > 0.005:
            row, used = stack.pop()
            back = min(left, used)
            row[4] += back
            if used > back:
                stack.append((row, used - back))
            left -= back
            vat += row[3] / row[2] * back if row[2] else 0.0
        return vat

    return pay, refund


def single_tax_income(organization, date_from, date_to, vat_payer=False):
    """Money received from buyers (ПКУ ст. 292.3, cash method) from the start of the year.

    A VAT payer does not count VAT in the income (ПКУ ст. 292.11). VAT of a cash document: its own VAT amount
    (advance); else the VAT of the sales invoices it pays (see _vat_allocator). A refund to the buyer takes the
    same VAT back. Payments of earlier years are replayed so that the open amounts of invoices are right.
    """
    year_start = getdate(date_from).replace(month=1, day=1)
    rows = frappe.db.sql(
        """select posting_date, registrar_type, registrar, account_dr, account_cr, amount
        from `tabUA Accounting Entry` where organization = %s and posting_date <= %s
        order by posting_date, creation""",
        (organization, getdate(date_to)),
        as_dict=True,
    )
    docs = {}  # (doctype, name) -> [signed cash amount, posting date], in the order of the ledger
    income = 0.0
    for r in rows:
        sign = 0
        if _starts(r.account_dr, CASH) and not _starts(r.account_cr, CASH) and _starts(r.account_cr, ("36", "681", "70", "71", "74")):
            sign = 1
        elif _starts(r.account_cr, CASH) and not _starts(r.account_dr, CASH) and _starts(r.account_dr, ("36", "681")):
            sign = -1  # money returned to the buyer
        if not sign:
            continue
        if r.posting_date >= year_start:
            income += sign * flt(r.amount)
        entry = docs.setdefault((r.registrar_type, r.registrar), [0.0, r.posting_date])
        entry[0] += sign * flt(r.amount)
    if vat_payer:
        pay, refund = _vat_allocator(organization, date_to)
        for (doctype, name), (signed, day) in docs.items():
            if doctype not in ("UA Cash Receipt", "UA Cash Payment"):
                continue
            fields = ["vat_amount", "exchange_rate", "counterparty"] + (["sales_invoice"] if doctype == "UA Cash Receipt" else [])
            doc = frappe.db.get_value(doctype, name, fields, as_dict=True)
            if not doc:
                continue
            if flt(doc.vat_amount):
                vat = flt(doc.vat_amount) * (flt(doc.exchange_rate) or 1)
                if signed < 0:
                    vat = -vat
            elif signed > 0:
                vat = pay(doc.counterparty, doc.get("sales_invoice"), signed, day)
            else:
                vat = -refund(doc.counterparty, -signed)
            if day >= year_start:
                income -= vat
    return flt(income, 2)


def single_tax(organization, date_from, date_to):
    org = frappe.db.get_value("UA Organization", organization, ["tax_system", "vat_payer"], as_dict=True)
    if org.tax_system != SINGLE_TAX_SYSTEM:
        frappe.throw(_("Декларацію єдиного податку 3 групи подає лише платник єдиного податку 3 групи"))
    income = single_tax_income(organization, date_from, date_to, vat_payer=bool(org.vat_payer))
    rate = SINGLE_RATE_VAT if org.vat_payer else SINGLE_RATE_NO_VAT
    return {"income_total": income, "rate": rate, "tax_amount": flt(max(income, 0) * rate / 100, 2)}


def esv(organization, date_from, date_to):
    """Додаток 4: one pair of lines per employee from the posted payroll, totals."""
    rows = frappe.db.sql(
        """select l.employee, coalesce(sum(l.esv_base), 0) base, coalesce(sum(l.esv), 0) esv
        from `tabUA Payroll Line` l join `tabUA Payroll` p on p.name = l.parent and l.parenttype = 'UA Payroll'
        where p.docstatus = 1 and p.organization = %s and p.month_start between %s and %s
        group by l.employee order by l.employee""",
        (organization, getdate(date_from), getdate(date_to)),
        as_dict=True,
    )
    values, labels = {}, {}
    for r in rows:
        name = frappe.db.get_value("UA Employee", r.employee, "employee_name") or r.employee
        values[f"esv.{r.employee}.base"] = flt(r.base, 2)
        values[f"esv.{r.employee}.sum"] = flt(r.esv, 2)
        labels[f"esv.{r.employee}.base"] = f"{name}: база нарахування ЄСВ"
        labels[f"esv.{r.employee}.sum"] = f"{name}: сума ЄСВ"
    values["esv.total_base"] = flt(sum(r.base for r in rows), 2)
    values["esv.total_sum"] = flt(sum(r.esv for r in rows), 2)
    return values, labels


# ---------------------------------------------------------------- filling


def _label(code, labels=None):
    if labels and code in labels:
        return labels[code]
    return LABELS.get(code) or {
        "01": "Фінансовий результат до оподаткування",
        "02": "Коригування фінансового результату (податкові різниці)",
        "03": "Об'єкт оподаткування",
        "04": "Податок на прибуток (18 %)",
        "income_total": "Дохід за звітний період (наростаючим підсумком з початку року)",
        "rate": "Ставка єдиного податку, %",
        "tax_amount": "Сума єдиного податку",
        "esv.total_base": "Усього: база нарахування ЄСВ",
        "esv.total_sum": "Усього: сума ЄСВ",
    }.get(code, code)


def compute(doc):
    """List of (code, label, value) for the report, in the order of the form."""
    org, d1, d2, kind = doc.organization, doc.period_from, doc.period_to, doc.report_kind
    labels = None
    if kind in (BAL, BAL_M, BAL_MS):
        v = balance_sheet(org, d2, kind)
        order = [c for codes in _bal_order(kind) for c in codes]
    elif kind in (PL, PL_M, PL_MS):
        v = income_statement(org, d1, d2)
        order = PL_SMALL.get(kind) or PL_FULL
    elif kind == CF:
        v = cash_flow(org, d1, d2)
        order = [c for c in LABELS if c.startswith("3")]
    elif kind == PROFIT_TAX:
        v, labels = profit_tax(org, d1, d2)
        order = list(v)
    elif kind == SINGLE_TAX:
        v = single_tax(org, d1, d2)
        order = list(v)
    elif kind == ESV:
        v, labels = esv(org, d1, d2)
        order = list(v)
    else:
        frappe.throw(_("Невідомий вид звіту: {0}").format(kind))
    return [(c, _label(c, labels), v.get(c, 0.0)) for c in order]


def _bal_order(kind):
    lines = SMALL_LINES.get(kind)
    keep = (lambda c: c in lines) if lines else (lambda c: True)
    out = []
    for section, total in BAL_TOTALS[:2]:
        out.append([c for c in BAL_SECTIONS[section] if keep(c)] + [total])
    out.append(([c for c in BAL_SECTIONS["HELD"] if keep(c)]) + ["1300"])
    for section, total in BAL_TOTALS[2:]:
        out.append([c for c in BAL_SECTIONS[section] if keep(c)] + [total])
    out.append([c for c in BAL_SECTIONS["HELD_L"] if keep(c)] + ["1900"])
    return out


def fill(doc):
    """Fill the lines from the ledger. Manual lines keep the value; computed_value always follows the ledger."""
    manual = {r.code: r for r in doc.lines if r.manual}
    computed = compute(doc)
    doc.set("lines", [])
    seen = set()
    for code, label, value in computed:
        row = {"code": code, "label": label, "value": value, "computed_value": value, "manual": 0}
        old = manual.get(code)
        if old:
            row["value"], row["manual"] = flt(old.value, 2), 1
        doc.append("lines", row)
        seen.add(code)
    for code, old in manual.items():
        if code not in seen:
            doc.append("lines", {"code": code, "label": old.label, "value": old.value,
                                 "computed_value": 0, "manual": 1})
    doc.status = FILLED
    doc.save()
    return doc


def line_of(doc, code):
    for row in doc.lines:
        if row.code == code:
            return row
    frappe.throw(_("Рядка {0} немає у звіті").format(code))


# ---------------------------------------------------------------- calendar


def next_working_day(day):
    """ПКУ ст. 49.18.4: a last day that is a day off moves to the next working day (weekends only)."""
    day = getdate(day)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def check_access(organization):
    frappe.only_for(READERS)
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)


def calendar(organization, year):
    """Reports of the year with periods and deadlines; status follows the report document."""
    year = int(year)
    org = frappe.db.get_value("UA Organization", organization, ["tax_system"], as_dict=True)
    single = bool(org) and org.tax_system == SINGLE_TAX_SYSTEM
    plan = []

    def quarterly(kind, long_year=True):
        for month, day in QUARTER_ENDS:
            end = getdate(f"{year}-{month:02d}-{day:02d}")
            days = 60 if (month == 12 and long_year) else 40
            plan.append((kind, getdate(f"{year}-01-01"), end, next_working_day(end + timedelta(days=days))))

    if single:
        quarterly(SINGLE_TAX, long_year=False)
    else:
        quarterly(PROFIT_TAX)
    for kind in (BAL, BAL_M, BAL_MS, PL, PL_M, PL_MS):
        quarterly(kind)
    quarterly(CF)
    for month in range(1, 13):
        start = getdate(f"{year}-{month:02d}-01")
        deadline = next_working_day(add_months(start, 1).replace(day=20))
        plan.append((ESV, start, get_last_day(start), deadline))

    existing = {}
    for r in frappe.get_all(
        DOCTYPE,
        filters={"organization": organization, "period_to": ("between", [f"{year}-01-01", f"{year}-12-31"])},
        fields=["name", "report_kind", "period_to", "status"],
        order_by="modified asc",
    ):
        existing[(r.report_kind, getdate(r.period_to))] = r
    rows = []
    for kind, start, end, deadline in plan:
        rep = existing.get((kind, end))
        rows.append({
            "report_kind": kind,
            "period_from": str(start),
            "period_to": str(end),
            "deadline": str(deadline),
            "status": rep.status if rep else NOT_FILED,
            "report": rep.name if rep else None,
        })
    return rows


# ---------------------------------------------------------------- XML

# (C_DOC, C_DOC_SUB, C_DOC_VER) per report. Profit tax J0100129 and single tax (legal entity, group 3) J0103509
# are from the ДПС register of forms; the other codes and all body tags are spec_gap until the XSD is checked
FORM_CODES = {
    PROFIT_TAX: ("J01", "001", 29),
    SINGLE_TAX: ("J01", "035", 9),
    BAL: ("J09", "001", 7),
    PL: ("J09", "002", 7),
    CF: ("J09", "003", 7),
    BAL_M: ("J09", "011", 7),
    PL_M: ("J09", "012", 7),
    BAL_MS: ("J09", "021", 7),
    PL_MS: ("J09", "022", 7),
    ESV: ("J04", "001", 1),
}

FORM_VERSION_CODES = {
    PROFIT_TAX: "PROFIT_TAX", SINGLE_TAX: "EP3_LEGAL", BAL: "BALANCE_F1",
    PL: "FIN_RESULT_F2", CF: "CASHFLOW_F3", BAL_M: "BALANCE_F1_M",
    PL_M: "FIN_RESULT_F2_M", BAL_MS: "BALANCE_F1_MS", PL_MS: "FIN_RESULT_F2_MS",
    ESV: "ESV",
}


def period_type(d1, d2):
    """ДПС PERIOD_TYPE: 1 month, 2 quarter, 3 half-year, 4 nine months, 5 year."""
    d1, d2 = getdate(d1), getdate(d2)
    months = (d2.year - d1.year) * 12 + d2.month - d1.month + 1
    return {1: 1, 3: 2, 6: 3, 9: 4, 12: 5}.get(months, 1)


SINGLE_TAX_TAGS = {"income_total": "R01G3", "rate": "R02G3", "tax_amount": "R03G3"}
APPENDIX_RE = re.compile(r"^(РІ|ПЗ)\.(\d+)$")


def _tag(code):
    """Body tag of a line; appendix lines (РІ.n, ПЗ.n) get the row tag and are written with ROWNUM."""
    if code in SINGLE_TAX_TAGS:
        return SINGLE_TAX_TAGS[code]
    return "R" + re.sub(r"[^0-9A-Za-z]", "_", str(code)) + "G3"


# appendices of the profit tax return are separate documents linked from the main one
# (C_DOC, C_DOC_SUB, C_DOC_VER); ПЗ = J0111329 matches the register pattern J011NN (J0111305 is «ПЗ до рядка 05»); РІ = J0111829 is in the register of J0100129
APPENDIX_FORMS = {"РІ": ("J01", "118", 29), "ПЗ": ("J01", "113", 29)}
APPENDIX_VERSION_CODES = {"РІ": "PROFIT_TAX_RI", "ПЗ": "PROFIT_TAX_PZ"}


def _document(org, doc, form, sub, version, lines, count, linked=(), fill_date=None, xsd=None):
    """One DECLAR document; returns (filename, content)."""
    d1, d2 = getdate(doc.period_from), getdate(doc.period_to)
    ptype = period_type(d1, d2)
    stan, doc_type, reg, raj, sti = 1, 0, "00", "00", "0000"
    root = tax_xml.new_root(xsd or f"{form}{sub}.xsd")
    head = tax_xml.ET.SubElement(root, "DECLARHEAD")
    for tag, text in (
        ("TIN", org.edrpou or ""), ("C_DOC", form), ("C_DOC_SUB", sub), ("C_DOC_VER", version),
        ("C_DOC_TYPE", doc_type), ("C_DOC_CNT", count), ("C_REG", reg), ("C_RAJ", raj),
        ("PERIOD_MONTH", d2.month), ("PERIOD_TYPE", ptype), ("PERIOD_YEAR", d2.year),
        ("C_STI_ORIG", sti), ("C_DOC_STAN", stan),
    ):
        tax_xml.add(head, tag, text)
    links = tax_xml.ET.SubElement(head, "LINKED_DOCS")
    for n, (lform, lsub, lver, lcount) in enumerate(linked, start=1):
        link = tax_xml.ET.SubElement(links, "DOC", {"NUM": str(n), "TYPE": "1"})
        for tag, text in (("C_DOC", lform), ("C_DOC_SUB", lsub), ("C_DOC_VER", lver), ("C_DOC_TYPE", 0),
                          ("C_DOC_CNT", lcount), ("C_DOC_STAN", 1), ("FILENAME", "")):
            tax_xml.add(link, tag, text)
    tax_xml.add(head, "D_FILL", tax_xml.ddmmyyyy(fill_date or today()))
    tax_xml.add(head, "SOFTWARE", tax_xml.SOFTWARE)
    body = tax_xml.ET.SubElement(root, "DECLARBODY")
    tax_xml.add(body, "HNAME", org.full_name or org.org_name)
    tax_xml.add(body, "HZY", d2.year)
    tax_xml.add(body, "HZP", ptype)
    for code, value in lines:
        m = APPENDIX_RE.match(code)
        if m:
            tax_xml.add(body, "R01G3", tax_xml.money(value), ROWNUM=m.group(2))
        else:
            tax_xml.add(body, _tag(code), tax_xml.money(value))
    # DPS file name: C_REG C_RAJ TIN C_DOC C_DOC_SUB C_DOC_VER C_DOC_STAN C_DOC_CNT C_DOC_TYPE PERIOD_TYPE
    # PERIOD_MONTH PERIOD_YEAR C_STI_ORIG (44 characters; the counter has 8 digits)
    filename = (
        f"{reg}{raj}{(org.edrpou or '').zfill(10)}{form}{sub}{version:02d}{stan}{count:08d}{doc_type:02d}"
        f"{ptype}{d2.month:02d}{d2.year}{sti}.xml"
    )
    return filename, tax_xml.serialize(root)


def export_xml(doc, fill_date=None):
    """ДПС XML (windows-1251): DECLAR / DECLARHEAD / DECLARBODY. Lines are written as R<code>G3.

    Appendix rows (РІ.n, ПЗ.n) go to separate documents of their own form, linked in LINKED_DOCS of the
    main document and returned in `appendices`.
    """
    org = frappe.get_doc("UA Organization", doc.organization)
    form, sub, version = FORM_CODES[doc.report_kind]
    info = regulatory.form_version_info(
        FORM_VERSION_CODES[doc.report_kind], doc.period_from, version,
        f"{form}{sub}{version:02d} v.{version}",
    )
    version = info["version"]
    main_lines, appendix = [], {}
    for row in doc.lines:
        m = APPENDIX_RE.match(row.code)
        if m:
            appendix.setdefault(m.group(1), []).append((row.code, row.value))
        else:
            main_lines.append((row.code, row.value))
    linked, extra = [], []
    for n, (prefix, lines) in enumerate(sorted(appendix.items()), start=2):
        aform, asub, aver = APPENDIX_FORMS[prefix]
        appendix_info = regulatory.form_version_info(
            APPENDIX_VERSION_CODES[prefix], doc.period_from, aver,
            f"{aform}{asub}{aver:02d} v.{aver}",
        )
        aver = appendix_info["version"]
        linked.append((aform, asub, aver, n))
        filename, content = _document(org, doc, aform, asub, aver, lines, n, fill_date=fill_date,
                                      xsd=appendix_info["xsd"])
        extra.append({"filename": filename, "content": content,
                      "xsd_version": appendix_info["schema_version"]})
    filename, content = _document(org, doc, form, sub, version, main_lines, 1, linked, fill_date,
                                  xsd=info["xsd"])
    return {
        "filename": filename,
        "content": content,
        "encoding": "windows-1251",
        "xsd_version": info["schema_version"],
        "appendices": extra,
    }
