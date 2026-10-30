"""ДПС XML export of ПН, РК and the VAT return, validated against bundled XSDs."""

from decimal import Decimal, ROUND_HALF_UP
import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

import frappe
from frappe import _
from frappe.utils import flt, getdate
from lxml import etree

from ua_accounting.accounting import regulatory, tax
from ua_accounting.accounting.documents import vat_info

SCHEMA_PN = "J1201016 v.16"
SCHEMA_RK = "J1201216 v.16"
SCHEMA_VAT = "J0200126 v.26"
SCHEMA_D1 = "J0200526 v.26"
SCHEMA_D5 = "J0215726 v.26"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SOFTWARE = "UA Accounting"


def money(value):
    value = flt(value, 2)
    return f"{(value if value else 0.0):.2f}"


def ddmmyyyy(value):
    return getdate(value).strftime("%d%m%Y")


def add(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is None:
        el.set(f"{{{XSI}}}nil", "true")
    else:
        el.text = str(text)
    return el


def header(root, org, form, sub, version, date, month, year, doc_no, tax_office_code=None, links=None):
    head = ET.SubElement(root, "DECLARHEAD")
    add(head, "TIN", org.edrpou or "")
    add(head, "C_DOC", form)
    add(head, "C_DOC_SUB", sub)
    add(head, "C_DOC_VER", version)
    add(head, "C_DOC_TYPE", 0)
    add(head, "C_DOC_CNT", doc_no)
    add(head, "C_REG", str(tax_office_code)[:2] if tax_office_code else "00")
    add(head, "C_RAJ", str(tax_office_code)[2:] if tax_office_code else "00")
    add(head, "PERIOD_MONTH", month)
    add(head, "PERIOD_TYPE", 1)
    add(head, "PERIOD_YEAR", year)
    if tax_office_code:
        add(head, "C_STI_ORIG", tax_office_code)
    add(head, "C_DOC_STAN", 1)
    if links:
        linked = ET.SubElement(head, "LINKED_DOCS")
        for number, link in enumerate(links, start=1):
            related = ET.SubElement(linked, "DOC", NUM=str(number), TYPE=str(link["type"]))
            for tag, value in (("C_DOC", "J02"), ("C_DOC_SUB", link["sub"]),
                               ("C_DOC_VER", link["version"]), ("C_DOC_TYPE", 0),
                               ("C_DOC_CNT", 1), ("C_DOC_STAN", 1),
                               ("FILENAME", link["filename"])):
                add(related, tag, value)
    else:
        add(head, "LINKED_DOCS")
    add(head, "D_FILL", ddmmyyyy(date))
    add(head, "SOFTWARE", SOFTWARE)


def new_root(xsd):
    ET.register_namespace("xsi", XSI)
    root = ET.Element("DECLAR", {f"{{{XSI}}}noNamespaceSchemaLocation": xsd})
    return root


def serialize(root):
    text = ET.tostring(root, encoding="unicode")
    # characters outside windows-1251 become numeric references: the file stays well-formed
    text = text.encode("windows-1251", errors="xmlcharrefreplace").decode("windows-1251")
    return '<?xml version="1.0" encoding="windows-1251"?>\n' + text


def validated_xml(root, xsd_name):
    """Validate the bytes that are actually delivered, using only bundled ДПС schemas."""
    path = Path(__file__).resolve().parents[1] / "schemas" / xsd_name
    if not path.is_file():
        frappe.throw(_("Схема ДПС {0} відсутня").format(xsd_name))
    xml = serialize(root)
    schema = etree.XMLSchema(etree.parse(str(path)))
    document = etree.fromstring(xml.encode("windows-1251"))
    if not schema.validate(document):
        frappe.throw(_("XML не відповідає схемі ДПС {0}: {1}").format(xsd_name, schema.error_log.last_error))
    return xml


def required(value, label):
    if not value:
        frappe.throw(_("Для XML ДПС заповніть поле «{0}»").format(label))
    return value


def filing_details(org):
    office = required(org.tax_office_code, _("Код контролюючого органу"))
    signer = frappe.get_doc("UA Person", required(org.director, _("Директор")))
    return office, required(signer.full_name, _("ПІБ директора")), required(signer.ipn, _("ІПН директора"))


def whole(value):
    """The official VAT return accepts whole hryvnias (column A/B)."""
    return str(Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_code(rate, cache):
    percent, taxable = vat_info(rate, cache)
    if not taxable:
        return "903"
    if percent == 0:
        return "902"
    if percent in (20, 7, 14):
        return str(int(percent))
    frappe.throw(_("Ставка ПДВ {0} не підтримується схемою ДПС").format(rate))


def party(name):
    if not name:
        return {"name": "", "edrpou": "", "ipn": ""}
    row = frappe.db.get_value("UA Counterparty", name, ["full_name", "counterparty_name", "edrpou", "ipn"], as_dict=True)
    return {"name": row.full_name or row.counterparty_name, "edrpou": row.edrpou or "", "ipn": row.ipn or row.edrpou or ""}


def sides(doc):
    org = frappe.get_doc("UA Organization", doc.organization)
    me = {"name": org.full_name or org.org_name, "ipn": org.ipn or org.edrpou or ""}
    other = party(doc.counterparty)
    if doc.direction == tax.ISSUED:
        return org, me, other
    return org, other, me


def filename(org, form, sub, date, number):
    d = getdate(date)
    return f"{(org.edrpou or '').zfill(10)}{form}{sub}01{1:01d}{str(number or 1).zfill(7)}1{d.month:02d}{d.year}.xml"


def package_filename(org, office, sub, version, period):
    """Official filename also used verbatim in each LINKED_DOCS/FILENAME."""
    d = getdate(period)
    return (f"{str(office).zfill(4)}{str(org.edrpou or '').zfill(10)}J02{sub}"
            f"{int(version):02d}1{0:02d}{1:07d}1{d.month:02d}{d.year}{str(office).zfill(4)}.xml")


def export(doc):
    if doc.doctype == tax.PN:
        return export_invoice(doc)
    return export_adjustment(doc)


def export_invoice(pn):
    org, seller, buyer = sides(pn)
    office, signer, signer_ipn = filing_details(org)
    d = getdate(pn.posting_date)
    info = regulatory.form_version_info("TAX_INVOICE_PN", d.replace(day=1), 16, SCHEMA_PN)
    root = new_root(info["xsd"])
    version = info["version"]
    header(root, org, "J12", "010", version, pn.posting_date, d.month, d.year, 1, office)
    body = ET.SubElement(root, "DECLARBODY")
    kinds = {
        tax.KIND_ORDINARY: None,
        tax.KIND_NO_PN: (4, "02"),
        tax.KIND_OWN: (1, "13"),
    }
    if pn.invoice_kind not in kinds:
        frappe.throw(_("Невідомий вид податкової накладної {0}").format(pn.invoice_kind))
    consolidated = kinds[pn.invoice_kind]
    if pn.invoice_kind == tax.KIND_NO_PN:
        buyer = {"name": "Неплатник", "ipn": "100000000000"}
    elif pn.invoice_kind == tax.KIND_OWN:
        buyer = {"name": seller["name"], "ipn": "600000000000"}
    if consolidated:
        add(body, "R01G1", consolidated[0])
    if pn.direction == tax.ISSUED:
        add(body, "HORIG1", 1)
    if consolidated:
        add(body, "HTYPR", consolidated[1])
    add(body, "HFILL", ddmmyyyy(pn.posting_date))
    add(body, "HNUM", pn.number)
    add(body, "HNAMESEL", required(seller["name"], _("Назва продавця")))
    add(body, "HNAMEBUY", required(buyer["name"], _("Назва покупця")))
    add(body, "HKSEL", required(seller["ipn"], _("ІПН продавця")))
    add(body, "HKBUY", buyer["ipn"] or "0")
    add(body, "R04G11", money(pn.total_amount))
    add(body, "R03G11", money(pn.total_vat))
    cache = {}
    by_rate = {}
    for line in pn.lines:
        code = rate_code(line.vat_rate, cache)
        row = by_rate.setdefault(code, [0.0, 0.0])
        row[0] += flt(line.base_amount)
        row[1] += flt(line.vat_amount)
    for code, tag in (("20", "R03G7"), ("7", "R03G109"), ("14", "R03G14")):
        if code in by_rate:
            add(body, tag, money(by_rate[code][1]))
    for code, tag in (("20", "R01G7"), ("7", "R01G109"), ("14", "R01G14"),
                      ("901", "R01G9"), ("902", "R01G8"), ("903", "R01G10")):
        if code in by_rate:
            add(body, tag, money(by_rate[code][0]))
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG3S", required(l.description, _("Опис рядка ПН")), ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        if l.ukt_zed:
            add(body, "RXXXXG4", l.ukt_zed, ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        if l.uom:
            add(body, "RXXXXG4S", l.uom, ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG5", f"{flt(l.quantity, 3):.3f}", ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG6", money(l.price), ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG008", rate_code(l.vat_rate, cache), ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG010", money(l.base_amount), ROWNUM=i)
    for i, l in enumerate(pn.lines, start=1):
        add(body, "RXXXXG11_10", money(l.vat_amount), ROWNUM=i)
    add(body, "HBOS", signer)
    add(body, "HKBOS", signer_ipn)
    return {
        "filename": filename(org, "J12", "010", pn.posting_date, pn.number),
        "schema_version": info["schema_version"],
        "xml": validated_xml(root, info["xsd"]),
    }


def export_adjustment(rk):
    pn = frappe.get_doc(tax.PN, rk.tax_invoice)
    org, seller, buyer = sides(rk)
    office, signer, signer_ipn = filing_details(org)
    d = getdate(rk.posting_date)
    info = regulatory.form_version_info("ADJUSTMENT_RK", d.replace(day=1), 16, SCHEMA_RK)
    root = new_root(info["xsd"])
    version = info["version"]
    header(root, org, "J12", "012", version, rk.posting_date, d.month, d.year, 1, office)
    body = ET.SubElement(root, "DECLARBODY")
    add(body, "HERPN" if flt(rk.total_delta_vat) < 0 else "HERPN0", 1)
    add(body, "HFILL", ddmmyyyy(rk.posting_date))
    add(body, "HNUM", rk.number)
    add(body, "HPODFILL", ddmmyyyy(pn.posting_date))
    add(body, "HPODNUM", pn.number)
    add(body, "HNAMESEL", required(seller["name"], _("Назва продавця")))
    add(body, "HNAMEBUY", required(buyer["name"], _("Назва покупця")))
    add(body, "HKSEL", required(seller["ipn"], _("ІПН продавця")))
    add(body, "HKBUY", buyer["ipn"] or "0")
    add(body, "R001G03", money(rk.total_delta_vat))
    add(body, "R02G9", money(rk.total_delta_vat))
    add(body, "R01G9", money(rk.total_delta_base))
    reasons = {"Зміна ціни": 101, "Зміна кількості": 102, "Повернення товару": 103, "Інше": 104}
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG001", i, ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG21", reasons.get(rk.reason, 104), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG22", 1, ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG3S", required(l.description, _("Опис рядка РК")), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        if flt(l.quantity_after) != flt(l.quantity_before):
            add(body, "RXXXXG5", f"{flt(l.quantity_after - l.quantity_before, 3):.3f}", ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        if flt(l.quantity_after) != flt(l.quantity_before):
            add(body, "RXXXXG6", money(l.price_after), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        if flt(l.price_after) != flt(l.price_before):
            add(body, "RXXXXG7", money(l.price_after - l.price_before), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        if flt(l.price_after) != flt(l.price_before):
            add(body, "RXXXXG8", f"{flt(l.quantity_after, 3):.3f}", ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG008", rate_code(pn.lines[i - 1].vat_rate, {}), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG010", money(l.delta_base), ROWNUM=i)
    for i, l in enumerate(rk.lines, start=1):
        add(body, "RXXXXG11_10", money(l.delta_vat), ROWNUM=i)
    add(body, "HBOS", signer)
    add(body, "HKBOS", signer_ipn)
    return {
        "filename": filename(org, "J12", "012", rk.posting_date, rk.number),
        "schema_version": info["schema_version"],
        "xml": validated_xml(root, info["xsd"]),
    }


def export_return(ret, fill_date=None, appendix_links=None):
    org = frappe.get_doc("UA Organization", ret.organization)
    office, signer, signer_ipn = filing_details(org)
    d = getdate(ret.period_from)
    info = regulatory.form_version_info("VAT_RETURN", d.replace(day=1), 26, SCHEMA_VAT)
    root = new_root(info["xsd"])
    version = info["version"]
    header(root, org, "J02", "001", version, fill_date or getdate(), d.month, d.year, 1, office,
           appendix_links)
    body = ET.SubElement(root, "DECLARBODY")
    add(body, "HZ", 1)
    add(body, "HZY", d.year)
    add(body, "HZM", d.month)
    add(body, "HNAME", org.full_name or org.org_name)
    add(body, "HTIN", org.edrpou or "")
    add(body, "HNPDV", required(org.ipn, _("ІПН організації")))
    add(body, "HLOC", required(org.legal_address, _("Юридична адреса")))
    add(body, "HSTI", required(org.tax_office_name, _("Найменування контролюючого органу")))
    lines = {str(l.row): l for l in ret.lines}

    def amount(row, field):
        return flt(lines[row].get(field), 2) if row in lines else 0

    for total, parts, field in (
        ("3", ("3.7", "3.14"), "base_amount"),
        ("6.3", ("6.7", "6.14"), "vat_amount"),
    ):
        if amount(total, field) != flt(sum(amount(row, field) for row in parts), 2):
            frappe.throw(_("Рядок декларації {0}: розподіліть суму між ставками 7 % і 14 %").format(total))

    # Internal summary keys predate the official row numbering. Translate by meaning.
    values = (
        ("R11GA", amount("1", "base_amount")),
        ("R11GB", amount("6.1", "vat_amount")),
        ("R12GA", amount("3.7", "base_amount")),
        ("R12GB", amount("6.7", "vat_amount")),
        ("R13GA", amount("3.14", "base_amount")),
        ("R13GB", amount("6.14", "vat_amount")),
        ("R21GA", amount("2", "base_amount")),
        ("R90GB", amount("10.1", "vat_amount")),
        ("R101GA", amount("13", "base_amount")),
        ("R101GB", amount("13", "vat_amount")),
        ("R140GB", amount("15", "vat_amount")),
        ("R170GB", amount("16", "vat_amount")),
        ("R180GB", amount("17", "vat_amount")),
        ("R190GB", amount("18", "vat_amount")),
    )
    for tag, value in values:
        if value:
            add(body, tag, whole(value))
    add(body, "HFILL", ddmmyyyy(fill_date or getdate()))
    add(body, "HBOS", signer)
    add(body, "HKBOS", signer_ipn)
    return {
        "filename": package_filename(org, office, "001", version, ret.period_from),
        "schema_version": info["schema_version"],
        "xml": validated_xml(root, info["xsd"]),
    }


def _appendix_start(ret, sub, schema, fill_date, main_link):
    org = frappe.get_doc("UA Organization", ret.organization)
    office, signer, signer_ipn = filing_details(org)
    period = getdate(ret.period_from)
    info = regulatory.form_version_info(f"VAT_APPENDIX_{sub}", period.replace(day=1), 26, schema)
    root = new_root(info["xsd"])
    header(root, org, "J02", sub, info["version"], fill_date, period.month, period.year, 1,
           office, [main_link])
    body = ET.SubElement(root, "DECLARBODY")
    add(body, "HZ", 1)
    add(body, "HZY", period.year)
    add(body, "HZM", period.month)
    add(body, "HNAME", org.full_name or org.org_name)
    add(body, "HTIN", org.edrpou or "")
    add(body, "HNPDV", required(org.ipn, _("ІПН організації")))
    result = {
        "filename": package_filename(org, office, sub, info["version"], ret.period_from),
        "schema_version": info["schema_version"],
    }
    return root, body, result, signer, signer_ipn, info


def _appendix_finish(root, body, result, signer, signer_ipn, info, fill_date):
    add(body, "HFILL", ddmmyyyy(fill_date))
    add(body, "HBOS", signer)
    add(body, "HKBOS", signer_ipn)
    result["xml"] = validated_xml(root, info["xsd"])
    return result


def _d1_ipn(row):
    """ІПН of the counterparty for Д1 columns «G2»: 9-12 digits, or the sign of a non-payer."""
    ipn = str(row.counterparty_ipn or "")
    if ipn == "Неплатник":
        return "100000000000"
    if not (ipn.isdigit() and 9 <= len(ipn) <= 12):
        frappe.throw(_("Для Д1 вкажіть ІПН контрагента в документі {0} (9–12 цифр)").format(row.number))
    return ipn


def _appendix_d1(ret, fill_date, main_link):
    root, body, result, signer, signer_ipn, info = _appendix_start(
        ret, "005", SCHEMA_D1, fill_date, main_link)
    # Table 1.1 (ПН) and 1.2.1 (РК) hold issued documents absent from ЄРПН at filing.
    issued = {"UA Tax Invoice": [], "UA Tax Adjustment": []}
    received = []
    for row in ret.appendix_d1:
        if row.section == "I":
            status = frappe.db.get_value(row.tax_invoice_type, row.tax_invoice, "erpn_status") if row.tax_invoice else None
            if status != tax.STATUS_REGISTERED:
                issued[row.tax_invoice_type].append(row)
        elif row.section == "II":
            received.append(row)
    for prefix, rows in (("T111", issued[tax.PN]), ("T121", issued[tax.RK])):
        for tag, value in ((prefix + "RXXXXG2", _d1_ipn),
                           (prefix + "RXXXXG3D", lambda r: ddmmyyyy(r.date)),
                           (prefix + "RXXXXG4S", lambda r: r.number),
                           (prefix + "RXXXXG6", lambda r: money(r.base_amount)),
                           (prefix + "RXXXXG7", lambda r: money(r.vat_amount))):
            for i, row in enumerate(rows, start=1):
                add(body, tag, value(row), ROWNUM=i)
        total = "R0111" if prefix == "T111" else "R0121"
        if rows:
            add(body, total + "G6", whole(sum(flt(r.base_amount) for r in rows)))
            add(body, total + "G7", whole(sum(flt(r.vat_amount) for r in rows)))
    for tag, value in (("T21RXXXXG2", _d1_ipn),
                       ("T21RXXXXG31", lambda r: getdate(r.date).month),
                       ("T21RXXXXG32", lambda r: getdate(r.date).year),
                       ("T21RXXXXG6", lambda r: money(r.base_amount)),
                       ("T21RXXXXG7", lambda r: money(r.vat_amount)),
                       ("T21RXXXXG10", lambda r: money(r.vat_amount))):
        for i, row in enumerate(received, start=1):
            add(body, tag, value(row), ROWNUM=i)
    if received:
        add(body, "R021G6", whole(sum(flt(r.base_amount) for r in received)))
        add(body, "R021G7", whole(sum(flt(r.vat_amount) for r in received)))
        add(body, "R021G10", whole(sum(flt(r.vat_amount) for r in received)))
    return _appendix_finish(root, body, result, signer, signer_ipn, info, fill_date)


def _latest_allocation(ret):
    rows = frappe.get_all(
        "UA VAT Allocation", filters={"organization": ret.organization,
                                      "posting_date": ("between", [ret.period_from, ret.period_to]),
                                      "docstatus": 1},
        fields=["taxable_share", "taxable_turnover", "exempt_turnover"],
        order_by="posting_date desc, creation desc", limit=1)
    return rows[0] if rows else None


def _appendix_d5(ret, fill_date, main_link):
    root, body, result, signer, signer_ipn, info = _appendix_start(
        ret, "157", SCHEMA_D5, fill_date, main_link)
    allocation = _latest_allocation(ret)
    if allocation:
        share = flt(allocation.taxable_share, 2)
        if flt(allocation.taxable_turnover) or flt(allocation.exempt_turnover):
            add(body, "R012G4", whole(allocation.taxable_turnover))
            add(body, "R012G5", whole(allocation.exempt_turnover))
        add(body, "R012G6", money(share))
        add(body, "R012G7", money(100 - share))
    return _appendix_finish(root, body, result, signer, signer_ipn, info, fill_date)


def export_return_package(ret, fill_date=None):
    """Return the declaration and independently validated appendix XML files in one ZIP."""
    fill_date = fill_date or getdate()
    org = frappe.get_doc("UA Organization", ret.organization)
    office = required(org.tax_office_code, _("Код контролюючого органу"))
    period = getdate(ret.period_from)
    main_info = regulatory.form_version_info("VAT_RETURN", period.replace(day=1), 26, SCHEMA_VAT)
    main_link = {"type": 2, "sub": "001", "version": main_info["version"],
                 "filename": package_filename(org, office, "001", main_info["version"], ret.period_from)}
    appendices = {}
    if ret.appendix_d1:
        appendices["d1"] = _appendix_d1(ret, fill_date, main_link)
    if ret.appendix_d5 or _latest_allocation(ret):
        appendices["d5"] = _appendix_d5(ret, fill_date, main_link)
    links = []
    for key, value in appendices.items():
        sub = "005" if key == "d1" else "157"
        schema = SCHEMA_D1 if key == "d1" else SCHEMA_D5
        info = regulatory.form_version_info(
            f"VAT_APPENDIX_{sub}", period.replace(day=1), 26, schema)
        links.append({"type": 1, "sub": sub, "version": info["version"],
                      "filename": value["filename"]})
    main = export_return(ret, fill_date, links)
    files = [main, *appendices.values()]
    content = BytesIO()
    with ZipFile(content, "w", ZIP_DEFLATED) as archive:
        for item in files:
            archive.writestr(item["filename"], item["xml"].encode("windows-1251"))
    return {"main": main, "appendices": appendices, "files": files,
            "filename": main["filename"].removesuffix(".xml") + ".zip",
            "zip_base64": base64.b64encode(content.getvalue()).decode("ascii")}


def export_return_with_links(ret, fill_date=None):
    """Export the declaration alone, with the filenames of its applicable appendices."""
    org = frappe.get_doc("UA Organization", ret.organization)
    office = required(org.tax_office_code, _("Код контролюючого органу"))
    links = []
    for rows, sub, schema in ((ret.appendix_d1, "005", SCHEMA_D1),
                              (ret.appendix_d5 or _latest_allocation(ret), "157", SCHEMA_D5)):
        if rows:
            info = regulatory.form_version_info(
                f"VAT_APPENDIX_{sub}", getdate(ret.period_from).replace(day=1), 26, schema)
            links.append({"type": 1, "sub": sub, "version": info["version"],
                          "filename": package_filename(org, office, sub, info["version"], ret.period_from)})
    return export_return(ret, fill_date, links)


def _el(tag, text):
    el = ET.Element(tag)
    el.text = str(text if text is not None else "")
    return el
