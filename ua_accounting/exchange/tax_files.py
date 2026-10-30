"""Files for M.E.Doc and Вчасно: the official XML of the tax invoice and the adjustment, plus a registry for Вчасно."""

import base64
import csv
import io
import json

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.accounting import tax, tax_xml
from ua_accounting.exchange.common import ExchangeError

TARGETS = ("medoc", "vchasno")


def money_uk(value):
    return f"{flt(value, 2):.2f}".replace(".", ",")


def seller_edrpou(doc):
    if doc.direction == tax.ISSUED:
        return frappe.db.get_value("UA Organization", doc.organization, "edrpou") or ""
    return tax_xml.party(doc.counterparty)["edrpou"]


def registry_row(doc):
    """A line of registry.csv: number, date, buyer, buyer's ІПН, base, VAT, total."""
    if doc.direction == tax.ISSUED:
        buyer = frappe.db.get_value("UA Counterparty", doc.counterparty, ["counterparty_name", "edrpou", "ipn"], as_dict=True)
        title, ipn = buyer.counterparty_name, buyer.ipn or buyer.edrpou
    else:
        org = frappe.db.get_value("UA Organization", doc.organization, ["org_name", "edrpou", "ipn"], as_dict=True)
        title, ipn = org.org_name, org.ipn or org.edrpou
    if doc.doctype == tax.PN:
        base, vat = flt(doc.total_base), flt(doc.total_vat)
    else:
        base, vat = flt(doc.total_delta_base), flt(doc.total_delta_vat)
    return [doc.number, f"{getdate(doc.posting_date):%d.%m.%Y}", title, ipn or "", money_uk(base), money_uk(vat), money_uk(base + vat)]


def export(items, target):
    if isinstance(items, str):
        items = json.loads(items)
    if target not in TARGETS:
        raise ExchangeError(_("Невідомий отримувач «{0}»: medoc або vchasno").format(target))
    if not items:
        raise ExchangeError(_("Оберіть податкові накладні"))
    files, registry, seen, organization = [], [], set(), None
    for item in items:
        doctype, name = item.get("doctype"), item.get("name")
        if doctype not in (tax.PN, tax.RK):
            raise ExchangeError(_("Вивантаження доступне лише для податкової накладної і розрахунку коригування"))
        if (doctype, name) in seen:
            continue
        seen.add((doctype, name))
        doc = frappe.get_doc(doctype, name)
        doc.check_permission("read")
        if doc.docstatus != 1:
            raise ExchangeError(_("Документ {0} не проведений: вивантажують лише проведені").format(name))
        organization = organization or doc.organization
        xml = tax_xml.export(doc)["xml"].encode("windows-1251")
        prefix = "PN" if doctype == tax.PN else "RK"
        files.append({"filename": f"{prefix}_{seller_edrpou(doc)}_{getdate(doc.posting_date):%Y%m%d}_{doc.number}.xml",
                      "content": base64.b64encode(xml).decode("ascii")})
        registry.append(registry_row(doc))
    if target == "vchasno":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["Номер", "Дата", "Покупець", "ІПН покупця", "База", "ПДВ", "Всього"])
        w.writerows(registry)
        files.append({"filename": "registry.csv", "content": base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii")})
    return {"files": files, "count": len(seen), "organization": organization}
