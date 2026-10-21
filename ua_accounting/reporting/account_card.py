"""Картка рахунку: entries of the account(s) with the running balance.

Options (besides the common filters; `accounts` is required):
    show_quantity, show_currency   used only when the accounts have those flags
    limit                          max entry rows (default 3000, max 20000)

The opening balance, the turnovers and the closing balance come from the shared
aggregate (totals + partial months), so they are right even when the rows are cut.
"""

import frappe
from frappe import _

from ua_accounting.reporting import model
from ua_accounting.reporting.chart import Chart
from ua_accounting.reporting.filters import parse_filters
from ua_accounting.reporting.query import Scope, aggregate, list_entries, sum_vectors
from ua_accounting.reporting.titles import Titles

DEFAULT_LIMIT = 3000
MAX_LIMIT = 20000
SIDE_LABEL = {"dr": "Д", "cr": "К"}


def _balance_cells(net):
    side = "dr" if net > 0.004 else "cr" if net < -0.004 else ""
    return {"bal_side": SIDE_LABEL.get(side, ""), "balance": model.money(abs(net))}


def _side_lines(row, side, titles):
    account = row.get(f"account_{side}")
    if not account:
        return []
    lines = [account]
    for i in (1, 2, 3):
        value = row.get(f"subconto_{side}{i}")
        if value:
            lines.append(titles.get(row.get(f"subconto_{side}{i}_type"), value))
    return lines


def build(raw):
    flt_ = parse_filters(raw)
    if not flt_.accounts:
        frappe.throw(_("Вкажіть рахунок"))
    chart = Chart()
    titles = Titles()
    scope = Scope(flt_, chart)
    leaves = list(scope.by_account)
    limit = min(max(flt_.number("limit", DEFAULT_LIMIT), 1), MAX_LIMIT)

    show_qty = flt_.flag("show_quantity", 1) and any(chart.get(a).quantity_accounting for a in leaves)
    show_cur = flt_.flag("show_currency", 1) and any(chart.get(a).currency_accounting for a in leaves)

    opening = sum_vectors(aggregate(scope, None, flt_.date_from))
    turnover = sum_vectors(aggregate(scope, flt_.date_from, flt_.end))
    entries, truncated = list_entries(scope, flt_.date_from, flt_.end, limit)

    pairs = []
    for e in entries:
        for side in ("dr", "cr"):
            for i in (1, 2, 3):
                if e.get(f"subconto_{side}{i}"):
                    pairs.append((e.get(f"subconto_{side}{i}_type"), e[f"subconto_{side}{i}"]))
    titles.preload(pairs)
    titles.preload(("UA Organization", e.organization) for e in entries)
    many_orgs = len({e.organization for e in entries}) > 1

    # ---- columns
    cols = [("date", _("Дата"), "date", "left"), ("doc", _("Документ"), "doc", "left")]
    cols.append(("content", _("Операція"), "text", "left"))
    if many_orgs:
        cols.append(("org", _("Організація"), "text", "left"))
    cols.append(("dr", _("Дебет"), "lines", "left"))
    cols.append(("cr", _("Кредит"), "lines", "left"))
    cols.append(("amt_dr", _("Сума Дт"), "money", "right"))
    cols.append(("amt_cr", _("Сума Кт"), "money", "right"))
    if show_qty:
        cols.append(("qty_dr", _("Кількість Дт"), "qty", "right"))
        cols.append(("qty_cr", _("Кількість Кт"), "qty", "right"))
    if show_cur:
        cols.append(("cur", _("Валюта"), "text", "left"))
        cols.append(("cur_dr", _("Вал. сума Дт"), "money", "right"))
        cols.append(("cur_cr", _("Вал. сума Кт"), "money", "right"))
    cols.append(("bal_side", _("Д/К"), "text", "center"))
    cols.append(("balance", _("Сума"), "money", "right"))
    columns = [{"key": k, "kind": kind, "align": align} for k, _l, kind, align in cols]

    header = [[model.header_cell(label, 1, 2) for k, label, _kd, _al in cols[:-2]]]
    header[0].append(model.header_cell(_("Сальдо"), 2))
    header.append([model.header_cell(_("Д/К")), model.header_cell(_("Сума"))])

    # ---- rows
    net = opening[0] - opening[1]
    rows = [
        model.make_row(
            "open",
            {"doc": _("Сальдо на початок"), **_balance_cells(net)},
            kind="open",
            bold=True,
        )
    ]
    for e in entries:
        dr_in = scope.side_matches(e, "dr")
        cr_in = scope.side_matches(e, "cr")
        net += (e.amount if dr_in else 0) - (e.amount if cr_in else 0)
        cells = {
            "date": model.fmt_date(e.posting_date),
            "doc": f"{_(e.registrar_type)} {e.registrar}",
            "content": e.content or "",
            "org": titles.get("UA Organization", e.organization),
            "dr": _side_lines(e, "dr", titles),
            "cr": _side_lines(e, "cr", titles),
            "amt_dr": model.money(e.amount) if dr_in else None,
            "amt_cr": model.money(e.amount) if cr_in else None,
            "qty_dr": model.qty(e.quantity_dr) if dr_in else None,
            "qty_cr": model.qty(e.quantity_cr) if cr_in else None,
            "cur": ", ".join(
                dict.fromkeys(
                    c for c, ok in ((e.currency_dr, dr_in), (e.currency_cr, cr_in)) if ok and c
                )
            ),
            "cur_dr": model.money(e.currency_amount_dr) if dr_in and e.currency_dr else None,
            "cur_cr": model.money(e.currency_amount_cr) if cr_in and e.currency_cr else None,
            **_balance_cells(net),
        }
        rows.append(
            model.make_row(
                f"e{e.name}",
                cells,
                links={"doc": {"doctype": e.registrar_type, "name": e.registrar}},
            )
        )

    closing = opening[0] - opening[1] + turnover[0] - turnover[1]
    rows.append(
        model.make_row(
            "turn",
            {
                "doc": _("Обороти за період"),
                "amt_dr": model.money(turnover[0]),
                "amt_cr": model.money(turnover[1]),
                "qty_dr": model.qty(turnover[2]),
                "qty_cr": model.qty(turnover[3]),
                "cur_dr": model.money(turnover[4]),
                "cur_cr": model.money(turnover[5]),
            },
            kind="total",
            bold=True,
        )
    )
    rows.append(
        model.make_row(
            "close",
            {"doc": _("Сальдо на кінець"), **_balance_cells(closing)},
            kind="close",
            bold=True,
        )
    )

    message = ""
    if truncated:
        message = _(
            "Показано перші {0} проводок. Обороти та сальдо враховують усі проводки. "
            "Звузьте період або додайте відбір."
        ).format(limit)
    return {
        "report": "account_card",
        "title": _("Картка рахунку {0}").format(", ".join(chart.label(a) for a in flt_.accounts)),
        "lines": model.header_lines(flt_, chart, titles),
        "header": header,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "message": message,
    }
