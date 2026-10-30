import frappe
from frappe.utils import get_first_day, getdate, now
try:
    from frappe.beeone.print import title_of  # beeone: core print helper
except ImportError:
    def title_of(doctype, name):
        """Human title of a record for messages. Catalogs have hash names, never show them."""
        if not name:
            return ""
        field = frappe.get_meta(doctype).title_field
        value = frappe.db.get_value(doctype, name, field) if field else None
        return value or name

def first_of_month(date):
    return get_first_day(getdate(date))

def std_columns():
    """Standard columns for rows written with raw SQL / bulk_insert."""
    return {
        "owner": frappe.session.user,
        "modified_by": frappe.session.user,
        "creation": now(),
        "modified": now(),
        "docstatus": 0,
        "idx": 0,
    }

def pick(doc, entry, key):
    """Value from the entry dict, or from the registrar document."""
    value = entry.get(key)
    if value in (None, ""):
        value = doc.get(key)
    return value

_synced = set()

def next_names(doctype, count):
    """Next `count` names of a doctype with autoincrement naming, for bulk_insert.

    bulk_insert does not set `name`, and on a new Frappe v16 site the column has
    no AUTO_INCREMENT. So the names come from the sequence of the doctype. A table
    that already has rows above the sequence (made with AUTO_INCREMENT) moves the
    sequence up once per process.
    """
    if doctype not in _synced:
        top = frappe.db.sql(f"select coalesce(max(name), 0) from `tab{doctype}`")[0][0]
        if frappe.db.get_next_sequence_val(doctype) <= top:
            frappe.db.set_next_sequence_val(doctype, top + 1)
        _synced.add(doctype)
    return [frappe.db.get_next_sequence_val(doctype) for _i in range(count)]

# ---------------------------------------------------------------- print forms (Jinja methods)

_UNITS = {
    False: ["", "один", "два", "три", "чотири", "п’ять", "шість", "сім", "вісім", "дев’ять"],
    True: ["", "одна", "дві", "три", "чотири", "п’ять", "шість", "сім", "вісім", "дев’ять"],
}
_TEENS = ["десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п’ятнадцять", "шістнадцять",
          "сімнадцять", "вісімнадцять", "дев’ятнадцять"]
_TENS = ["", "", "двадцять", "тридцять", "сорок", "п’ятдесят", "шістдесят", "сімдесят", "вісімдесят", "дев’яносто"]
_HUNDREDS = ["", "сто", "двісті", "триста", "чотириста", "п’ятсот", "шістсот", "сімсот", "вісімсот", "дев’ятсот"]
# (one, few, many, feminine)
_SCALES = [
    None,
    ("тисяча", "тисячі", "тисяч", True),
    ("мільйон", "мільйони", "мільйонів", False),
    ("мільярд", "мільярди", "мільярдів", False),
]

def _plural(number, forms):
    """Ukrainian plural form of a noun: 1 гривня, 2 гривні, 5 гривень."""
    if 11 <= number % 100 <= 14:
        return forms[2]
    if number % 10 == 1:
        return forms[0]
    if 2 <= number % 10 <= 4:
        return forms[1]
    return forms[2]

def _triple(number, feminine):
    words = [_HUNDREDS[number // 100]]
    rest = number % 100
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
    else:
        words += [_TENS[rest // 10], _UNITS[feminine][rest % 10]]
    return [w for w in words if w]

def money_in_words(value, currency=None):
    """1200.5 -> «Одна тисяча двісті гривень 50 копійок».

    A foreign currency is written with its code: 100 USD -> «Сто USD 00 сотих».
    """
    cents = int(round(abs(float(value or 0)) * 100))
    whole, kop = divmod(cents, 100)
    parts = []
    scale = 0
    rest = whole
    while rest:
        rest, chunk = divmod(rest, 1000)
        if chunk:
            if scale == 0:
                words = _triple(chunk, True)
            else:
                forms = _SCALES[scale]
                words = _triple(chunk, forms[3]) + [_plural(chunk, forms)]
            parts = words + parts
        scale += 1
    text = " ".join(parts) or "нуль"
    if currency and currency != "UAH":
        text = f"{text} {currency} {kop:02d} сотих"
        return text[0].upper() + text[1:]
    text = f"{text} {_plural(whole, ('гривня', 'гривні', 'гривень'))} {kop:02d} {_plural(kop, ('копійка', 'копійки', 'копійок'))}"
    return text[0].upper() + text[1:]


def uk_money(value):
    """1300 -> «1 300,00»."""
    return f"{float(value or 0):,.2f}".replace(",", " ").replace(".", ",")


def uk_date(value):
    return getdate(value).strftime("%d.%m.%Y") if value else ""


def bank_info(account):
    """IBAN, bank name and МФО of a bank account."""
    if not account:
        return frappe._dict()
    row = frappe.db.get_value("UA Bank Account", account, ["iban", "bank", "currency"], as_dict=True) or frappe._dict()
    bank = frappe.db.get_value("UA Bank", row.bank, ["bank_name", "mfo"], as_dict=True) if row.bank else None
    row.bank_name = bank.bank_name if bank else ""
    row.mfo = bank.mfo if bank else ""
    return row

def default_account(filters):
    """The default bank account for a filter, else any one."""
    rows = frappe.get_all("UA Bank Account", filters=filters, fields=["name", "is_default"],
                          order_by="is_default desc, creation asc", limit=1)
    return rows[0].name if rows else None

def org_info(name):
    """Organization data for a print form: names, codes, address, logo, bank, director and chief accountant."""
    row = frappe.db.get_value(
        "UA Organization", name,
        ["org_name", "full_name", "edrpou", "ipn", "legal_address", "phone", "logo", "director", "chief_accountant"],
        as_dict=True,
    ) or frappe._dict()
    row.title = row.full_name or row.org_name or name
    row.director_name = title_of("UA Person", row.director)
    row.accountant_name = title_of("UA Person", row.chief_accountant)
    row.bank = bank_info(default_account({"organization": name}))
    return row

def party_info(name):
    """Counterparty data for a print form."""
    row = frappe.db.get_value(
        "UA Counterparty", name, ["counterparty_name", "full_name", "edrpou", "ipn", "legal_address", "phone"],
        as_dict=True,
    ) or frappe._dict()
    row.title = row.full_name or row.counterparty_name or name
    row.bank = bank_info(default_account({"counterparty": name}))
    return row

def uktzed(item):
    """УКТЗЕД code of an item."""
    return frappe.db.get_value("UA Item", item, "uktzed_code") or "" if item else ""

def person_name(person):
    return title_of("UA Person", person) if person else ""
