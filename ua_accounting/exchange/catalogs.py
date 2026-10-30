"""Import of catalogs (counterparties, items, warehouses) from normalized records.

A record is a plain dict made by the 1C XML or the Excel reader. A bad record is reported and the others are saved.
"""

import re

import frappe
from frappe import _

CP, ITEM, WH = "UA Counterparty", "UA Item", "UA Warehouse"
VAT_1C = {"НДС20": "20", "НДС7": "7", "НДС0": "0", "БезНДС": "Без ПДВ"}
ITEM_TYPES = ("Товар", "Послуга", "Матеріал", "Продукція")


class Counts:
    def __init__(self):
        self.created, self.updated, self.errors = {}, {}, []

    def add(self, kind, doctype):
        bucket = self.created if kind == "created" else self.updated
        bucket[doctype] = bucket.get(doctype, 0) + 1

    def result(self):
        return {"created": self.created, "updated": self.updated, "errors": self.errors}


def run_rows(counts, records, importer, organization):
    """Each record is saved in its own savepoint."""
    for rec in records:
        frappe.db.savepoint("exchange_row")
        try:
            doctype, kind = importer(rec, organization)
            counts.add(kind, doctype)
        except Exception as e:
            frappe.db.rollback(save_point="exchange_row")
            counts.errors.append({"row": rec.get("row"), "message": _clean(e)})


def _clean(e):
    return re.sub(r"<[^>]+>", "", str(e))


def _text(value):
    return (str(value).strip() if value is not None else "") or None


def _find(doctype, filters):
    return frappe.db.get_value(doctype, filters, "name")


def import_counterparty(rec, organization=None):
    name = _text(rec.get("name"))
    edrpou, ipn = _text(rec.get("edrpou")), _text(rec.get("ipn"))
    if not name:
        frappe.throw(_("Контрагент: не вказано найменування"))
    if edrpou and not re.fullmatch(r"\d{8}", edrpou):
        frappe.throw(_("Контрагент «{0}»: ЄДРПОУ має містити рівно 8 цифр ({1})").format(name, edrpou))
    allowed = (8, 10, 12) if edrpou else (10,)
    if ipn and not (ipn.isdigit() and len(ipn) in allowed):
        frappe.throw(_("Контрагент «{0}»: ІПН/РНОКПП має містити {1} цифр ({2})").format(
            name, _(" або ").join(str(n) for n in allowed), ipn))
    existing = None
    if edrpou:
        existing = _find(CP, {"edrpou": edrpou})
    elif ipn and len(ipn) == 10:
        existing = _find(CP, {"ipn": ipn}) or _find(CP, {"edrpou": ipn})
    elif not ipn:
        existing = _find(CP, {"counterparty_name": name, "edrpou": ("is", "not set"), "ipn": ("is", "not set")})
    doc = frappe.get_doc(CP, existing) if existing else frappe.new_doc(CP)
    doc.counterparty_name = name
    doc.full_name = _text(rec.get("full_name")) or name
    if edrpou:
        doc.edrpou = edrpou
    if ipn:
        doc.ipn = ipn
    doc.vat_payer = 1 if rec.get("vat_payer") else 0
    doc.is_customer = 1 if rec.get("is_customer") else 0
    doc.is_supplier = 1 if rec.get("is_supplier") else 0
    if not existing:
        doc.kind = "Юридична особа" if edrpou else "ФОП" if "ФОП" in (doc.full_name + name).upper() else "Фізична особа"
    doc.save(ignore_permissions=True)
    return CP, "updated" if existing else "created"


def ensure_uom(uom):
    uom = _text(uom) or "шт"
    if not frappe.db.exists("UA UOM", uom):
        frappe.get_doc({"doctype": "UA UOM", "short_name": uom[:140], "full_name": uom[:140]}).insert(ignore_permissions=True)
    return uom[:140]


def import_item(rec, organization=None):
    name, article = _text(rec.get("name")), _text(rec.get("article"))
    if not name or name.lower() == "без назви":  # «Без назви» is the placeholder of an empty name
        frappe.throw(_("Номенклатура: не вказано найменування"))
    rate = _text(rec.get("vat_rate"))
    if rate and not frappe.db.exists("UA VAT Rate", rate):
        frappe.throw(_("Номенклатура «{0}»: невідома ставка ПДВ «{1}»").format(name, rate))
    item_type = _text(rec.get("item_type"))
    if item_type and item_type not in ITEM_TYPES:
        frappe.throw(_("Номенклатура «{0}»: невідомий вид «{1}»").format(name, item_type))
    existing = None
    if article:
        existing = _find(ITEM, {"article": article}) or _find(ITEM, {"item_name": name, "article": ("is", "not set")})
    else:
        existing = _find(ITEM, {"item_name": name})
    doc = frappe.get_doc(ITEM, existing) if existing else frappe.new_doc(ITEM)
    doc.item_name = name
    if article:
        doc.article = article
    if rec.get("uom") or not existing:
        doc.uom = ensure_uom(rec.get("uom"))
    if rate:
        doc.vat_rate = rate
    elif not existing:
        doc.vat_rate = "20"
    if "service" in rec:
        if rec["service"]:
            doc.item_type = "Послуга"
        elif not existing or doc.item_type == "Послуга":
            doc.item_type = "Товар"
    elif item_type:
        doc.item_type = item_type
    doc.save(ignore_permissions=True)
    return ITEM, "updated" if existing else "created"


def import_warehouse(rec, organization):
    name = _text(rec.get("name"))
    if not name:
        frappe.throw(_("Склад: не вказано найменування"))
    existing = _find(WH, {"warehouse_name": name, "organization": organization})
    doc = frappe.get_doc(WH, existing) if existing else frappe.new_doc(WH)
    doc.warehouse_name = name
    doc.organization = organization
    doc.save(ignore_permissions=True)
    return WH, "updated" if existing else "created"


IMPORTERS = {"counterparties": import_counterparty, "items": import_item, "warehouses": import_warehouse}


def import_catalogs(organization, records):
    """records: {"counterparties": [...], "items": [...], "warehouses": [...]}"""
    counts = Counts()
    for key, importer in IMPORTERS.items():
        run_rows(counts, records.get(key, []), importer, organization)
    return counts
