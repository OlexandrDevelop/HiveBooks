"""Reader of 1C BAU files in the EnterpriseData XML format."""

import re
import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.utils import getdate

from ua_accounting.exchange.catalogs import VAT_1C
from ua_accounting.exchange.common import ExchangeError, flag


def parse(data):
    # a DTD can carry entity bombs: the format does not need it
    if re.search(rb"<!DOCTYPE|<!ENTITY", data, re.I):
        raise ExchangeError(_("Файл містить DTD: такий XML не приймається"))
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ExchangeError(_("Файл не є коректним XML: {0}").format(e))
    for el in root.iter():
        el.tag = el.tag.rsplit("}", 1)[-1]
    return root


def _value(el, tag):
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def catalogs(root):
    """Records of the catalogs found in the file."""
    out = {"counterparties": [], "items": [], "warehouses": []}
    for i, el in enumerate(root.iter("КаталогОбъект.Контрагенты"), start=1):
        out["counterparties"].append({
            "row": i, "name": _value(el, "Наименование"), "full_name": _value(el, "НаименованиеПолное"),
            "edrpou": _value(el, "КодПоЕДРПОУ"), "ipn": _value(el, "ИНН"), "vat_payer": flag(_value(el, "ПлательщикНДС")),
            "is_customer": flag(_value(el, "Покупатель")), "is_supplier": flag(_value(el, "Поставщик")),
        })
    for i, el in enumerate(root.iter("КаталогОбъект.Номенклатура"), start=1):
        rate = _value(el, "СтавкаНДС")
        out["items"].append({
            "row": i, "name": _value(el, "Наименование"), "article": _value(el, "Артикул"),
            "uom": _value(el, "ЕдиницаИзмерения"), "vat_rate": VAT_1C.get(rate, rate) if rate else "",
            "service": flag(_value(el, "Услуга")),
        })
    for i, el in enumerate(root.iter("КаталогОбъект.Склады"), start=1):
        out["warehouses"].append({"row": i, "name": _value(el, "Наименование")})
    return out


def parse_date(value):
    value = (value or "").strip()[:10]
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
        d, m, y = value.split(".")
        value = f"{y}-{m}-{d}"
    try:
        return getdate(value)
    except Exception:
        return None


def balances(root):
    """(date, rows) of the first `Остатки` block."""
    block = root.find(".//Остатки")
    if block is None:
        raise ExchangeError(_("У файлі немає блоку залишків «Остатки»"))
    date = parse_date(block.get("Дата") or _value(block, "Дата"))
    rows = []
    for i, el in enumerate(block.iter("Строка"), start=1):
        rows.append({
            "row": i, "account": _value(el, "Счет"), "counterparty": _value(el, "Контрагент"), "contract": _value(el, "Договор"),
            "warehouse": _value(el, "Склад"), "item": _value(el, "Номенклатура"), "iban": _value(el, "БанковскийСчет"),
            "quantity": _value(el, "Количество"), "amount": _value(el, "Сумма"), "side": _value(el, "Сторона"),
        })
    return date, rows
