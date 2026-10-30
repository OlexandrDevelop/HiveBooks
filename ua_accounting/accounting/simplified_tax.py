"""Simplified tax system (спрощена система): policy rules, Книга обліку доходів, income limit, ЄСВ, declaration.

Dated legal values are read from UA Regulatory Parameter (MIN_WAGE, ESV_RATE, EP_LIMIT_G*_MULT ...).
The income book is filled on submit of UA Cash Receipt (cash method, ПКУ 292.1).
spec_gap: the DPS form codes of the single tax declaration are not in the repository; the body tags follow the
pattern of the other forms in regulated_report and must be checked against the XSD.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.utils import flt, get_last_day, getdate

from ua_accounting.accounting.utils import first_of_month, next_names, std_columns
from ua_accounting.accounting_policy import policy_for

READERS = ("UA Accountant", "UA Accounting Manager", "UA Chief Accountant", "System Manager")

BOOK = "UA Income Book Entry"
DECLARATION = "UA Single Tax Declaration"
GENERAL = "Загальна система"
G1, G2, G3, G4 = (f"Єдиний податок, {n} група" for n in (1, 2, 3, 4))
FOP, LEGAL = "ФОП", "Юридична особа"
FULL_CHART, SIMPLE_CHART = "Загальний", "Спрощений (малі підприємства)"
OP_BUYER = "Оплата від покупця"

LIMIT_CODE = {G1: "EP_LIMIT_G1_MULT", G2: "EP_LIMIT_G2_MULT", G3: "EP_LIMIT_G3_MULT"}
FIXED_MAX_PCT = {G1: 10, G2: 20}  # ПКУ 293.1: % of the living minimum (G1) / minimum wage (G2)
PERIODS = {"Q1": 3, "H1": 6, "9M": 9, "Y": 12}
ORDER = ["Q1", "H1", "9M", "Y"]
INCOME_FIELDS = [
    "posting_date", "period", "registrar_type", "registrar", "line_no", "organization",
    "income_amount", "vat_amount", "document_description", "content",
]

# leaf accounts of the simplified chart of small enterprises (Наказ №291, малі підприємства)
SIMPLE_CHART_ACCOUNTS = frozenset("""
101 102 103 104 105 106 107 108 109 111 112 113 114 115 116 117 121 122 125 131 132 133 134 135
201 202 203 204 205 206 207 208 209 22 23 24 26 281 282 283 284 285 286 301 302 311 312 331 332
361 362 363 364 371 372 373 374 375 376 377 401 402 403 404 411 412 421 422 425 441 442 443
631 632 633 641 642 643 644 651 652 653 654 655 661 662 663 671 672 681 682 683 684 685 69
701 702 703 704 705 711 712 713 714 715 716 717 718 719 741 742 744 745 746 791 792 793 794
901 902 903 904 91 92 93 940 941 942 943 944 945 946 947 948 949 951 952 961 962 963 971 972 973 974 975 976 977
981 982 991 992 993
""".split())


def money(value):
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_single(tax_system):
    return bool(tax_system) and tax_system.startswith("Єдиний податок")


def check_access(organization=None):
    frappe.only_for(READERS)
    if organization:
        frappe.has_permission("UA Organization", "read", doc=organization, throw=True)


# ---------------------------------------------------------------- parameters


def parameter(code, date):
    """Value of a dated legal parameter valid on `date`."""
    from ua_accounting.accounting.regulatory import parameter_row

    return flt(parameter_row(code, date).value)


# ---------------------------------------------------------------- policy


def rate_of(tax_system, vat_payer):
    """ПКУ 293.2: group 3 pays 3 % when the payer is a VAT payer, otherwise 5 %."""
    if tax_system == G3:
        return 3 if vat_payer else 5
    return None


def validate_policy(doc):
    system = doc.tax_system or GENERAL
    if system in (G1, G2):
        if doc.taxpayer_type != FOP:
            frappe.throw(_("Групи 1 і 2 єдиного податку доступні лише для ФОП (ПКУ 291.4)"))
        if doc.vat_payer:
            frappe.throw(_("Платники єдиного податку 1 і 2 груп не можуть бути платниками ПДВ (ПКУ 291.4)"))
        limit = FIXED_MAX_PCT[system]
        if flt(doc.fixed_rate_pct) < 0 or flt(doc.fixed_rate_pct) > limit:
            base = "прожиткового мінімуму" if system == G1 else "мінімальної зарплати"
            frappe.throw(_("Ставка {0} не може бути більшою за {1} % {2} (ПКУ 293.1)").format(system, limit, base))
        if not flt(doc.fixed_rate_pct):
            # an empty or zero rate is not a choice: the maximum rate is saved and shown
            doc.fixed_rate_pct = limit
    doc.single_tax_rate = rate_of(system, doc.vat_payer)


def get_policy_data(organization, date):
    policy = policy_for(organization, date)
    if policy:
        return {
            "tax_system": policy.tax_system or GENERAL,
            "taxpayer_type": policy.taxpayer_type or LEGAL,
            "vat_payer": policy.vat_payer,
            "single_tax_rate": policy.single_tax_rate,
            "fixed_rate_pct": policy.fixed_rate_pct,
            "chart_variant": policy.chart_variant or FULL_CHART,
            "policy": policy.name,
        }
    org = frappe.db.get_value("UA Organization", organization, ["tax_system", "vat_payer"], as_dict=True)
    system = (org.tax_system if org else None) or GENERAL
    return {
        "tax_system": system, "taxpayer_type": LEGAL, "vat_payer": org.vat_payer if org else 0,
        "single_tax_rate": rate_of(system, org.vat_payer if org else 0), "fixed_rate_pct": None,
        "chart_variant": FULL_CHART, "policy": None,
    }


@frappe.whitelist(methods=["POST"])
def get_tax_system(organization, date):
    """Tax system, taxpayer type, VAT payer, rate and chart variant valid on the date."""
    frappe.has_permission("UA Organization", "read", doc=organization, throw=True)
    return get_policy_data(organization, date)


# ---------------------------------------------------------------- income book


def post_income(doc):
    """Cash receipt from a buyer: income of a single-tax payer on the day the money is received."""
    if doc.operation_type != OP_BUYER:
        return
    if not is_single(get_policy_data(doc.organization, doc.posting_date)["tax_system"]):
        return
    vat = doc.vat_uah
    income = money(doc.amount_uah - vat)
    buyer = doc.counterparty and frappe.db.get_value("UA Counterparty", doc.counterparty, "counterparty_name")
    description = f"{doc.doc_title} {doc.name} від {getdate(doc.posting_date).strftime('%d.%m.%Y')}"
    if buyer:
        description += f", {buyer}"
    row = {
        "posting_date": getdate(doc.posting_date), "period": first_of_month(doc.posting_date),
        "registrar_type": doc.doctype, "registrar": doc.name, "line_no": 1, "organization": doc.organization,
        "income_amount": income, "vat_amount": vat, "document_description": description[:140],
        "content": doc.content_text(),
    }
    std = std_columns()
    name = next_names(BOOK, 1)[0]
    frappe.db.bulk_insert(BOOK, ["name"] + INCOME_FIELDS + list(std), [[name] + [row[f] for f in INCOME_FIELDS] + list(std.values())])


def cancel_income(doc):
    frappe.db.delete(BOOK, {"registrar_type": doc.doctype, "registrar": doc.name})


def income_between(organization, date_from, date_to):
    value = frappe.db.sql(
        """select coalesce(sum(income_amount), 0) from `tabUA Income Book Entry`
        where organization = %s and posting_date between %s and %s""",
        (organization, getdate(date_from), getdate(date_to)),
    )[0][0]
    return flt(value, 2)


@frappe.whitelist(methods=["POST"])
def get_income_book(organization, date_from, date_to):
    """Книга обліку доходів (Наказ Мінфіну №579): rows, total and income per quarter."""
    check_access(organization)
    rows = frappe.get_all(
        BOOK, filters={"organization": organization, "posting_date": ("between", [date_from, date_to])},
        fields=["posting_date", "document_description", "registrar_type", "registrar", "income_amount"],
        order_by="posting_date asc, name asc", limit_page_length=0,
    )
    quarters = {q: 0.0 for q in (1, 2, 3, 4)}
    for row in rows:
        row["posting_date"] = str(row["posting_date"])
        row["income_amount"] = flt(row["income_amount"], 2)
        quarters[(getdate(row["posting_date"]).month - 1) // 3 + 1] += row["income_amount"]
    return {
        "rows": rows,
        "total_income": flt(sum(r["income_amount"] for r in rows), 2),
        "quarters": [{"quarter": q, "income": flt(v, 2)} for q, v in quarters.items()],
    }


# ---------------------------------------------------------------- income limit


@frappe.whitelist(methods=["POST"])
def income_limit_status(organization, date):
    """Limit of the annual income of the group (ПКУ 291.4) and the income since 1 January."""
    check_access(organization)
    date = getdate(date)
    system = get_policy_data(organization, date)["tax_system"]
    out = {"tax_system": system, "limit": None, "income_ytd": 0.0, "remaining": None, "exceeded": False}
    if system not in LIMIT_CODE:
        return out
    jan1 = date.replace(month=1, day=1)
    limit = flt(parameter(LIMIT_CODE[system], jan1) * parameter("MIN_WAGE", jan1), 2)
    income = income_between(organization, jan1, date)
    out.update(limit=limit, income_ytd=income, remaining=flt(limit - income, 2), exceeded=income > limit)
    return out


# ---------------------------------------------------------------- ЄСВ


@frappe.whitelist(methods=["POST"])
def calculate_esv(organization, year, quarter):
    """ЄСВ for a ФОП: minimum wage x rate for every month of the quarter, also when there is no income."""
    check_access(organization)
    year, quarter = int(year), int(quarter)
    if quarter not in (1, 2, 3, 4):
        frappe.throw(_("Квартал має бути від 1 до 4"))
    months = []
    for month in range(3 * quarter - 2, 3 * quarter + 1):
        first = getdate(f"{year}-{month:02d}-01")
        if get_policy_data(organization, get_last_day(first))["taxpayer_type"] != FOP:
            continue
        base, rate = parameter("MIN_WAGE", first), parameter("ESV_RATE", first)
        months.append({"month": month, "base": base, "rate": rate, "amount": money(base * rate / 100)})
    return {"months": months, "total": flt(sum(m["amount"] for m in months), 2)}


# ---------------------------------------------------------------- declaration


def _fixed_months(organization, year, system):
    """(single tax, ВЗ) of groups 1, 2: a fixed amount for every month the payer is in the group."""
    jan1 = getdate(f"{year}-01-01")
    tax = vz = 0.0
    for month in range(1, 13):
        data = get_policy_data(organization, get_last_day(getdate(f"{year}-{month:02d}-01")))
        if data["tax_system"] != system:
            continue
        pct = flt(data["fixed_rate_pct"]) or FIXED_MAX_PCT[system]
        base = parameter("LIVING_MINIMUM" if system == G1 else "MIN_WAGE", jan1)
        tax += money(base * pct / 100)
        vz += money(parameter("MIN_WAGE", jan1) * parameter("VZ_FOP_FIXED_PCT", jan1) / 100)
    return money(tax), money(vz)


def _group3_tax(organization, date_from, date_to):
    """Group 3 tax of the income since 1 January: every day's income keeps the rate valid on that day."""
    rows = frappe.db.sql(
        """select posting_date, sum(income_amount) from `tabUA Income Book Entry`
        where organization = %s and posting_date between %s and %s group by posting_date""",
        (organization, getdate(date_from), getdate(date_to)),
    )
    rates, total = {}, Decimal(0)
    for day, amount in rows:
        policy = policy_for(organization, day)
        key = policy.name if policy else None
        if key not in rates:
            rates[key] = Decimal(str(flt(get_policy_data(organization, day)["single_tax_rate"])))
        total += Decimal(str(amount or 0)) * rates[key] / 100
    return money(total)


def _previous(organization, year, period):
    """Single tax and ВЗ of the latest submitted declaration of an earlier period of the year."""
    for earlier in reversed(ORDER[: ORDER.index(period)]):
        row = frappe.db.get_value(
            DECLARATION, {"organization": organization, "year": year, "period": earlier, "docstatus": 1},
            ["single_tax_accrued", "vz_accrued"], as_dict=True,
        )
        if row:
            return flt(row.single_tax_accrued, 2), flt(row.vz_accrued, 2)
    return 0.0, 0.0


def calculate_declaration(organization, year, period):
    if period not in PERIODS:
        frappe.throw(_("Період має бути Q1, H1, 9M або Y"))
    year = int(year)
    end = get_last_day(getdate(f"{year}-{PERIODS[period]:02d}-01"))
    data = get_policy_data(organization, end)
    system = data["tax_system"]
    if not is_single(system):
        frappe.throw(_("Організація на дату {0} не є платником єдиного податку").format(end))
    if system in (G1, G2) and period != "Y":
        frappe.throw(_("Платники 1 і 2 груп подають лише річну декларацію (ПКУ 296.2)"))
    if system == G4:
        frappe.throw(_("Декларація 4 групи не підтримується"))
    jan1 = getdate(f"{year}-01-01")
    income = income_between(organization, jan1, end)
    if system == G3:
        rate = flt(data["single_tax_rate"])
        accrued = _group3_tax(organization, jan1, end)
        vz = money(Decimal(str(income)) * Decimal(str(parameter("VZ_FOP_G3_RATE", jan1))) / 100) if data["taxpayer_type"] == FOP else 0.0
    else:
        rate = flt(data["fixed_rate_pct"]) or FIXED_MAX_PCT[system]
        accrued, vz = _fixed_months(organization, year, system)
    prev_tax, prev_vz = _previous(organization, year, period)
    limit = income_limit_status(organization, end)
    return {
        "year": year, "period": period, "posting_date": end, "tax_system": system,
        "taxpayer_type": data["taxpayer_type"], "income_total": income, "tax_rate": rate,
        "single_tax_accrued": accrued, "single_tax_previous": prev_tax,
        "single_tax_payable": money(accrued - prev_tax), "vz_accrued": vz, "vz_payable": money(vz - prev_vz),
        "income_limit_exceeded": 1 if limit["exceeded"] else 0,
    }


@frappe.whitelist(methods=["POST"])
def fill_single_tax_declaration(organization, year, period):
    """Create the declaration of the period, or refresh its draft. Returns the name."""
    check_access(organization)
    values = calculate_declaration(organization, year, period)
    name = frappe.db.get_value(
        DECLARATION, {"organization": organization, "year": values["year"], "period": period, "docstatus": 0}
    )
    doc = frappe.get_doc(DECLARATION, name) if name else frappe.new_doc(DECLARATION)
    doc.organization = organization
    doc.update(values)
    doc.save()
    return doc.name


def declaration_entries(doc):
    """Legal entity: Дт 981 Кт 641 with the tax to pay. A ФОП has no entries."""
    if doc.taxpayer_type != LEGAL or flt(doc.single_tax_payable) <= 0:
        return []
    doc._ctx = {}
    sub = {"TaxType": "SINGLE"}
    return [doc.entry("981", "641", doc.single_tax_payable, None, sub)]


# DPS form (C_DOC, C_DOC_SUB, C_DOC_VER): legal entity J0103509 as in regulated_report; ФОП codes are spec_gap
FORMS = {LEGAL: ("J01", "035", 9), FOP: ("F01", "033", 9)}


@frappe.whitelist(methods=["POST"])
def export_single_tax_declaration_xml(name):
    from ua_accounting.accounting import regulated_report, regulatory, tax_xml

    check_access()
    doc = frappe.get_doc(DECLARATION, name)
    doc.check_permission("read")
    org = frappe.get_doc("UA Organization", doc.organization)
    form, sub, version = FORMS[doc.taxpayer_type or LEGAL]
    end = getdate(doc.posting_date)
    # the version comes from the form register by the START of the reporting period (T-458)
    info = regulatory.form_version_info(
        "EP3_LEGAL" if doc.taxpayer_type == LEGAL else "EP3_FOP", f"{doc.year or end.year}-01-01", version,
        f"{form}{sub} v.{version}")
    version = info["version"]
    root = tax_xml.new_root(info["xsd"])
    tax_xml.header(root, org, form, sub, version, getdate(frappe.utils.today()), end.month, end.year, 1)
    ptype = regulated_report.period_type(f"{end.year}-01-01", end)
    root.find("DECLARHEAD/PERIOD_TYPE").text = str(ptype)
    body = tax_xml.ET.SubElement(root, "DECLARBODY")
    tax_xml.add(body, "HNAME", org.full_name or org.org_name)
    tax_xml.add(body, "HZY", end.year)
    tax_xml.add(body, "HZP", ptype)
    for tag, value in (
        ("R01G3", doc.income_total), ("R02G3", doc.tax_rate), ("R03G3", doc.single_tax_accrued),
        ("R04G3", doc.single_tax_previous), ("R05G3", doc.single_tax_payable),
        ("R06G3", doc.vz_accrued), ("R07G3", doc.vz_payable),
    ):
        tax_xml.add(body, tag, tax_xml.money(value))
    return tax_xml.serialize(root)


# ---------------------------------------------------------------- simplified chart


def chart_variant(organization, date):
    return get_policy_data(organization, date)["chart_variant"]


@frappe.whitelist(methods=["POST"])
def get_chart_accounts(organization, date):
    """Leaf accounts the organization may post to on the date."""
    check_access(organization)
    filters = {"is_group": 0}
    if chart_variant(organization, date) == SIMPLE_CHART:
        filters["in_simplified_chart"] = 1
    return sorted(frappe.get_all("UA Account", filters=filters, pluck="name"))


def check_posting_account(organization, date, account, ctx):
    """Posting to a leaf account outside the simplified chart is rejected."""
    key = f"__chart:{organization}:{date}"
    if key not in ctx:
        ctx[key] = chart_variant(organization, date) == SIMPLE_CHART
    if not ctx[key]:
        return
    if not frappe.db.get_value("UA Account", account, "in_simplified_chart"):
        frappe.throw(_("Рахунок {0} не входить до спрощеного плану рахунків").format(account))
