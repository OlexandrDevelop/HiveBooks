"""Setup wizard of HiveBooks: the minimum to start real work.

The steps plug into the wizard of the core (hook `beeone_setup_steps`). They create nothing of their own:
every record is made through the existing doctypes, so their validations run as they do in the forms.

1. Organization        UA Organization
2. Accounting policy   UA Accounting Policy
3. Bank and cash desk  UA Bank, UA Bank Account, UA Cash Desk
4. Responsible persons UA Person (director, chief accountant), linked in the organization
5. Opening balances    UA Opening Balances (optional: cash and bank only, the rest can be entered later)

Each `save` is idempotent: the wizard works with one organization, and a second save changes its records.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, today

from ua_accounting.accounting.bank_documents import valid_ua_iban

ORG = "UA Organization"
POLICY = "UA Accounting Policy"
BANK = "UA Bank"
BANK_ACCOUNT = "UA Bank Account"
CASH_DESK = "UA Cash Desk"
PERSON = "UA Person"
OPENING = "UA Opening Balances"
CASH_ACCOUNT = "301"
BANK_ACCOUNT_CODE = "311"
PREFIX = "ua_accounting"


def beeone_setup_steps() -> list[dict]:
    return [
        {
            "id": f"{PREFIX}.organization",
            "order": 20,
            "title": _("Організація"),
            "description": _("Назва і коди, як у реєстраційних документах"),
            "fields": _organization_fields(),
            "load": f"{PREFIX}.setup.wizard.load_organization",
            "validate": f"{PREFIX}.setup.wizard.check_organization",
            "save": f"{PREFIX}.setup.wizard.save_organization",
        },
        {
            "id": f"{PREFIX}.policy",
            "order": 30,
            "title": _("Облікова політика"),
            "description": _("З якої дати ведеться облік і як оцінюються запаси"),
            "fields": _policy_fields(),
            "load": f"{PREFIX}.setup.wizard.load_policy",
            "validate": f"{PREFIX}.setup.wizard.check_policy",
            "save": f"{PREFIX}.setup.wizard.save_policy",
        },
        {
            "id": f"{PREFIX}.bank_cash",
            "order": 40,
            "title": _("Банківський рахунок і каса"),
            "description": _("Основний розрахунковий рахунок та каса організації"),
            "fields": _bank_cash_fields(),
            "load": f"{PREFIX}.setup.wizard.load_bank_cash",
            "validate": f"{PREFIX}.setup.wizard.check_bank_cash",
            "save": f"{PREFIX}.setup.wizard.save_bank_cash",
        },
        {
            "id": f"{PREFIX}.persons",
            "order": 50,
            "title": _("Відповідальні особи"),
            "description": _("Директор і головний бухгалтер для підписів у документах"),
            "fields": _persons_fields(),
            "load": f"{PREFIX}.setup.wizard.load_persons",
            "validate": f"{PREFIX}.setup.wizard.check_persons",
            "save": f"{PREFIX}.setup.wizard.save_persons",
        },
        {
            "id": f"{PREFIX}.opening",
            "order": 60,
            "title": _("Початкові залишки"),
            "description": _("Залишок коштів у касі та на рахунку. Решту можна ввести пізніше"),
            "fields": _opening_fields(),
            "load": f"{PREFIX}.setup.wizard.load_opening",
            "validate": f"{PREFIX}.setup.wizard.check_opening",
            "save": f"{PREFIX}.setup.wizard.save_opening",
            "optional": True,
        },
    ]


# ---------------------------------------------------------------- helpers


def _label(doctype, fieldname):
    return frappe.get_meta(doctype).get_field(fieldname).label


def _options(doctype, fieldname):
    return frappe.get_meta(doctype).get_field(fieldname).options or ""


def _first(doctype, **filters):
    """The record of the wizard: the oldest one. The wizard works with one organization."""
    names = frappe.get_all(doctype, filters, pluck="name", order_by="creation asc", limit=1)
    return names[0] if names else None


def _organization():
    return _first(ORG)


def _need_organization():
    name = _organization()
    if not name:
        frappe.throw(_("Спочатку заповніть крок «Організація»"))
    return name


def _problem(doc, field):
    """{field: message} when the validation of the doctype refuses the document, else {}."""
    try:
        doc.validate()
    except frappe.ValidationError as error:
        return {field: frappe.utils.strip_html(str(error)).strip() or _("Перевірте значення")}
    return {}


def _save(doc):
    doc.flags.ignore_permissions = True
    doc.save() if doc.get("name") and not doc.is_new() else doc.insert()
    return doc


def _values(doctype, name, fields):
    if not name:
        return {}
    return {k: v for k, v in frappe.db.get_value(doctype, name, fields, as_dict=True).items()}


# ---------------------------------------------------------------- 1. organization

ORG_FIELDS = ("org_name", "full_name", "edrpou", "ipn", "vat_payer", "tax_system")


def _organization_fields():
    return [
        {"fieldname": "org_name", "fieldtype": "Data", "label": _label(ORG, "org_name"), "reqd": 1},
        {"fieldname": "full_name", "fieldtype": "Data", "label": _label(ORG, "full_name")},
        {
            "fieldname": "edrpou",
            "fieldtype": "Data",
            "label": _label(ORG, "edrpou"),
            "reqd": 1,
            "description": _("8 цифр для юридичної особи, 10 цифр (РНОКПП) для ФОП"),
        },
        {"fieldname": "tax_system", "fieldtype": "Select", "label": _label(ORG, "tax_system"),
         "options": _options(ORG, "tax_system"), "reqd": 1},
        {"fieldname": "vat_payer", "fieldtype": "Check", "label": _label(ORG, "vat_payer")},
        {
            "fieldname": "ipn",
            "fieldtype": "Data",
            "label": _label(ORG, "ipn"),
            "description": _("Обов'язковий для платника ПДВ: 10 або 12 цифр"),
        },
    ]


def load_organization():
    name = _organization()
    values = _values(ORG, name, ORG_FIELDS)
    return values or {"tax_system": frappe.get_meta(ORG).get_field("tax_system").default, "vat_payer": 0}


def check_organization(values):
    org = frappe.new_doc(ORG)
    org.update({k: values.get(k) for k in ORG_FIELDS})
    errors = _problem(org, "edrpou")
    ipn = (values.get("ipn") or "").strip()
    if ipn and not (ipn.isascii() and ipn.isdigit() and len(ipn) in (10, 12)):
        errors["ipn"] = _("ІПН має містити 10 або 12 цифр")
    elif values.get("vat_payer") and not ipn:
        errors["ipn"] = _("Платник ПДВ має вказати ІПН")
    return errors


def save_organization(values):
    name = _organization()
    org = frappe.get_doc(ORG, name) if name else frappe.new_doc(ORG)
    org.update({k: values.get(k) for k in ORG_FIELDS})
    org.keep_tax_accounting = 1
    _save(org)
    # the policy of the wizard repeats the tax data of the organization
    policy = _wizard_policy(org.name)
    if policy:
        doc = frappe.get_doc(POLICY, policy)
        doc.vat_payer, doc.tax_system = org.vat_payer, org.tax_system
        _save(doc)


# ---------------------------------------------------------------- 2. accounting policy


def _policy_fields():
    return [
        {"fieldname": "effective_from", "fieldtype": "Date", "label": _("Початок ведення обліку"), "reqd": 1,
         "description": _("Дата, з якої облік ведеться в програмі")},
        {"fieldname": "taxpayer_type", "fieldtype": "Select", "label": _label(POLICY, "taxpayer_type"),
         "options": _options(POLICY, "taxpayer_type"), "reqd": 1},
        {"fieldname": "cost_method", "fieldtype": "Select", "label": _label(POLICY, "cost_method"),
         "options": _options(POLICY, "cost_method"), "reqd": 1},
    ]


def _wizard_policy(organization):
    return _first(POLICY, organization=organization)


def load_policy():
    name = _organization()
    policy = _wizard_policy(name) if name else None
    if policy:
        return _values(POLICY, policy, ("effective_from", "taxpayer_type", "cost_method"))
    meta = frappe.get_meta(POLICY)
    return {
        "effective_from": str(get_first_day(today())),
        "taxpayer_type": meta.get_field("taxpayer_type").default,
        "cost_method": meta.get_field("cost_method").default,
    }


def _policy_doc(values):
    organization = _need_organization()
    name = _wizard_policy(organization)
    doc = frappe.get_doc(POLICY, name) if name else frappe.new_doc(POLICY)
    org = frappe.db.get_value(ORG, organization, ["vat_payer", "tax_system"], as_dict=True)
    doc.update(
        {
            "organization": organization,
            "effective_from": values.get("effective_from"),
            "taxpayer_type": values.get("taxpayer_type"),
            "cost_method": values.get("cost_method"),
            "vat_payer": org.vat_payer,
            "tax_system": org.tax_system,
        }
    )
    return doc


def check_policy(values):
    doc = _policy_doc(values)
    doc.before_validate()
    return _problem(doc, "taxpayer_type")


def save_policy(values):
    _save(_policy_doc(values))


# ---------------------------------------------------------------- 3. bank account and cash desk


def _bank_cash_fields():
    return [
        {"fieldname": "mfo", "fieldtype": "Data", "label": _label(BANK, "mfo"), "reqd": 1,
         "description": _("6 цифр")},
        {"fieldname": "bank_name", "fieldtype": "Data", "label": _("Банк"), "reqd": 1},
        {"fieldname": "iban", "fieldtype": "Data", "label": _label(BANK_ACCOUNT, "iban"), "reqd": 1,
         "description": _("UA і 27 цифр")},
        {"fieldname": "account_name", "fieldtype": "Data", "label": _("Назва рахунку"), "reqd": 1},
        {"fieldname": "cash_desk_name", "fieldtype": "Data", "label": _("Назва каси"), "reqd": 1},
    ]


def _bank_account(organization):
    return _first(BANK_ACCOUNT, organization=organization)


def _cash_desk(organization):
    return _first(CASH_DESK, organization=organization)


def load_bank_cash():
    values = {"account_name": _("Основний рахунок"), "cash_desk_name": _("Основна каса")}
    organization = _organization()
    if not organization:
        return values
    account = _bank_account(organization)
    if account:
        row = frappe.db.get_value(BANK_ACCOUNT, account, ["account_name", "iban", "bank"], as_dict=True)
        values.update(account_name=row.account_name, iban=row.iban)
        if row.bank:
            values.update(mfo=row.bank, bank_name=frappe.db.get_value(BANK, row.bank, "bank_name"))
    desk = _cash_desk(organization)
    if desk:
        values["cash_desk_name"] = frappe.db.get_value(CASH_DESK, desk, "cash_desk_name")
    return values


def check_bank_cash(values):
    errors = {}
    mfo = (values.get("mfo") or "").strip()
    if not (mfo.isascii() and mfo.isdigit() and len(mfo) == 6):
        errors["mfo"] = _("МФО має містити 6 цифр")
    iban = (values.get("iban") or "").replace(" ", "").upper()
    account = frappe.new_doc(BANK_ACCOUNT)
    account.update({"organization": _organization(), "iban": iban})
    errors.update(_problem(account, "iban"))
    if "iban" not in errors and not valid_ua_iban(iban):
        errors["iban"] = _("Контрольні цифри IBAN не збігаються: перевірте номер")
    return errors


def save_bank_cash(values):
    organization = _need_organization()
    mfo = values["mfo"].strip()
    if not frappe.db.exists(BANK, mfo):
        _save(frappe.get_doc({"doctype": BANK, "mfo": mfo, "bank_name": values["bank_name"]}))
    name = _bank_account(organization)
    account = frappe.get_doc(BANK_ACCOUNT, name) if name else frappe.new_doc(BANK_ACCOUNT)
    account.update(
        {
            "organization": organization,
            "account_name": values["account_name"],
            "iban": values["iban"],
            "bank": mfo,
            "is_default": 1,
        }
    )
    _save(account)
    name = _cash_desk(organization)
    desk = frappe.get_doc(CASH_DESK, name) if name else frappe.new_doc(CASH_DESK)
    desk.update({"organization": organization, "cash_desk_name": values["cash_desk_name"]})
    _save(desk)


# ---------------------------------------------------------------- 4. responsible persons


def _persons_fields():
    return [
        {"fieldname": "director", "fieldtype": "Data", "label": _("Директор (ПІБ)"), "reqd": 1},
        {"fieldname": "director_ipn", "fieldtype": "Data", "label": _("ІПН директора")},
        {"fieldname": "chief_accountant", "fieldtype": "Data", "label": _("Головний бухгалтер (ПІБ)"),
         "description": _("Якщо облік веде директор, залиште порожнім")},
        {"fieldname": "chief_accountant_ipn", "fieldtype": "Data", "label": _("ІПН головного бухгалтера")},
    ]


PERSON_ROLES = (("director", "director"), ("chief_accountant", "chief_accountant"))


def load_persons():
    organization = _organization()
    values = {}
    if not organization:
        return values
    org = frappe.db.get_value(ORG, organization, [role for role, _field in PERSON_ROLES], as_dict=True)
    for role, field in PERSON_ROLES:
        if org.get(role):
            person = frappe.db.get_value(PERSON, org[role], ["full_name", "ipn"], as_dict=True)
            values[field] = person.full_name
            values[f"{field}_ipn"] = person.ipn
    return values


def check_persons(values):
    errors = {}
    for role, field in PERSON_ROLES:
        ipn = (values.get(f"{field}_ipn") or "").strip()
        if ipn and not (ipn.isascii() and ipn.isdigit() and len(ipn) in (10, 12)):
            errors[f"{field}_ipn"] = _("ІПН має містити 10 або 12 цифр")
    return errors


def save_persons(values):
    organization = _need_organization()
    org = frappe.get_doc(ORG, organization)
    for role, field in PERSON_ROLES:
        full_name = (values.get(field) or "").strip()
        if not full_name:
            org.set(role, None)
            continue
        person = frappe.get_doc(PERSON, org.get(role)) if org.get(role) else frappe.new_doc(PERSON)
        person.update({"full_name": full_name, "ipn": (values.get(f"{field}_ipn") or "").strip() or None})
        org.set(role, _save(person).name)
    _save(org)


# ---------------------------------------------------------------- 5. opening balances (optional)


def _opening_fields():
    return [
        {"fieldname": "posting_date", "fieldtype": "Date", "label": _label(OPENING, "posting_date"), "reqd": 1,
         "description": _("Дата, на яку відомі залишки")},
        {"fieldname": "cash", "fieldtype": "Currency", "label": _("Залишок у касі, грн")},
        {"fieldname": "bank", "fieldtype": "Currency", "label": _("Залишок на рахунку, грн")},
    ]


def _opening_document(organization):
    """The opening balances document of the wizard: the only one of the organization (cash and bank rows)."""
    names = frappe.get_all(OPENING, {"organization": organization, "docstatus": ("<", 2)}, pluck="name")
    return frappe.get_doc(OPENING, names[0]) if len(names) == 1 else None


def load_opening():
    organization = _organization()
    start = _values(POLICY, _wizard_policy(organization), ("effective_from",)).get("effective_from") if organization else None
    values = {"posting_date": str(start or today())}
    doc = _opening_document(organization) if organization else None
    if doc:
        values["posting_date"] = str(doc.posting_date)
        for row in doc.rows:
            key = {CASH_ACCOUNT: "cash", BANK_ACCOUNT_CODE: "bank"}.get(row.account)
            if key:
                values[key] = flt(row.amount)
    return values


def check_opening(values):
    errors = {}
    for field in ("cash", "bank"):
        if flt(values.get(field)) < 0:
            errors[field] = _("Залишок не може бути від'ємним")
    if not flt(values.get("cash")) and not flt(values.get("bank")):
        errors["cash"] = _("Вкажіть залишок або пропустіть цей крок")
    return errors


def save_opening(values):
    organization = _need_organization()
    cash, bank = flt(values.get("cash")), flt(values.get("bank"))
    old = _opening_document(organization)
    if old:
        if old.docstatus == 1:
            old.flags.ignore_permissions = True
            old.cancel()
        frappe.delete_doc(OPENING, old.name, ignore_permissions=True, force=True)
    rows = []
    if cash:
        rows.append(_opening_row("Каса", CASH_ACCOUNT, "UA Cash Desk", _cash_desk(organization), cash))
    if bank:
        rows.append(_opening_row("Банківські рахунки", BANK_ACCOUNT_CODE, BANK_ACCOUNT, _bank_account(organization), bank))
    doc = frappe.get_doc(
        {"doctype": OPENING, "organization": organization, "posting_date": getdate(values["posting_date"]), "rows": rows}
    )
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()


def _opening_row(section, account, subconto_type, subconto, amount):
    return {
        "section": section,
        "account": account,
        "subconto1_type": subconto_type,
        "subconto1": subconto,
        "amount": amount,
    }
