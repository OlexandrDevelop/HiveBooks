"""Opening balances: one submitted `UA Journal Operation` against the balance account.

Everything is checked first. One error stops the import and nothing is posted.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.exchange.catalogs import CP, ITEM, WH
from ua_accounting.exchange.common import ExchangeError

# 1C uses the service account 000; the chart of the app has no such account, so the first leaf of the group 40 is used
BALANCE_ACCOUNT = "401"
CONTENT = "Введення залишків (імпорт)"
SIDES = {"Дт": "dr", "Кт": "cr"}


def subconto_doctypes(account):
    return frappe.db.sql(
        """select t.reference_doctype from `tabUA Account Subconto` s
        left join `tabUA Subconto Type` t on t.name = s.subconto_type
        where s.parent = %s and s.parenttype = 'UA Account' order by s.idx""", account, pluck=True)


def find_counterparty(code):
    """By ЄДРПОУ (8 digits) or РНОКПП/ІПН (10 or 12 digits)."""
    if not code:
        return None
    return frappe.db.get_value(CP, {"edrpou": code}, "name") or frappe.db.get_value(CP, {"ipn": code}, "name")


def find_contract(counterparty, organization, number, account):
    kind = "З покупцем" if account.startswith("36") else "З постачальником" if account.startswith("63") else "Інше"
    filters = {"counterparty": counterparty, "organization": organization}
    if number:
        found = frappe.db.get_value("UA Counterparty Contract", dict(filters, contract_no=number), "name")
    else:
        found = (frappe.db.get_value("UA Counterparty Contract", dict(filters, contract_kind=kind), "name")
                 or frappe.db.get_value("UA Counterparty Contract", filters, "name"))
    if found:
        return found, False
    doc = frappe.get_doc({"doctype": "UA Counterparty Contract", "counterparty": counterparty, "organization": organization,
                          "contract_kind": kind, "contract_no": number or None, "currency": "UAH",
                          "contract_title": f"Договір №{number}" if number else "Основний договір"})
    doc.insert(ignore_permissions=True)
    return doc.name, True


def resolve(row, organization, state):
    """The entry (dict) of one row, or raises with the message of the row."""
    account = row["account"]
    acc = frappe.db.get_value("UA Account", account, ["is_group", "off_balance"], as_dict=True) if account else None
    if not acc:
        frappe.throw(_("Рахунок {0} не знайдено").format(account or "—"))
    if acc.is_group:
        frappe.throw(_("Рахунок {0} є групою: оберіть рахунок нижчого рівня").format(account))
    if acc.off_balance:
        frappe.throw(_("Позабалансовий рахунок {0} не підтримується").format(account))
    side = SIDES.get(row["side"])
    if not side:
        frappe.throw(_("Сторона має бути «Дт» або «Кт»"))
    try:
        amount = flt(str(row["amount"]).replace(",", ".").replace(" ", ""))
        quantity = flt(str(row["quantity"] or 0).replace(",", ".").replace(" ", ""))
    except Exception:
        frappe.throw(_("Сума або кількість не є числом"))
    if amount <= 0:
        frappe.throw(_("Сума має бути більше нуля"))
    if quantity < 0:
        frappe.throw(_("Кількість не може бути від'ємною"))

    values, counterparty = {}, None
    for doctype in subconto_doctypes(account):
        if doctype == CP:
            counterparty = find_counterparty(row["counterparty"])
            if not counterparty:
                frappe.throw(_("Контрагента {0} не знайдено").format(row["counterparty"] or "—"))
            values[doctype] = counterparty
        elif doctype == WH:
            name = frappe.db.get_value(WH, {"warehouse_name": row["warehouse"], "organization": organization}, "name") if row["warehouse"] else None
            if not name:
                frappe.throw(_("Склад {0} не знайдено").format(row["warehouse"] or "—"))
            values[doctype] = name
        elif doctype == ITEM:
            code = row["item"]
            name = (frappe.db.get_value(ITEM, {"article": code}, "name") or frappe.db.get_value(ITEM, {"item_name": code}, "name")) if code else None
            if not name:
                frappe.throw(_("Номенклатуру {0} не знайдено").format(code or "—"))
            values[doctype] = name
        elif doctype == "UA Bank Account":
            name = frappe.db.get_value("UA Bank Account", {"iban": row["iban"], "organization": organization}, "name") if row["iban"] else None
            if not name:
                frappe.throw(_("Банківський рахунок {0} не знайдено").format(row["iban"] or "—"))
            values[doctype] = name
    if "UA Counterparty Contract" in subconto_doctypes(account):
        values["UA Counterparty Contract"] = find_contract(counterparty, organization, row["contract"], account)
    return {"account": account, "side": side, "amount": amount, "quantity": quantity, "values": values}


def entry_row(item, organization, state):
    types = subconto_doctypes(item["account"])
    side, account = item["side"], item["account"]
    entry = {"amount": item["amount"], "content": CONTENT}
    if side == "dr":
        entry.update(account_dr=account, account_cr=BALANCE_ACCOUNT)
    else:
        entry.update(account_dr=BALANCE_ACCOUNT, account_cr=account)
    for i, doctype in enumerate(types[:3], start=1):
        value = item["values"].get(doctype)
        if isinstance(value, tuple):
            value, created = value
            state["contracts"] += 1 if created else 0
        if value:
            entry[f"subconto_{side}{i}_type"] = doctype
            entry[f"subconto_{side}{i}"] = value
    if item["quantity"]:
        entry[f"quantity_{side}"] = item["quantity"]
    return entry


def post(organization, rows, date, replace=False):
    """Posts the balances; returns the counts. Raises `ExchangeError` with all row errors."""
    if not rows:
        raise ExchangeError(_("У файлі немає рядків залишків"))
    if not date:
        raise ExchangeError(_("Вкажіть дату залишків"))
    if not frappe.db.exists("UA Account", BALANCE_ACCOUNT):
        raise ExchangeError(_("Рахунок {0} для різниці не знайдено").format(BALANCE_ACCOUNT))
    old = frappe.get_all("UA Journal Operation", filters={"organization": organization, "posting_date": date,
                                                          "content": CONTENT, "docstatus": 1}, pluck="name")
    if old and not replace:
        raise ExchangeError(_("Залишки на {0} вже введено ({1}). Увімкніть заміну, щоб скасувати попередні").format(date, ", ".join(old)))
    state, errors, items = {"contracts": 0}, [], []
    for row in rows:
        frappe.db.savepoint("exchange_row")
        try:
            items.append(resolve(row, organization, state))
        except Exception as e:
            frappe.db.rollback(save_point="exchange_row")
            errors.append({"row": row["row"], "message": str(e)})
    if errors:
        raise ExchangeError("\n".join(f"{_('Рядок')} {e['row']}: {e['message']}" for e in errors), errors)
    for name in old:
        previous = frappe.get_doc("UA Journal Operation", name)
        previous.flags.ignore_permissions = True
        previous.cancel()
    state["contracts"] = 0
    entries = [entry_row(item, organization, state) for item in items]
    doc = frappe.get_doc({"doctype": "UA Journal Operation", "organization": organization, "posting_date": date,
                          "content": CONTENT, "entries": entries})
    doc.insert(ignore_permissions=True)
    doc.submit()
    created = {"UA Journal Operation": 1}
    if state["contracts"]:
        created["UA Counterparty Contract"] = state["contracts"]
    return {"created": created, "updated": {}, "errors": [], "operation": doc.name}
