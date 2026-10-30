"""Експрес-перевірка ведення обліку: typical errors with links to the documents.

Codes:
    unposted_document   draft (not posted) documents of the period
    red_balance         active account with a credit balance, passive one with a debit balance
    negative_stock      negative quantity on a stock account (class 2) per item and warehouse
Bi-active accounts (type «АП»: settlements 36x, 63x, 68x ...) may have any side.
"""

import frappe
from frappe import _
from frappe.model.base_document import get_controller

from ua_accounting.accounting.documents import AccountingDocument
from ua_accounting.reporting import model
from ua_accounting.reporting.more_common import col, make_table, result
from ua_accounting.reporting.query import Scope, aggregate

ERROR = "Помилка"
WARNING = "Попередження"
CODE_TITLE = {
    "unposted_document": "Не проведений документ",
    "red_balance": "Червоне сальдо",
    "negative_stock": "Від'ємний залишок",
}
EPS = 0.005
# settlement accounts that are bi-active in practice, whatever the chart says
BI_ACTIVE_PREFIXES = ("36", "63", "68")
STOCK_WAREHOUSE_DOCTYPE = "UA Warehouse"
STOCK_ITEM_DOCTYPE = "UA Item"


def _posting_doctypes():
    """Documents that post to the ledger (controllers of AccountingDocument)."""
    out = []
    names = frappe.get_all(
        "DocType", filters={"module": "UA Documents", "is_submittable": 1, "istable": 0}, pluck="name"
    )
    for name in sorted(names):
        meta = frappe.get_meta(name)
        if not (meta.has_field("organization") and meta.has_field("posting_date")):
            continue
        if issubclass(get_controller(name), AccountingDocument):
            out.append(name)
    return out


def _drafts(ctx):
    flt_ = ctx.flt
    for doctype in _posting_doctypes():
        rows = frappe.get_all(
            doctype,
            filters={
                "docstatus": 0,
                "organization": ("in", flt_.organizations),
                "posting_date": ("between", [flt_.date_from, flt_.date_to]),
            },
            fields=["name", "posting_date"],
            order_by="posting_date asc, name asc",
            limit_page_length=0,
        )
        for r in rows:
            yield {
                "code": "unposted_document",
                "severity": WARNING,
                "message": _("Документ {0} {1} від {2} не проведено: він не впливає на облік").format(
                    _(doctype), r.name, model.fmt_date(r.posting_date)
                ),
                "doctype": doctype,
                "name": r.name,
                "account": "",
            }


def _red_balances(ctx):
    chart = ctx.chart
    leaves = [
        a
        for a in chart.all_leaves()
        if not chart.get(a).off_balance
        and chart.get(a).account_type in ("А", "П")
        and not (chart.get(a).account_code or "").startswith(BI_ACTIVE_PREFIXES)
    ]
    scope = Scope(ctx.flt, chart, leaves=leaves)
    net = {}
    for (account, _path, _cur), vec in aggregate(scope, None, ctx.flt.end).items():
        net[account] = net.get(account, 0.0) + vec[0] - vec[1]
    for account in leaves:
        value = net.get(account, 0.0)
        kind = chart.get(account).account_type
        if kind == "А" and value < -EPS:
            side, amount = _("кредитове"), -value
        elif kind == "П" and value > EPS:
            side, amount = _("дебетове"), value
        else:
            continue
        yield {
            "code": "red_balance",
            "severity": ERROR,
            "message": _("Рахунок {0} має {1} сальдо {2} на {3}").format(
                chart.label(account), side, f"{model.money(amount):,.2f}".replace(",", " ").replace(".", ","),
                model.fmt_date(ctx.flt.date_to),
            ),
            "doctype": "UA Account",
            "name": account,
            "account": account,
        }


def _negative_stock(ctx):
    chart = ctx.chart
    item_type = ctx.type_code(STOCK_ITEM_DOCTYPE)
    levels = [("type", item_type), ("type", ctx.type_code(STOCK_WAREHOUSE_DOCTYPE))]
    leaves = [
        a
        for a in chart.all_leaves()
        if chart.get(a).quantity_accounting
        and (chart.get(a).account_code or "").startswith("2")
        and chart.type_index(a, item_type) is not None
    ]
    if not leaves:
        return
    scope = Scope(ctx.flt, chart, levels=levels, leaves=leaves)
    found = []
    for (account, (item, warehouse), _cur), vec in aggregate(scope, None, ctx.flt.end).items():
        if item and vec[2] - vec[3] < -0.0005:
            found.append((account, item, warehouse, vec[2] - vec[3]))
    ctx.titles.preload(("UA Item", f[1]) for f in found)
    for account, item, warehouse, quantity in sorted(found):
        yield {
            "code": "negative_stock",
            "severity": ERROR,
            "message": _("Товар {0}{1}: від'ємний залишок {2} на рахунку {3}").format(
                ctx.titles.get("UA Item", item),
                f" ({warehouse})" if warehouse else "",
                model.qty(quantity),
                chart.label(account),
            ),
            "doctype": "UA Item",
            "name": item,
            "account": account,
        }


def accounting_check(ctx):
    issues = [*_drafts(ctx), *_red_balances(ctx), *_negative_stock(ctx)]
    counts = {}
    for i in issues:
        counts[i["code"]] = counts.get(i["code"], 0) + 1

    cols = [
        col("severity", _("Важливість"), "text"),
        col("kind", _("Проблема"), "text"),
        col("message", _("Опис"), "text"),
        col("doc", _("Посилання"), "doc"),
    ]
    table_rows = []
    for n, i in enumerate(issues):
        table_rows.append(
            model.make_row(
                f"i{n}",
                {
                    "severity": _(i["severity"]),
                    "kind": _(CODE_TITLE[i["code"]]),
                    "message": i["message"],
                    "doc": f"{_(i['doctype'])} {i['name']}",
                },
                links={"doc": {"doctype": i["doctype"], "name": i["name"]}},
            )
        )
    message = "" if issues else _("Помилок не знайдено.")
    table = make_table("accounting_check", _("Експрес-перевірка ведення обліку"), ctx.lines(), cols, table_rows, message=message)
    return result(table, cols, issues, {"count": len(issues)}, issues=issues, counts=counts)
