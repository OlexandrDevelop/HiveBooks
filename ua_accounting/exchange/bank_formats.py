"""Readers and writers of bank statement formats: iBank2 (1CClientBankExchange), Приват24 CSV, Ощад MT940.

A reader returns {"iban", "date_from", "date_to", "opening", "closing", "lines": [...]}; amounts are floats, dates are `date`.
"""

import csv
import io
import re
from datetime import date

import frappe
from frappe import _

from ua_accounting.exchange.common import ExchangeError

DEBIT, CREDIT = "Списання", "Надходження"
FORMATS = ("ibank2", "privat24", "oschad")


def norm_iban(value):
    return re.sub(r"\s+", "", value or "").upper()


def amount_of(value):
    value = re.sub(r"[\s ]", "", str(value or "")).replace(",", ".")
    if not value:
        return None
    try:
        return round(float(value), 2)
    except ValueError:
        raise ExchangeError(_("Сума «{0}» не є числом").format(value))


def date_of(value, fmt="dmy"):
    value = (value or "").strip()
    try:
        if fmt == "dmy":
            d, m, y = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", value).groups()
        else:  # YYMMDD
            y, m, d = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", value).groups()
            y = "20" + y
        return date(int(y), int(m), int(d))
    except (AttributeError, ValueError):
        raise ExchangeError(_("Дата «{0}» має невірний формат").format(value))


def decode(data):
    """Statements come in utf-8, windows-1251 or cp866 (the file says which one)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    for enc, mark in (("windows-1251", "Windows"), ("cp866", "DOS")):
        text = data.decode(enc, errors="replace")
        if re.search(rf"^Кодировка\s*=\s*{mark}", text, re.M | re.I):
            return text
    return data.decode("windows-1251", errors="replace")


def detect(text):
    head = text.lstrip()[:200]
    if head.startswith("1CClientBankExchange"):
        return "ibank2"
    if head.startswith("Виписка по рахунку"):
        return "privat24"
    if re.search(r"^:25:", text, re.M) and re.search(r"^:61:", text, re.M):
        return "oschad"
    raise ExchangeError(_("Не вдалося визначити формат файлу виписки"))


# ------------------------------------------------------------------ iBank2
def read_ibank2(text, own_iban=None):
    if not text.lstrip().startswith("1CClientBankExchange"):
        raise ExchangeError(_("Файл не є обміном 1CClientBankExchange"))
    head, acc, docs, cur, in_acc = {}, {}, [], None, False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("СекцияДокумент"):
            cur = {}
        elif line == "КонецДокумента":
            if cur is not None:
                docs.append(cur)
            cur = None
        elif line == "СекцияРасчСчет":
            in_acc = True
        elif line == "КонецРасчСчет":
            in_acc = False
        elif "=" in line:
            key, _sep, value = line.partition("=")
            (cur if cur is not None else acc if in_acc else head)[key.strip()] = value.strip()
    file_iban = norm_iban(acc.get("РасчСчет") or head.get("РасчСчет"))
    iban = file_iban or norm_iban(own_iban)
    lines, warnings = [], []
    for doc in docs:
        payer, receiver = norm_iban(doc.get("ПлательщикСчет")), norm_iban(doc.get("ПолучательСчет"))
        if iban and iban not in (payer, receiver):
            warnings.append(_("Документ {0}: жоден з рахунків не збігається з рахунком виписки").format(doc.get("Номер", "")))
            continue
        out = payer == iban
        side = "Получатель" if out else "Плательщик"
        when = doc.get("ДатаСписано" if out else "ДатаПоступило") or doc.get("Дата")
        lines.append({
            "posting_date": date_of(when), "number": doc.get("Номер", ""), "direction": DEBIT if out else CREDIT,
            "amount": amount_of(doc.get("Сумма")), "counterparty_name": doc.get(side) or doc.get(side + "1") or "",
            "counterparty_edrpou": doc.get(side + "ИНН", ""), "counterparty_iban": doc.get(side + "Счет", ""),
            "purpose": doc.get("НазначениеПлатежа", ""),
        })
    start, end = acc.get("ДатаНачала") or head.get("ДатаНачала"), acc.get("ДатаКонца") or head.get("ДатаКонца")
    return {"iban": file_iban or None, "lines": lines, "warnings": warnings,
            "date_from": date_of(start) if start else None, "date_to": date_of(end) if end else None,
            "opening": amount_of(acc.get("НачальныйОстаток")), "closing": amount_of(acc.get("КонечныйОстаток"))}


# ------------------------------------------------------------------ Приват24
PRIVAT_COLUMNS = {"date": "Дата проведення", "number": "Номер документа", "name": "Назва контрагента", "edrpou": "ЄДРПОУ контрагента",
                  "iban": "Рахунок контрагента", "debit": "Дебет", "credit": "Кредит", "purpose": "Призначення платежу"}


def read_privat24(text, own_iban=None):
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    title = next((r[0] for r in rows if r and r[0].strip()), "")
    m = re.match(r"Виписка по рахунку\s+(\S+)\s+за період\s+(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", title.strip())
    if not m:
        raise ExchangeError(_("Файл не є випискою Приват24: немає рядка «Виписка по рахунку …»"))
    start = next((i for i, r in enumerate(rows) if r and r[0].strip() == PRIVAT_COLUMNS["date"]), None)
    if start is None:
        raise ExchangeError(_("У файлі немає рядка заголовків «Дата проведення;…»"))
    header = [c.strip() for c in rows[start]]
    index = {key: header.index(label) if label in header else None for key, label in PRIVAT_COLUMNS.items()}

    def cell(row, key):
        i = index[key]
        return row[i].strip() if i is not None and i < len(row) else ""

    lines = []
    for row in rows[start + 1:]:
        if not row or not cell(row, "date"):
            continue
        debit, credit = amount_of(cell(row, "debit")), amount_of(cell(row, "credit"))
        if not (debit or credit):
            continue
        lines.append({
            "posting_date": date_of(cell(row, "date")), "number": cell(row, "number"), "direction": DEBIT if debit else CREDIT,
            "amount": debit or credit, "counterparty_name": cell(row, "name"), "counterparty_edrpou": cell(row, "edrpou"),
            "counterparty_iban": cell(row, "iban"), "purpose": cell(row, "purpose"),
        })
    return {"iban": norm_iban(m.group(1)), "lines": lines, "warnings": [], "date_from": date_of(m.group(2)),
            "date_to": date_of(m.group(3)), "opening": None, "closing": None}


# ------------------------------------------------------------------ Ощад (MT940)
def mt940_fields(text):
    fields = []
    for line in text.splitlines():
        m = re.match(r"^:(\d{2}[A-Z]?):(.*)$", line)
        if m:
            fields.append([m.group(1), m.group(2)])
        elif fields and line.strip() and not line.startswith("-"):
            fields[-1][1] += line.strip()
    return fields


def mt940_balance(value):
    m = re.match(r"([CD])(\d{6})[A-Z]{3}([\d,]+)", value.strip())
    if not m:
        raise ExchangeError(_("Рядок залишку не розпізнано: {0}. Перевірте формат виписки").format(value))
    amount = amount_of(m.group(3))
    return date_of(m.group(2), "ymd"), -amount if m.group(1) == "D" else amount


def mt940_details(value):
    parts = re.split(r"/(NAME|EDRPOU|NAZN|IBAN|ACC|MFO)/", "/" + value.lstrip("/"))
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i]] = parts[i + 1].rstrip("/").strip()
    return out


def read_oschad(text, own_iban=None):
    fields = mt940_fields(text)
    result = {"iban": None, "lines": [], "warnings": [], "date_from": None, "date_to": None, "opening": None, "closing": None}
    last = None
    for tag, value in fields:
        if tag == "25":
            m = re.search(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", value.upper())
            result["iban"] = m.group(0) if m else norm_iban(value)
        elif tag in ("60F", "60M"):
            result["date_from"], result["opening"] = mt940_balance(value)
        elif tag in ("62F", "62M"):
            result["date_to"], result["closing"] = mt940_balance(value)
        elif tag == "61":
            m = re.match(r"(\d{6})(\d{4})?(R?[DC])[A-Z]?(\d+(?:,\d*)?)(.*)$", value)
            if not m:
                raise ExchangeError(_("Рядок операції не розпізнано: {0}. Перевірте формат виписки").format(value))
            reverse, kind = m.group(3).startswith("R"), m.group(3)[-1]
            debit = (kind == "D") != reverse
            ref = re.sub(r"^N[A-Z]{3}", "", m.group(5).split("//")[0].strip())
            last = {"posting_date": date_of(m.group(1), "ymd"), "number": "" if ref.upper() == "NONREF" else ref,
                    "direction": DEBIT if debit else CREDIT, "amount": amount_of(m.group(4)), "counterparty_name": "",
                    "counterparty_edrpou": "", "counterparty_iban": "", "purpose": ""}
            result["lines"].append(last)
        elif tag == "86" and last is not None:
            d = mt940_details(value)
            last.update(counterparty_name=d.get("NAME", ""), counterparty_edrpou=d.get("EDRPOU", ""),
                        counterparty_iban=norm_iban(d.get("IBAN") or d.get("ACC")), purpose=d.get("NAZN", ""))
    if not result["iban"] or not result["lines"] and result["opening"] is None:
        raise ExchangeError(_("Файл не є випискою MT940"))
    return result


READERS = {"ibank2": read_ibank2, "privat24": read_privat24, "oschad": read_oschad}


# ------------------------------------------------------------------ export of payment orders
def one_line(text):
    return re.sub(r"\s*[\r\n]+\s*", " ", text or "").strip()


def export_ibank2(orders, iban, org, bank_name=None):
    """orders: dicts with number, date, amount, recipient_*, purpose. Returns text (windows-1251 when encoded)."""
    today = date.today()
    dates = [o["date"] for o in orders]
    head = ["1CClientBankExchange", "ВерсияФормата=1.03", "Кодировка=Windows", "Отправитель=Бухгалтерія UA",
            f"ДатаСоздания={today:%d.%m.%Y}", "ВремяСоздания=00:00:00", f"ДатаНачала={min(dates):%d.%m.%Y}",
            f"ДатаКонца={max(dates):%d.%m.%Y}", f"РасчСчет={iban}"]
    out = list(head)
    for o in orders:
        out += ["СекцияДокумент=Платежное поручение", f"Номер={o['number']}", f"Дата={o['date']:%d.%m.%Y}",
                f"Сумма={o['amount']:.2f}", f"ПлательщикСчет={iban}", f"Плательщик={one_line(org['name'])}",
                f"ПлательщикИНН={org['edrpou'] or ''}", f"ПолучательСчет={norm_iban(o['recipient_iban'])}",
                f"Получатель={one_line(o['recipient_name'])}", f"ПолучательИНН={o['recipient_edrpou'] or ''}",
                f"НазначениеПлатежа={one_line(o['purpose'])}", "КонецДокумента"]
    out.append("КонецФайла")
    return "\r\n".join(out) + "\r\n"


def export_privat24(orders):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Номер", "Дата", "Сума", "Рахунок отримувача", "Назва отримувача", "ЄДРПОУ отримувача", "Призначення платежу"])
    for o in orders:
        w.writerow([o["number"], f"{o['date']:%d.%m.%Y}", f"{o['amount']:.2f}".replace(".", ","), norm_iban(o["recipient_iban"]),
                    one_line(o["recipient_name"]), o["recipient_edrpou"] or "", one_line(o["purpose"])])
    return buf.getvalue()
