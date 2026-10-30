"""Import from a ПРРО service (Checkbox, Вчасно.Каса): fiscal receipts and Z-reports.

The service answer is passed as a parameter, the module does not use the network.
Sums are in kopecks, quantity in thousandths (the public Checkbox convention).
A Z-report that equals the sums of its receipts creates and submits the retail report (sales) and the retail return.
"""

import frappe
from dateutil import parser
from frappe import _
from frappe.beeone import providers
from frappe.beeone.providers.fiscal import CARD, CASH, RETURN, SELL, FiscalError, ReceiptImporter
from frappe.utils import cint, flt, today

CASHLESS = "CASHLESS"
ACCEPTED, DIFFERENCE = "Прийнято", "Розбіжність"
KIND = {SELL: "Продаж", RETURN: "Повернення"}
SERVICE_KIND = {"SELL": SELL, "RETURN": RETURN}
SERVICE_PAYMENT = {"CASH": CASH, CASHLESS: CARD}
PROVIDER_NAME = "checkbox"


class CheckboxImporter(ReceiptImporter):
    """The answer of Checkbox / Вчасно.Каса in the neutral form of the core contract (kopecks, thousandths)."""

    name = PROVIDER_NAME

    def normalize_receipt(self, raw):
        kind = SERVICE_KIND.get(raw.get("type"))
        if not kind:
            raise FiscalError(_("Чек {0}: невідомий тип {1}").format(raw.get("id"), raw.get("type")))
        payments = {CASH: 0, CARD: 0}
        for pay in raw.get("payments") or []:
            slot = SERVICE_PAYMENT.get(pay.get("type"))
            if not slot:
                raise FiscalError(_("Чек {0}: невідомий вид оплати {1}").format(raw.get("id"), pay.get("type")))
            payments[slot] += flt(pay.get("value"))
        shift = raw.get("shift")
        return {
            "id": str(raw.get("id") or ""),
            "kind": kind,
            "shift": (shift.get("serial") if isinstance(shift, dict) else shift),
            "fiscal_code": raw.get("fiscal_code"),
            "fiscal_datetime": raw.get("fiscal_date"),
            "total": flt(raw.get("total_sum")),
            "payments": payments,
            "goods": [
                {
                    "code": (row.get("good") or {}).get("code"),
                    "quantity": flt(row.get("quantity")),
                    "price": flt((row.get("good") or {}).get("price")),
                }
                for row in raw.get("goods") or []
            ],
        }

    def normalize_z_report(self, raw):
        out = {key: raw.get(key) for key in ("id", "serial", "opened_at", "closed_at")}
        out.update({key: flt(raw.get(key)) for key in ("sell_cash", "sell_card", "return_cash", "return_card")})
        return out


def importer():
    return providers.get_receipt_importer(PROVIDER_NAME)


def money(kopecks):
    return flt(flt(kopecks) / 100, 2)


def item_by_code(code):
    names = frappe.get_all("UA Item", filters={"article": str(code or "")}, pluck="name", limit=2)
    if len(names) != 1:
        frappe.throw(_("Номенклатуру з артикулом {0} не знайдено або їх кілька").format(code))
    return names[0]


def read_register(cash_register):
    frappe.has_permission("UA Fiscal Receipt", "create", throw=True)
    frappe.has_permission("UA Z Report", "create", throw=True)
    return frappe.get_doc("UA Cash Register", cash_register)


def moment(value):
    """Naive local datetime of an ISO string of the service (receipt and Z-report use the same parser)."""
    return parser.isoparse(value).replace(tzinfo=None) if value else None


def parse_receipt(receipt):
    """UA Fiscal Receipt values from the answer of the service."""
    try:
        norm = importer().normalize_receipt(receipt)
    except FiscalError as error:
        frappe.throw(str(error))
    total = money(norm["total"])
    paid = {CASH: money(norm["payments"][CASH]), CARD: money(norm["payments"][CARD])}
    if abs(paid[CASH] + paid[CARD] - total) > 0.001:
        frappe.throw(_("Чек {0}: оплата не дорівнює сумі чека").format(norm["id"]))
    goods, goods_total = [], 0.0
    for row in norm["goods"]:
        quantity = flt(row["quantity"] / 1000, 3)
        price = money(row["price"])
        amount = flt(quantity * price, 2)
        goods_total = flt(goods_total + amount, 2)
        goods.append({"item": item_by_code(row["code"]), "quantity": quantity, "price": price, "amount": amount})
    if abs(goods_total - total) > 0.001:
        frappe.throw(_("Чек {0}: сума товарів {1} не дорівнює сумі чека {2}").format(norm["id"], goods_total, total))
    return {
        "external_id": norm["id"],
        "shift_number": cint(norm["shift"]),
        "fiscal_code": norm["fiscal_code"],
        "fiscal_datetime": moment(norm["fiscal_datetime"]),
        "receipt_type": KIND[norm["kind"]],
        "total_amount": total,
        "cash_amount": paid[CASH],
        "card_amount": paid[CARD],
        "goods": goods,
    }


@frappe.whitelist(methods=["POST"])
def import_receipts(cash_register, receipts):
    """Save fiscal receipts of the service. Known ids are skipped. Returns the new names."""
    register = read_register(cash_register)
    receipts = frappe.parse_json(receipts) if isinstance(receipts, str) else receipts
    parsed, seen = [], set()
    for receipt in receipts or []:
        external_id = str(receipt.get("id") or "")
        if not external_id:
            frappe.throw(_("Чек без ідентифікатора"))
        if external_id in seen or frappe.db.exists("UA Fiscal Receipt", {"external_id": external_id}):
            continue
        seen.add(external_id)
        parsed.append(parse_receipt(receipt))
    names = []
    for values in parsed:
        doc = frappe.get_doc({"doctype": "UA Fiscal Receipt", "cash_register": register.name, "organization": register.organization, **values})
        doc.insert()
        names.append(doc.name)
    return names


def shift_totals(receipts):
    total = {"sell_cash": 0.0, "sell_card": 0.0, "return_cash": 0.0, "return_card": 0.0}
    for r in receipts:
        prefix = "sell" if r.receipt_type == "Продаж" else "return"
        total[f"{prefix}_cash"] = flt(total[f"{prefix}_cash"] + r.cash_amount, 2)
        total[f"{prefix}_card"] = flt(total[f"{prefix}_card"] + r.card_amount, 2)
    return total


def shift_receipts(register, receipts, serial, opened_at, closed_at):
    """The unlinked receipts that belong to the shift of a Z-report.

    1. Receipts carry a shift number: those with the number of the Z-report.
    2. The Z-report has a close time: receipts after its open time (or after the close time of the previous
       Z-report of the register) up to the close time.
    3. Else all unlinked receipts, that is the receipts since the last Z-report (import order).
    """
    if any(r.shift_number for r in receipts):
        return [r for r in receipts if r.shift_number and r.shift_number == cint(serial)]
    if closed_at:
        start = opened_at or frappe.db.get_value(
            "UA Z Report", {"cash_register": register, "closed_at": ("<", closed_at)}, "closed_at", order_by="closed_at desc"
        )
        return [r for r in receipts if r.fiscal_datetime and (not start or r.fiscal_datetime > start) and r.fiscal_datetime <= closed_at]
    return receipts


def collect_goods(receipts, kind):
    """Goods of the receipts of one type: rows with the same item and price are joined."""
    rows = {}
    for r in receipts:
        if r.receipt_type != kind:
            continue
        for g in frappe.get_doc("UA Fiscal Receipt", r.name).goods:
            key = (g.item, flt(g.price))
            rows[key] = flt(rows.get(key, 0) + g.quantity, 3)
    return [{"item": item, "quantity": qty, "price": price} for (item, price), qty in rows.items()]


@frappe.whitelist(methods=["POST"])
def import_z_report(cash_register, report):
    """Save a Z-report. If it equals the receipts of the shift, post the retail report and the retail return."""
    register = read_register(cash_register)
    report = frappe.parse_json(report) if isinstance(report, str) else report
    external_id = str(report.get("id") or "")
    if not external_id:
        frappe.throw(_("Z-звіт без ідентифікатора"))
    old = frappe.db.get_value("UA Z Report", {"external_id": external_id}, ["name", "status"], as_dict=True)
    if old and old.status == DIFFERENCE:
        # a discrepant Z-report can be sent again once the missing receipts are imported
        for name in frappe.get_all("UA Fiscal Receipt", filters={"z_report": old.name}, pluck="name"):
            frappe.db.set_value("UA Fiscal Receipt", name, "z_report", None, update_modified=False)
        frappe.delete_doc("UA Z Report", old.name, ignore_permissions=True)
        old = None
    if old:
        frappe.throw(_("Z-звіт {0} уже завантажено").format(external_id))
    norm = importer().normalize_z_report(report)
    values = {key: money(norm[key]) for key in ("sell_cash", "sell_card", "return_cash", "return_card")}
    receipts = frappe.get_all(
        "UA Fiscal Receipt",
        filters={"cash_register": register.name, "z_report": ("is", "not set")},
        fields=["name", "receipt_type", "cash_amount", "card_amount", "fiscal_datetime", "shift_number"],
        order_by="fiscal_datetime asc, creation asc",
    )
    opened_at, closed_at = moment(report.get("opened_at")), moment(report.get("closed_at"))
    receipts = shift_receipts(register.name, receipts, report.get("serial"), opened_at, closed_at)
    day = max((r.fiscal_datetime for r in receipts if r.fiscal_datetime), default=None)
    day = closed_at.date() if closed_at else day.date() if day else today()
    totals = shift_totals(receipts)
    equal = all(abs(totals[k] - values[k]) <= 0.001 for k in values)
    z = frappe.get_doc(
        {
            "doctype": "UA Z Report",
            "cash_register": register.name,
            "organization": register.organization,
            "external_id": external_id,
            "shift_number": report.get("serial"),
            "posting_date": day,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "status": ACCEPTED if equal else DIFFERENCE,
            **values,
        }
    )
    z.insert()
    result = {"z_report": z.name, "retail_report": None, "retail_return": None}
    # the receipts of the shift leave the pool also when the Z-report is a discrepancy
    for r in receipts:
        frappe.db.set_value("UA Fiscal Receipt", r.name, "z_report", z.name, update_modified=False)
    if not equal:
        return result
    head = {"organization": register.organization, "posting_date": day, "warehouse": register.warehouse, "cash_desk": register.cash_desk, "bank_account": register.bank_account}
    sales = collect_goods(receipts, "Продаж")
    if sales:
        doc = frappe.get_doc(
            {"doctype": "UA Retail Sales Report", **head, "outlet_type": "Автоматизована", "cash_amount": values["sell_cash"], "card_amount": values["sell_card"], "goods": sales}
        )
        doc.insert()
        doc.submit()
        result["retail_report"] = doc.name
    returns = collect_goods(receipts, "Повернення")
    if returns:
        refund = "Змішано" if values["return_cash"] and values["return_card"] else "Картка" if values["return_card"] else "Готівка"
        doc = frappe.get_doc(
            {"doctype": "UA Retail Return", **head, "refund_type": refund, "cash_amount": values["return_cash"], "card_amount": values["return_card"], "goods": returns}
        )
        doc.insert()
        doc.submit()
        result["retail_return"] = doc.name
    frappe.db.set_value("UA Z Report", z.name, {"retail_report": result["retail_report"], "retail_return": result["retail_return"]}, update_modified=False)
    return result
