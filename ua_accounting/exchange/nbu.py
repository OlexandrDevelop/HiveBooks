"""NBU services: exchange rates, the list of banks; IBAN check."""

import json
import re
from datetime import timedelta
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.beeone import exchange as core_exchange
from frappe.utils import getdate, nowdate

from ua_accounting.exchange.common import ExchangeError, status_of, write_log

SETTINGS = "UA Exchange Settings"
DEFAULT_RATES_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json&date={date}"
DEFAULT_BANKS_URL = "https://bank.gov.ua/NBU_BankInfo/get_data_branch?typ=0&json"
MAX_DAYS = 366
TIMEOUT = 20


def settings_value(field, default):
    return frappe.db.get_single_value(SETTINGS, field) or default


NBU_HOSTS = ("bank.gov.ua", "www.bank.gov.ua")


def check_url(url):
    """Only the NBU over https. Other hosts (tests, a proxy) must be listed by the server administrator
    in the site config key `ua_exchange_allowed_hosts`; developer mode allows any host."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if parts.scheme == "https" and host in NBU_HOSTS:
        return
    conf = frappe.conf
    if conf.get("developer_mode") or host in [h.lower() for h in conf.get("ua_exchange_allowed_hosts") or []]:
        if parts.scheme in ("http", "https") and host:
            return
    raise ExchangeError(_("Адреса служби не дозволена: використовуйте https://bank.gov.ua"))


def fetch_json(url):
    """The JSON answer of an NBU service; raises `ExchangeError` with a short reason."""
    check_url(url)
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"Accept": "application/json"}, allow_redirects=False)
    except requests.RequestException as e:
        raise ExchangeError(_("Служба недоступна: {0}").format(e.__class__.__name__))
    if resp.status_code != 200:
        raise ExchangeError(_("Служба відповіла кодом {0}").format(resp.status_code))
    try:
        data = json.loads(resp.content.decode("utf-8-sig"))
    except ValueError:
        raise ExchangeError(_("Відповідь служби не є коректним JSON"))
    if not isinstance(data, list):
        raise ExchangeError(_("Відповідь служби має невірну структуру"))
    return data


def parse_nbu_date(value):
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(value or "").strip())
    if not m:
        raise ExchangeError(_("Дата у відповіді НБУ не розпізнана: {0}. Спробуйте ще раз пізніше").format(value))
    return getdate(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")


def load_rates(date_from=None, date_to=None, rule=None):
    start = getdate(date_from or nowdate())
    end = getdate(date_to or date_from or nowdate())
    if end < start:
        raise ExchangeError(_("Кінець періоду раніше за початок"))
    days = (end - start).days + 1
    if days > MAX_DAYS:
        raise ExchangeError(_("Період завеликий: не більше {0} днів").format(MAX_DAYS))
    url = settings_value("nbu_rates_url", DEFAULT_RATES_URL)
    known = set(frappe.get_all("UA Currency", filters={"is_base": 0}, pluck="name"))
    rule = rule or core_exchange.rule_for("nbu_rates")
    loaded, skipped, errors = {}, set(), []
    rows = {}  # {code: {date: rate}}
    for i in range(days):
        day = start + timedelta(days=i)
        try:
            items = fetch_json(url.replace("{date}", day.strftime("%Y%m%d")))
            for item in items:
                item = core_exchange.map_row(rule, item) if rule else item  # the field mapping of the rule
                code = str(item.get("cc") or "").upper()
                if code not in known:
                    if code:
                        skipped.add(code)
                    continue
                rate = float(item["rate"])
                rows.setdefault(code, {})[parse_nbu_date(item.get("exchangedate"))] = rate
                loaded[code] = rate
        except (ExchangeError, core_exchange.ExchangeError, KeyError, TypeError, ValueError) as e:
            errors.append(f"{day:%d.%m.%Y}: {e}")
    created = updated = 0
    for code, by_date in rows.items():
        doc = frappe.get_doc("UA Currency", code)
        for day, rate in sorted(by_date.items()):
            row = next((r for r in doc.rates if r.date and getdate(r.date) == day), None)
            if row:
                row.rate = rate
                updated += 1
            else:
                doc.append("rates", {"date": day, "rate": rate, "multiplicity": 1})
                created += 1
        doc.save(ignore_permissions=True)
    return {"days": days, "loaded": loaded, "skipped": sorted(skipped), "errors": errors, "created": created, "updated": updated}


def load_rates_logged(date_from=None, date_to=None):
    core_exchange.check_enabled(core_exchange.rule_for("nbu_rates"))
    result = load_rates(date_from, date_to)
    status = "Помилка" if result["errors"] and not result["loaded"] else status_of(result["errors"], result["created"], result["updated"])
    write_log("Імпорт", "nbu_rates", status, created=result["created"], updated=result["updated"], errors=len(result["errors"]),
              details={"errors": result["errors"], "skipped": result["skipped"]})
    return result


def rule_load_rates(rule, scheduled=False, date_from=None, date_to=None, **kwargs):
    """Handler of the exchange framework (`nbu_rates`): the result goes to the journal of the rule run."""
    result = load_rates(date_from, date_to, rule=rule)
    return {"created": result["created"], "updated": result["updated"], "errors": result["errors"],
            "details": {"errors": result["errors"], "skipped": result["skipped"]}}


def rule_load_banks(rule, **kwargs):
    """Handler of the exchange framework (`nbu_banks`): the list of banks."""
    result = load_banks()
    return {"created": result["created"], "updated": result["updated"], "errors": result["errors"], "details": result}


def scheduled_load():
    """Daily job of the scheduler: the framework runs the rule of the rates when it is due and the setting allows."""
    if not frappe.db.get_single_value(SETTINGS, "auto_load_rates"):
        return
    core_exchange.run_due("nbu_rates")


# ------------------------------------------------------------------ banks
def bank_dict(name):
    row = frappe.db.get_value("UA Bank", name, ["name", "mfo", "bank_name", "short_name", "is_active"], as_dict=True) if name else None
    return dict(row) if row else None


def load_banks():
    items = fetch_json(settings_value("nbu_banks_url", DEFAULT_BANKS_URL))
    created = updated = deactivated = 0
    errors = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append({"row": i, "message": _("Запис не розпізнано. Перевірте файл курсів")})
            continue
        mfo = str(item.get("GLB") or "").strip()
        if not re.fullmatch(r"\d{6}", mfo):
            errors.append({"row": i, "message": _("МФО має містити 6 цифр: {0}").format(mfo or "—")})
            continue
        active = 1 if str(item.get("STAN") or "").strip() == "Нормальний" else 0
        values = {"bank_name": str(item.get("NAME") or item.get("NKB") or mfo).strip()[:140],
                  "short_name": str(item.get("NKB") or "").strip()[:140], "is_active": active}
        if frappe.db.exists("UA Bank", mfo):
            doc = frappe.get_doc("UA Bank", mfo)
            if doc.is_active and not active:
                deactivated += 1
            doc.update(values)
            doc.save(ignore_permissions=True)
            updated += 1
        else:
            frappe.get_doc(dict(values, doctype="UA Bank", mfo=mfo)).insert(ignore_permissions=True)
            created += 1
    return {"created": created, "updated": updated, "deactivated": deactivated, "errors": errors}


def clean_iban(iban):
    return re.sub(r"\s+", "", iban or "").upper()


def validate_iban(iban):
    """ISO 13616 for Ukraine: UA + 2 check digits + 6-digit МФО + 19-digit account; the rearranged number mod 97 is 1."""
    value = clean_iban(iban)
    if not re.fullmatch(r"[A-Z0-9]+", value or ""):
        return {"valid": False, "mfo": None, "bank": None, "message": _("IBAN має містити лише літери та цифри")}
    if not value.startswith("UA"):
        return {"valid": False, "mfo": None, "bank": None, "message": _("Це не український IBAN: має починатися з UA")}
    if len(value) != 29:
        return {"valid": False, "mfo": None, "bank": None, "message": _("Український IBAN має 29 символів, у вказаному — {0}").format(len(value))}
    if not value[2:].isdigit():
        return {"valid": False, "mfo": None, "bank": None, "message": _("Після UA мають іти лише цифри")}
    mfo = value[4:10]
    number = int("".join(str(int(c, 36)) for c in value[4:] + value[:4]))
    bank = bank_dict(mfo)
    if number % 97 != 1:
        return {"valid": False, "mfo": mfo, "bank": None, "message": _("Контрольні цифри IBAN не збігаються")}
    return {"valid": True, "mfo": mfo, "bank": (bank["bank_name"] or bank["short_name"]) if bank else None,
            "message": _("IBAN коректний")}


def bank_by_iban(iban):
    value = clean_iban(iban)
    if not (value.startswith("UA") and len(value) >= 10 and value[4:10].isdigit()):
        return None
    return bank_dict(value[4:10])
