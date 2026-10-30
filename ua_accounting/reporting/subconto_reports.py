"""Reports by subconto: subconto analysis, OSV by subconto, subconto card."""

import frappe
from frappe import _

from ua_accounting.reporting import model
from ua_accounting.reporting.filters import as_list
from ua_accounting.reporting.more_common import (
    BAL_KEYS,
    add_bal,
    bal_cols,
    bal_row,
    col,
    drill,
    is_zero,
    make_table,
    result,
    split,
    total_row,
)
from ua_accounting.reporting.query import Scope, aggregate, list_entries

NOT_SET = "<не задано>"
CARD_LIMIT = 5000


def _type_doctype(ctx, stype):
    t = ctx.chart.types.get(stype)
    return t.reference_doctype if t and t.reference_doctype and not t.is_dynamic else None


def _folded(scope, date_from, end):
    """{path: [opening net, debit, credit]} summed over accounts and currencies."""
    out = {}

    def add(res, i):
        for (_acc, path, _cur), vec in res.items():
            row = out.setdefault(path, [0.0, 0.0, 0.0])
            if i == 0:
                row[0] += vec[0] - vec[1]
            else:
                row[1] += vec[0]
                row[2] += vec[1]

    add(aggregate(scope, None, date_from), 0)
    add(aggregate(scope, date_from, end), 1)
    return out


def _title(ctx, doctype, value):
    return ctx.titles.get(doctype, value) if doctype and value else (value or _(NOT_SET))


# ---------------------------------------------------------------- subconto analysis


def subconto_analysis(ctx):
    raw = ctx.need("subconto_type", _("Вкажіть вид субконто"))
    stype = ctx.type_code(raw)
    doctype = _type_doctype(ctx, stype)
    scope = Scope(ctx.flt, ctx.chart, levels=[("type", stype)])
    data = _folded(scope, ctx.flt.date_from, ctx.flt.end)
    if doctype:
        ctx.titles.preload((doctype, p[0]) for p in data if p[0])

    items = []
    for (value,), (opening, debit, credit) in data.items():
        if not value:  # accounts without this subconto have no value
            continue
        row = bal_row(opening, debit, credit)
        if is_zero(row):
            continue
        items.append((_title(ctx, doctype, value), value, row))
    items.sort(key=lambda x: (x[0].lower(), x[1]))

    cols = bal_cols(_("Субконто"))
    cols.insert(1, col("code", _("Код"), "text"))
    rows, table_rows, totals = [], [], {}
    for title, value, row in items:
        filters = ctx.base_filters(subconto_type=raw, subconto=value)
        if ctx.flt.accounts:
            filters["accounts"] = list(ctx.flt.accounts)
        if ctx.flt.subconto:
            filters["subconto"] = [{"type": s["type"], "value": v} for s in ctx.flt.subconto for v in s["values"]]
            filters["subconto"].append({"type": raw, "value": value})
        d = drill("ua-subconto-card", filters)
        rows.append({"subconto_type": raw, "subconto": value, "title": title, **row, "drill": d})
        table_rows.append(model.make_row(f"s{value}", {"label": title, "code": value, **row}, drill=d))
        add_bal(totals, row)
    for k in BAL_KEYS:
        totals.setdefault(k, 0.0)
    table_rows.append(total_row(totals))
    title = _("Аналіз субконто: {0}").format(ctx.chart.type_title(stype))
    table = make_table("subconto_analysis", title, ctx.lines(), cols, table_rows)
    return result(table, cols, rows, totals)


# ---------------------------------------------------------------- OSV by subconto


def osv_subconto(ctx):
    account = ctx.account()
    raw_levels = as_list(ctx.opt("levels"))
    if not 1 <= len(raw_levels) <= 3:
        frappe.throw(_("Вкажіть від 1 до 3 видів субконто"))
    levels = [ctx.type_code(t) for t in raw_levels]
    doctypes = [_type_doctype(ctx, t) for t in levels]
    scope = Scope(ctx.flt, ctx.chart, levels=[("type", t) for t in levels])
    leaves = _folded(scope, ctx.flt.date_from, ctx.flt.end)
    n = len(levels)
    for path in leaves:
        ctx.titles.preload((doctypes[i], v) for i, v in enumerate(path) if v and doctypes[i])

    # every prefix of a leaf path is a group row
    nodes = {}
    for path, vec in leaves.items():
        for k in range(1, n + 1):
            node = nodes.setdefault(path[:k], [0.0, 0.0, 0.0])
            for i in range(3):
                node[i] += vec[i]

    def sort_key(path):
        return tuple((_title(ctx, doctypes[i], v).lower(), v) for i, v in enumerate(path))

    def row_id(path):
        return "|".join(path)

    rows, table_rows, totals = [], [], {}
    alive = {}
    for path in sorted(nodes, key=sort_key):
        bal = bal_row(*nodes[path])
        alive[path] = not is_zero(bal)
        if not alive[path]:
            continue
        level = len(path)
        filters = ctx.base_filters(
            accounts=[account],
            subconto_type=raw_levels[level - 1],
            subconto=[{"type": raw_levels[i], "value": v} for i, v in enumerate(path)],
        )
        d = drill("ua-subconto-card", filters)
        rows.append({"level": level, "path": list(path), **bal, "drill": d})
        label = _title(ctx, doctypes[level - 1], path[-1])
        table_rows.append(
            model.make_row(
                row_id(path),
                {"label": label, **bal},
                level=level - 1,
                kind="group" if level < n else "item",
                bold=level < n,
                parent=row_id(path[:-1]) if level > 1 else None,
                drill=d,
            )
        )
        if level == 1:
            add_bal(totals, bal)
    for k in BAL_KEYS:
        totals.setdefault(k, 0.0)
    cols = bal_cols(_("Субконто"))
    table_rows.append(total_row(totals))
    title = _("ОСВ по субконто: рахунок {0}").format(ctx.chart.label(account))
    table = make_table("osv_subconto", title, ctx.lines(), cols, table_rows)
    return result(table, cols, rows, totals)


# ---------------------------------------------------------------- subconto card


def subconto_card(ctx):
    cols = [
        col("date", _("Дата"), "date"),
        col("doc", _("Документ"), "doc"),
        col("content", _("Операція"), "text"),
        col("account_dr", _("Дебет"), "text", "center"),
        col("account_cr", _("Кредит"), "text", "center"),
        col("debit", _("Сума Дт"), "money"),
        col("credit", _("Сума Кт"), "money"),
        col("balance_dr", _("Дебет"), "money", group=_("Сальдо")),
        col("balance_cr", _("Кредит"), "money", group=_("Сальдо")),
    ]
    empty = {"opening": {"debit": 0.0, "credit": 0.0}, "closing": {"debit": 0.0, "credit": 0.0}, "totals": {"debit": 0.0, "credit": 0.0}}
    raw = ctx.opt("subconto_type") or (ctx.flt.subconto[-1]["type"] if ctx.flt.subconto else "")
    if not raw:
        frappe.throw(_("Вкажіть вид субконто"))
    stype = ctx.type_code(raw)
    title = _("Картка субконто: {0}").format(ctx.chart.type_title(stype))
    if not ctx.flt.subconto:
        table = make_table("subconto_card", title, ctx.lines(), cols, [], message=_("Вкажіть значення субконто."))
        return result(table, cols, [], empty["totals"], opening=empty["opening"], closing=empty["closing"])

    scope = Scope(ctx.flt, ctx.chart)
    opening = _sum_net(aggregate(scope, None, ctx.flt.date_from))
    turn = aggregate(scope, ctx.flt.date_from, ctx.flt.end)
    debit = sum(v[0] for v in turn.values())
    credit = sum(v[1] for v in turn.values())
    entries, truncated = list_entries(scope, ctx.flt.date_from, ctx.flt.end, CARD_LIMIT)

    net = opening
    rows, table_rows = [], []
    o_dr, o_cr = split(opening)
    table_rows.append(
        model.make_row("open", {"doc": _("Сальдо на початок"), "balance_dr": o_dr, "balance_cr": o_cr}, kind="open", bold=True)
    )
    for e in entries:
        d_amt = e.amount if scope.side_matches(e, "dr") else 0
        c_amt = e.amount if scope.side_matches(e, "cr") else 0
        net += d_amt - c_amt
        b_dr, b_cr = split(net)
        row = {
            "posting_date": str(e.posting_date),
            "registrar_type": e.registrar_type,
            "registrar": e.registrar,
            "account_dr": e.account_dr,
            "account_cr": e.account_cr,
            "debit": model.money(d_amt),
            "credit": model.money(c_amt),
            "balance_dr": b_dr,
            "balance_cr": b_cr,
        }
        rows.append(row)
        table_rows.append(
            model.make_row(
                f"e{e.name}",
                {
                    "date": model.fmt_date(e.posting_date),
                    "doc": f"{_(e.registrar_type)} {e.registrar}",
                    "content": e.content or "",
                    "account_dr": e.account_dr,
                    "account_cr": e.account_cr,
                    "debit": row["debit"],
                    "credit": row["credit"],
                    "balance_dr": b_dr,
                    "balance_cr": b_cr,
                },
                links={"doc": {"doctype": e.registrar_type, "name": e.registrar}},
            )
        )
    c_dr, c_cr = split(opening + debit - credit)
    totals = {"debit": model.money(debit), "credit": model.money(credit)}
    table_rows.append(
        model.make_row(
            "turn",
            {"doc": _("Обороти за період"), "debit": totals["debit"], "credit": totals["credit"]},
            kind="total",
            bold=True,
        )
    )
    table_rows.append(
        model.make_row("close", {"doc": _("Сальдо на кінець"), "balance_dr": c_dr, "balance_cr": c_cr}, kind="close", bold=True)
    )
    lines = ctx.lines()
    for f in ctx.flt.subconto:
        dt = _type_doctype(ctx, f["type"])
        ctx.titles.preload((dt, v) for v in f["values"] if dt)
        lines.append(f"{ctx.chart.type_title(f['type'])}: " + ", ".join(_title(ctx, dt, v) for v in f["values"]))
    message = _("Показано перші {0} проводок. Обороти та сальдо враховують усі проводки.").format(CARD_LIMIT) if truncated else ""
    table = make_table("subconto_card", title, lines, cols, table_rows, message=message, truncated=truncated)
    return result(
        table,
        cols,
        rows,
        totals,
        opening={"debit": o_dr, "credit": o_cr},
        closing={"debit": c_dr, "credit": c_cr},
    )


def _sum_net(res):
    return sum(v[0] - v[1] for v in res.values())

