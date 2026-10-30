"""Bank statements: import, posting of recognised lines, export of payment orders."""

import base64
from collections import Counter

import frappe
from frappe import _
from frappe.utils import flt, getdate

from ua_accounting.exchange import bank_formats as fmts
from ua_accounting.exchange.common import ExchangeError, decode_text

STATEMENT, LINE, SETTINGS = "UA Bank Statement", "UA Bank Statement Line", "UA Exchange Settings"
ORDER = "UA Payment Order"


def match_counterparty(code):
    """Counterparty by ЄДРПОУ (8 digits) or РНОКПП/ІПН (10 or 12 digits)."""
    code = (code or "").strip()
    if not code.isdigit():
        return None
    return frappe.db.get_value("UA Counterparty", {"edrpou": code}, "name") or frappe.db.get_value("UA Counterparty", {"ipn": code}, "name")


def parse(bank_account, fmt, data):
    account = frappe.get_doc("UA Bank Account", bank_account)
    account.check_permission("read")
    text = fmts.decode(data)
    if fmt == "auto":
        fmt = fmts.detect(text)
    if fmt not in fmts.READERS:
        raise ExchangeError(_("Невідомий формат виписки «{0}»").format(fmt))
    if not (account.iban or "").strip():
        raise ExchangeError(_("У банківського рахунку не заповнено IBAN"))
    parsed = fmts.READERS[fmt](text, account.iban)
    if parsed["iban"] and parsed["iban"] != fmts.norm_iban(account.iban):
        raise ExchangeError(_("IBAN у файлі ({0}) не збігається з IBAN банківського рахунку ({1})").format(parsed["iban"], account.iban))
    if not parsed["lines"] and not parsed.get("opening"):
        raise ExchangeError(_("У файлі немає операцій"))
    return account, fmt, parsed


def line_key(ln):
    """Identity of a bank line: the same payment in a repeated file has the same key."""
    return (ln["posting_date"], ln["number"], ln["amount"], ln["direction"],
            fmts.norm_iban(ln.get("counterparty_iban")), (ln.get("purpose") or "").strip())


def existing_counts(bank_account, lines):
    """{key: [count in the base, name of a statement]} of the lines that are already saved."""
    found = {}
    for ln in lines:
        key = line_key(ln)
        if key in found:
            continue
        rows = frappe.db.sql(
            """select s.name from `tabUA Bank Statement Line` l join `tabUA Bank Statement` s on s.name = l.parent
            where s.bank_account = %s and ifnull(s.format, '') != '' and s.docstatus < 2 and l.posting_date = %s
            and ifnull(l.number, '') = %s and l.amount = %s and l.direction = %s
            and upper(replace(ifnull(l.counterparty_iban, ''), ' ', '')) = %s and trim(ifnull(l.purpose, '')) = %s""",
            (bank_account, ln["posting_date"], ln["number"], ln["amount"], ln["direction"], key[4], key[5]), pluck=True)
        found[key] = [len(rows), rows[0] if rows else None]
    return found


def import_statement(bank_account, fmt, data):
    account, fmt, parsed = parse(bank_account, fmt, data)
    lines = parsed["lines"]
    known = existing_counts(bank_account, lines)
    fresh, duplicates, statement = [], 0, None
    for ln in lines:
        entry = known[line_key(ln)]
        if entry[0] > 0:
            entry[0] -= 1
            duplicates += 1
            statement = statement or entry[1]
        else:
            fresh.append(ln)
    matched = 0
    for ln in fresh:
        ln["counterparty"] = match_counterparty(ln["counterparty_edrpou"])
        ln["status"] = "Розпізнано" if ln["counterparty"] else "Нове"
        matched += 1 if ln["counterparty"] else 0
    receipts = sum(ln["amount"] for ln in lines if ln["direction"] == fmts.CREDIT)
    payments = sum(ln["amount"] for ln in lines if ln["direction"] == fmts.DEBIT)
    opening, closing, warnings = parsed["opening"], parsed["closing"], list(parsed["warnings"])
    balance_ok = None
    if opening is not None and closing is not None:
        balance_ok = round(opening + receipts - payments, 2) == round(closing, 2)
        if not balance_ok:
            warnings.append(_("Залишки не сходяться: {0} + {1} − {2} ≠ {3}").format(opening, receipts, payments, closing))
    if fresh:
        dates = [ln["posting_date"] for ln in lines]
        doc = frappe.get_doc({
            "doctype": STATEMENT, "organization": account.organization, "bank_account": bank_account, "format": fmt,
            "posting_date": parsed["date_to"] or max(dates), "date_from": parsed["date_from"] or min(dates),
            "date_to": parsed["date_to"] or max(dates), "opening_balance": opening or 0, "closing_balance": closing or 0,
            "currency": account.currency or "UAH", "exchange_rate": 1, "lines": fresh,
        })
        doc.insert(ignore_permissions=True)
        statement = doc.name
    return {
        "statement": statement, "lines": len(lines), "new": len(fresh), "duplicates": duplicates, "matched": matched,
        "unmatched": len(fresh) - matched, "opening_balance": opening, "closing_balance": closing, "balance_ok": balance_ok,
        "warnings": warnings, "organization": account.organization,
    }


def pick_contract(counterparty, organization, direction):
    kind = "З покупцем" if direction == fmts.CREDIT else "З постачальником"
    rows = frappe.get_all("UA Counterparty Contract", filters={"counterparty": counterparty, "organization": organization},
                          fields=["name", "contract_kind"], order_by="creation asc")
    rows.sort(key=lambda r: r.contract_kind != kind)
    return rows[0].name if rows else None


def post_statement(name):
    frappe.db.sql("select name from `tabUA Bank Statement` where name = %s for update", name)
    statement = frappe.get_doc(STATEMENT, name)
    statement.check_permission("read")
    if not statement.format:
        raise ExchangeError(_("Це не виписка, завантажена з файлу"))
    item = frappe.db.get_single_value(SETTINGS, "default_cash_flow_item")
    todo = [ln for ln in statement.lines if ln.status == "Розпізнано"]
    if todo and not item:
        raise ExchangeError(_("Вкажіть статтю руху коштів за замовчуванням у налаштуваннях обміну"))
    posted = skipped = 0
    for ln in todo:
        contract = pick_contract(ln.counterparty, statement.organization, ln.direction)
        if not contract:
            skipped += 1
            continue
        incoming = ln.direction == fmts.CREDIT
        doctype = "UA Cash Receipt" if incoming else "UA Cash Payment"
        doc = frappe.get_doc({
            "doctype": doctype, "organization": statement.organization, "posting_date": ln.posting_date, "cash_type": "Банк",
            "bank_account": statement.bank_account, "cash_flow_item": item, "amount": ln.amount,
            "currency": statement.currency or "UAH", "counterparty": ln.counterparty, "contract": contract,
            "operation_type": "Оплата від покупця" if incoming else "Оплата постачальнику",
            "settlement_type": "Оплата за реалізацію" if incoming else "Оплата за надходження", "comment": ln.purpose,
        })
        doc.insert(ignore_permissions=True)
        doc.submit()
        frappe.db.set_value(LINE, ln.name, {"status": "Проведено", "document_type": doctype, "document": doc.name})
        posted += 1
    return {"posted": posted, "skipped": skipped, "organization": statement.organization}


# ------------------------------------------------------------------ payment orders
def export_orders(names, fmt):
    if not names:
        raise ExchangeError(_("Оберіть платіжні доручення"))
    if fmt not in fmts.FORMATS:
        raise ExchangeError(_("Невідомий формат «{0}»").format(fmt))
    docs = []
    for name in dict.fromkeys(names):
        doc = frappe.get_doc(ORDER, name)
        doc.check_permission("read")
        if doc.docstatus != 1:
            raise ExchangeError(_("Платіжне доручення {0} не проведене: вивантажують лише проведені").format(name))
        docs.append(doc)
    if len({d.bank_account for d in docs}) > 1 or len({d.organization for d in docs}) > 1:
        raise ExchangeError(_("Доручення мають бути з одного банківського рахунку"))
    first = docs[0]
    iban = fmts.norm_iban(frappe.db.get_value("UA Bank Account", first.bank_account, "iban"))
    if not iban:
        raise ExchangeError(_("У банківського рахунку не заповнено IBAN"))
    orders = []
    for d in docs:
        if not (d.recipient_iban and d.recipient_name):
            raise ExchangeError(_("Доручення {0}: вкажіть отримувача та його IBAN").format(d.name))
        orders.append({"number": d.number or d.name, "date": getdate(d.posting_date), "amount": flt(d.amount, 2),
                       "recipient_name": d.recipient_name, "recipient_iban": d.recipient_iban,
                       "recipient_edrpou": d.recipient_edrpou, "purpose": d.purpose})
    org = frappe.db.get_value("UA Organization", first.organization, ["org_name", "full_name", "edrpou"], as_dict=True)
    if fmt == "privat24":
        text, encoding, ext = fmts.export_privat24(orders), "utf-8", "csv"
    else:
        info = {"name": org.full_name or org.org_name, "edrpou": org.edrpou}
        text, encoding, ext = fmts.export_ibank2(orders, iban, info), "windows-1251", "txt"
    for d in docs:
        if d.status == "Створено":
            frappe.db.set_value(ORDER, d.name, "status", "Експортовано", update_modified=False)
    stamp = max(o["date"] for o in orders).strftime("%Y%m%d")
    return {
        "filename": f"platizhki_{fmt}_{stamp}.{ext}", "encoding": encoding, "count": len(orders),
        "total": round(sum(o["amount"] for o in orders), 2),
        "content": base64.b64encode(text.encode(encoding, errors="replace")).decode("ascii"), "organization": first.organization,
    }
