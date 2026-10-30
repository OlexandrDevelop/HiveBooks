"""Ledger reports: account turnovers, account analysis, general ledger, journal-order,
chess sheet, entries report."""

import frappe
from frappe import _
from frappe.utils import flt

from ua_accounting.reporting import model
from ua_accounting.reporting.more_common import (
    bal_cols,
    bal_row,
    col,
    drill,
    is_zero,
    make_table,
    month_end,
    month_label,
    months,
    result,
    total_row,
)
from ua_accounting.reporting.query import ENTRIES, Scope, aggregate, corr_turnover, side_condition

ENTRIES_LIMIT = 5000
ENTRIES_MAX = 20000


def _net_by_account(res):
    """{account: [net, debit, credit]} from an aggregate() result."""
    out = {}
    for (account, _path, _cur), vec in res.items():
        row = out.setdefault(account, [0.0, 0.0, 0.0])
        row[0] += vec[0] - vec[1]
        row[1] += vec[0]
        row[2] += vec[1]
    return out


def _account_label(ctx, account):
    return ctx.chart.label(account) if account in ctx.chart.accounts else (account or _("Без кореспонденції"))


def _order(ctx):
    return {name: i for i, name in enumerate(ctx.chart.accounts)}


# ---------------------------------------------------------------- account turnovers


def account_turnover(ctx):
    account = ctx.account()
    if (ctx.opt("step") or "month") != "month":
        frappe.throw(_("Підтримується лише крок «місяць»"))
    scope = Scope(ctx.flt, ctx.chart)
    flt_ = ctx.flt
    opening = sum(v[0] - v[1] for v in aggregate(scope, None, flt_.date_from).values())
    start, cur = opening, opening

    cols = bal_cols(_("Період"))
    rows, table_rows, sum_dr, sum_cr = [], [], 0.0, 0.0
    for first, begin, end in months(flt_.date_from, flt_.date_to):
        turn = aggregate(scope, begin, end).values()
        debit, credit = sum(v[0] for v in turn), sum(v[1] for v in turn)
        bal = bal_row(cur, debit, credit)
        cur += debit - credit
        sum_dr += debit
        sum_cr += credit
        if is_zero(bal):
            continue
        d = drill(
            "ua-account-card",
            ctx.base_filters(accounts=[account], date_from=str(begin), date_to=str(month_end(first, flt_.date_to))),
        )
        rows.append({"period": str(first), **bal, "drill": d})
        label = month_label(first)
        table_rows.append(model.make_row(f"m{first}", {"label": label, **bal}, drill=d))
    totals = bal_row(start, sum_dr, sum_cr)
    table_rows.append(total_row(totals))
    title = _("Обороти рахунку {0}").format(ctx.chart.label(account))
    table = make_table("account_turnover", title, ctx.lines(), cols, table_rows)
    return result(table, cols, rows, totals)


# ---------------------------------------------------------------- account analysis / journal-order


def _corr(ctx):
    """({corr: [debit, credit]}, account) for the account of the filter."""
    account = ctx.account()
    scope = Scope(ctx.flt, ctx.chart)
    out = {}
    for (_acc, corr), vec in corr_turnover(scope, ctx.flt.date_from, ctx.flt.end).items():
        row = out.setdefault(corr, [0.0, 0.0])
        row[0] += vec[0]
        row[1] += vec[1]
    return out, account


def _entries_drill(ctx, account, corr, side):
    """Entries where `account` stands on `side` and `corr` on the other one.

    The source filters (accounts, currency, subconto) go along and apply to the side of `account`,
    so the entries report adds up to the clicked number.
    """
    extra = {"accounts": list(ctx.flt.accounts) or [account], "scope_side": side}
    if ctx.flt.currency:
        extra["currency"] = ctx.flt.currency
    if ctx.flt.subconto:
        extra["subconto"] = [dict(s) for s in ctx.flt.subconto]
    pair = {"account_dr": account, "account_cr": corr} if side == "dr" else {"account_dr": corr, "account_cr": account}
    return drill("ua-entries-report", ctx.base_filters(**pair, **extra))


def _scope_sql(ctx, sides=("dr", "cr")):
    """Condition of the common filters (accounts, currency, subconto) for an entries query.

    Returns ("", []) when no such filter is set, ("1 = 0", []) when nothing can match.
    """
    flt_ = ctx.flt
    if not (flt_.accounts or flt_.currency or flt_.subconto):
        return "", []
    cond = side_condition(Scope(flt_, ctx.chart), sides)
    return cond if cond else ("1 = 0", [])


def account_analysis(ctx):
    data, account = _corr(ctx)
    order = _order(ctx)
    cols = [
        col("label", _("Кореспондуючий рахунок"), "label"),
        col("turnover_dr", _("Дебет"), "money", group=_("Обороти за період")),
        col("turnover_cr", _("Кредит"), "money", group=_("Обороти за період")),
    ]
    rows, table_rows, tot_dr, tot_cr = [], [], 0.0, 0.0
    for corr in sorted(data, key=lambda c: order.get(c, 1e9)):
        dr, cr = model.money(data[corr][0]), model.money(data[corr][1])
        if not dr and not cr:
            continue
        d_dr = _entries_drill(ctx, account, corr, "dr")
        d_cr = _entries_drill(ctx, account, corr, "cr")
        d = d_dr if dr else d_cr
        rows.append({"corr_account": corr, "turnover_dr": dr, "turnover_cr": cr, "drill": d})
        table_rows.append(
            model.make_row(
                f"c{corr}",
                {"label": _account_label(ctx, corr), "turnover_dr": dr, "turnover_cr": cr},
                drill=d,
            )
        )
        table_rows[-1]["cell_drill"] = {"turnover_dr": d_dr, "turnover_cr": d_cr}
        tot_dr += dr
        tot_cr += cr
    totals = {"turnover_dr": model.money(tot_dr), "turnover_cr": model.money(tot_cr)}
    table_rows.append(total_row(totals))
    title = _("Аналіз рахунку {0}").format(ctx.chart.label(account))
    table = make_table("account_analysis", title, ctx.lines(), cols, table_rows)
    return result(table, cols, rows, totals)


def journal_order(ctx):
    data, account = _corr(ctx)
    order = _order(ctx)
    cols = [col("label", _("Кореспондуючий рахунок"), "label"), col("amount", _("Сума"), "money")]
    sections = (
        ("credit", 1, "cr", _("Журнал-ордер: обороти по кредиту рахунку {0}")),
        ("debit", 0, "dr", _("Відомість: обороти по дебету рахунку {0}")),
    )
    out, table_rows, totals = {}, [], {}
    for key, idx, side, caption in sections:
        group_id = f"g-{key}"
        table_rows.append(
            model.make_row(group_id, {"label": caption.format(ctx.chart.label(account))}, kind="group", bold=True)
        )
        rows, total = [], 0.0
        for corr in sorted(data, key=lambda c: order.get(c, 1e9)):
            amount = model.money(data[corr][idx])
            if not amount:
                continue
            d = _entries_drill(ctx, account, corr, side)
            rows.append({"corr_account": corr, "amount": amount, "drill": d})
            table_rows.append(
                model.make_row(
                    f"{key}-{corr}",
                    {"label": _account_label(ctx, corr), "amount": amount},
                    level=1,
                    parent=group_id,
                    drill=d,
                )
            )
            total += amount
        total = model.money(total)
        out[key] = {"rows": rows, "total": total}
        totals[key] = total
        table_rows.append(model.make_row(f"t-{key}", {"label": _("Разом"), "amount": total}, kind="subtotal", bold=True))
    title = _("Журнал-ордер і відомість по рахунку {0}").format(ctx.chart.label(account))
    table = make_table("journal_order", title, ctx.lines(), cols, table_rows)
    return result(table, cols, out["credit"]["rows"] + out["debit"]["rows"], totals, **out)


# ---------------------------------------------------------------- general ledger


def general_ledger(ctx):
    flt_ = ctx.flt
    chart = ctx.chart
    leaves = [a for a in (chart.expand(flt_.accounts) if flt_.accounts else chart.all_leaves()) if not chart.get(a).off_balance]
    scope = Scope(flt_, chart, leaves=leaves)
    nets = {a: v[0] for a, v in _net_by_account(aggregate(scope, None, flt_.date_from)).items()}
    order = _order(ctx)

    found = []
    for first, begin, end in months(flt_.date_from, flt_.date_to):
        turn = _net_by_account(aggregate(scope, begin, end))
        for account in set(nets) | set(turn):
            _n, debit, credit = turn.get(account, (0.0, 0.0, 0.0))
            bal = bal_row(nets.get(account, 0.0), debit, credit)
            nets[account] = nets.get(account, 0.0) + debit - credit
            if not is_zero(bal):
                found.append((order.get(account, 1e9), str(first), account, first, bal))
    found.sort(key=lambda x: x[:2])

    cols = bal_cols(_("Рахунок"))
    cols.insert(1, col("month", _("Місяць"), "text"))
    rows, table_rows, tot_dr, tot_cr = [], [], 0.0, 0.0
    for _o, key, account, first, bal in found:
        d = drill(
            "ua-account-card",
            ctx.base_filters(accounts=[account], date_from=key, date_to=str(month_end(first, flt_.date_to))),
        )
        rows.append({"account": account, "month": key, **bal, "drill": d})
        table_rows.append(
            model.make_row(
                f"{account}|{key}",
                {"label": chart.label(account), "month": first.strftime("%m.%Y"), **bal},
                drill=d,
            )
        )
        tot_dr += bal["turnover_dr"]
        tot_cr += bal["turnover_cr"]
    totals = {"turnover_dr": model.money(tot_dr), "turnover_cr": model.money(tot_cr)}
    table_rows.append(total_row(totals))
    table = make_table("general_ledger", _("Головна книга"), ctx.lines(), cols, table_rows)
    return result(table, cols, rows, totals)


# ---------------------------------------------------------------- chess sheet


def chess_sheet(ctx):
    flt_ = ctx.flt
    marks = ", ".join(["%s"] * len(flt_.organizations))
    scope_sql, scope_params = _scope_sql(ctx)
    cells = frappe.db.sql(
        f"""SELECT account_dr, account_cr, SUM(amount) AS amount FROM `{ENTRIES}`
        WHERE organization IN ({marks}) AND posting_date >= %s AND posting_date < %s
        AND account_dr != '' AND account_cr != ''{" AND " + scope_sql if scope_sql else ""}
        GROUP BY account_dr, account_cr""",
        [*flt_.organizations, flt_.date_from, flt_.end, *scope_params],
        as_dict=True,
    )
    order = _order(ctx)
    cells = [c for c in cells if model.money(c.amount)]
    cells.sort(key=lambda c: (order.get(c.account_dr, 1e9), order.get(c.account_cr, 1e9)))
    credit = sorted({c.account_cr for c in cells}, key=lambda a: order.get(a, 1e9))

    rows, totals_dr, totals_cr, by_dr = [], {}, {}, {}
    for c in cells:
        amount = model.money(c.amount)
        d = drill("ua-entries-report", ctx.base_filters(account_dr=c.account_dr, account_cr=c.account_cr))
        rows.append({"account_dr": c.account_dr, "account_cr": c.account_cr, "amount": amount, "drill": d})
        totals_dr[c.account_dr] = model.money(totals_dr.get(c.account_dr, 0) + amount)
        totals_cr[c.account_cr] = model.money(totals_cr.get(c.account_cr, 0) + amount)
        by_dr.setdefault(c.account_dr, {})[c.account_cr] = (amount, d)
    total = model.money(sum(totals_dr.values()))

    cols = [col("label", _("Дебет"), "label")]
    cols += [col(f"cr:{a}", a, "money", group=_("Кредит")) for a in credit]
    cols.append(col("total", _("Усього"), "money"))
    table_rows = []
    for dr in sorted(totals_dr, key=lambda a: order.get(a, 1e9)):
        row_cells = {"label": _account_label(ctx, dr), "total": totals_dr[dr]}
        cell_drill = {}
        for cr, (amount, d) in by_dr[dr].items():
            row_cells[f"cr:{cr}"] = amount
            cell_drill[f"cr:{cr}"] = d
        r = model.make_row(f"d{dr}", row_cells)
        r["cell_drill"] = cell_drill
        table_rows.append(r)
    foot = {"label": _("Усього"), "total": total}
    foot.update({f"cr:{a}": v for a, v in totals_cr.items()})
    table_rows.append(model.make_row("total", foot, kind="total", bold=True))
    table = make_table("chess_sheet", _("Шахова відомість"), ctx.lines(), cols, table_rows)
    return result(table, cols, rows, {"total": total}, totals_dr=totals_dr, totals_cr=totals_cr, total=total)


# ---------------------------------------------------------------- entries report


def entries_report(ctx):
    flt_ = ctx.flt
    where = [f"organization IN ({', '.join(['%s'] * len(flt_.organizations))})", "posting_date >= %s", "posting_date < %s"]
    params = [*flt_.organizations, flt_.date_from, flt_.end]
    for key in ("account_dr", "account_cr"):
        value = ctx.opt(key)
        if value:
            leaves = ctx.chart.expand([ctx.chart.get(value).name])
            where.append(f"{key} IN ({', '.join(['%s'] * len(leaves))})")
            params.extend(leaves)
    if ctx.opt("amount_from") not in ("", None):
        where.append("amount >= %s")
        params.append(flt(ctx.opt("amount_from")))
    if ctx.opt("amount_to") not in ("", None):
        where.append("amount <= %s")
        params.append(flt(ctx.opt("amount_to")))
    side = ctx.opt("scope_side")
    scope_sql, scope_params = _scope_sql(ctx, (side,) if side in ("dr", "cr") else ("dr", "cr"))
    if scope_sql:
        where.append(scope_sql)
        params.extend(scope_params)
    sql_where = " AND ".join(where)

    limit = min(max(flt_.number("limit", ENTRIES_LIMIT), 1), ENTRIES_MAX)
    count, amount = frappe.db.sql(f"SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM `{ENTRIES}` WHERE {sql_where}", params)[0]
    entries = frappe.db.sql(
        f"""SELECT name, posting_date, registrar_type, registrar, account_dr, account_cr, amount, content
        FROM `{ENTRIES}` WHERE {sql_where} ORDER BY posting_date ASC, name ASC LIMIT %s""",
        [*params, limit],
        as_dict=True,
    )
    cols = [
        col("date", _("Дата"), "date"),
        col("doc", _("Документ"), "doc"),
        col("content", _("Операція"), "text"),
        col("account_dr", _("Дебет"), "text", "center"),
        col("account_cr", _("Кредит"), "text", "center"),
        col("amount", _("Сума"), "money"),
    ]
    rows, table_rows = [], []
    for e in entries:
        rows.append(
            {
                "posting_date": str(e.posting_date),
                "registrar_type": e.registrar_type,
                "registrar": e.registrar,
                "account_dr": e.account_dr,
                "account_cr": e.account_cr,
                "amount": model.money(e.amount),
                "content": e.content or "",
            }
        )
        table_rows.append(
            model.make_row(
                f"e{e.name}",
                {
                    "date": model.fmt_date(e.posting_date),
                    "doc": f"{_(e.registrar_type)} {e.registrar}",
                    "content": e.content or "",
                    "account_dr": e.account_dr,
                    "account_cr": e.account_cr,
                    "amount": model.money(e.amount),
                },
                links={"doc": {"doctype": e.registrar_type, "name": e.registrar}},
            )
        )
    totals = {"count": int(count), "amount": model.money(amount)}
    table_rows.append(
        model.make_row(
            "total",
            {"doc": _("Разом проводок: {0}").format(totals["count"]), "amount": totals["amount"]},
            kind="total",
            bold=True,
        )
    )
    truncated = totals["count"] > len(rows)
    message = _("Показано перші {0} проводок. Підсумок враховує всі проводки.").format(limit) if truncated else ""
    lines = ctx.lines()
    if ctx.opt("account_dr"):
        lines.append(_("Дебет: {0}").format(ctx.opt("account_dr")))
    if ctx.opt("account_cr"):
        lines.append(_("Кредит: {0}").format(ctx.opt("account_cr")))
    table = make_table("entries_report", _("Звіт по проводках"), lines, cols, table_rows, message=message, truncated=truncated)
    return result(table, cols, rows, totals)

