"""Rows "opening balance / turnovers / closing balance" for OSV and OSV by account.

Both reports are one builder with different settings:
    OSV            account hierarchy; subconto levels are slot numbers 1..N
    OSV by account one account (and its sub-accounts); levels are subconto types

Balances are net per leaf row: debit side if debit > credit, else credit side.
A group row (and the totals row) is an expanded balance, like 1C: it adds the
debit and the credit balances of the leaf rows below it separately, no netting.
"""

from frappe import _

from ua_accounting.reporting import model
from ua_accounting.reporting.query import Scope, aggregate

# Agg = [open money, open qty, open cur, turn Dr money, turn Cr money,
#        turn Dr qty, turn Cr qty, turn Dr cur, turn Cr cur]
AGG_SIZE = 9
EPS = 0.0005


def balance_columns(first_label, show_qty, show_cur):
    kinds = [("", _("Сума"), "money")]
    if show_qty:
        kinds.append(("_qty", _("Кількість"), "qty"))
    if show_cur:
        kinds.append(("_cur", _("Вал. сума"), "money"))
    k = len(kinds)
    sections = [
        ("open", _("Сальдо на початок періоду")),
        ("turn", _("Обороти за період")),
        ("close", _("Сальдо на кінець періоду")),
    ]
    sides = [("dr", _("Дебет")), ("cr", _("Кредит"))]

    columns = [dict(model.LABEL)]
    for sec, _title in sections:
        for side, _label in sides:
            for suffix, _lbl, kind in kinds:
                columns.append({"key": f"{sec}_{side}{suffix}", "kind": kind, "align": "right"})

    height = 3 if k > 1 else 2
    header = [[model.header_cell(first_label, 1, height)]]
    for _sec, title in sections:
        header[0].append(model.header_cell(title, 2 * k))
    header.append([model.header_cell(label, k) for _s in sections for _k, label in sides])
    if k > 1:
        header.append([model.header_cell(lbl) for _s in sections for _sd in sides for _x, lbl, _k in kinds])
    return header, columns


def _side(m, q, c):
    for v in (m, q, c):
        if v > EPS:
            return "dr"
        if v < -EPS:
            return "cr"
    return "dr"


# Exp = expanded balances: [open dr (m, q, c), open cr, close dr, close cr]
EXP_SIZE = 12


def _leaf_exp(agg):
    """Expanded balances of one leaf (account, subconto values, currency)."""
    o_m, o_q, o_c, tdm, tcm, tdq, tcq, tdc, tcc = agg
    exp = [0.0] * EXP_SIZE
    for n, (m, q, c) in enumerate(
        [(o_m, o_q, o_c), (o_m + tdm - tcm, o_q + tdq - tcq, o_c + tdc - tcc)]
    ):
        sign = 1 if _side(m, q, c) == "dr" else -1
        base = n * 6 + (0 if sign == 1 else 3)
        exp[base] = sign * m
        exp[base + 1] = sign * q
        exp[base + 2] = sign * c
    return exp


def present(agg, exp, show_cur):
    """Cells of one row from its Agg and its expanded balances."""
    _o_m, _o_q, _o_c, tdm, tcm, tdq, tcq, tdc, tcc = agg
    cells = {}

    def balance(sec, n):
        for k, side in enumerate(("dr", "cr")):
            m, q, c = exp[n * 6 + k * 3 : n * 6 + k * 3 + 3]
            cells[f"{sec}_{side}"] = model.money(m)
            cells[f"{sec}_{side}_qty"] = model.qty(q)
            cells[f"{sec}_{side}_cur"] = model.money(c) if show_cur else None

    balance("open", 0)
    cells["turn_dr"] = model.money(tdm)
    cells["turn_cr"] = model.money(tcm)
    cells["turn_dr_qty"] = model.qty(tdq)
    cells["turn_cr_qty"] = model.qty(tcq)
    cells["turn_dr_cur"] = model.money(tdc) if show_cur else None
    cells["turn_cr_cur"] = model.money(tcc) if show_cur else None
    balance("close", 1)
    return cells


def _zero(agg):
    return all(abs(v) < EPS for v in agg)


def _add(target, agg):
    for i in range(len(agg)):
        target[i] += agg[i]


def _add_exp(expanded, node_key, exp):
    _add(expanded.setdefault(node_key, [0.0] * EXP_SIZE), exp)


class Settings:
    """What a balance report needs to know. Plain attributes."""

    def __init__(self, **kw):
        self.title = ""
        self.first_label = _("Рахунок")
        self.levels = []  # [("slot", 1)] or [("type", "Counterparty")]
        self.leaves = None  # accounts to read (None: from the filters)
        self.roots = []  # accounts shown at the top
        self.with_children = False  # open sub-accounts below the roots
        self.by_currency = False  # currency is the last grouping level
        self.show_qty = False
        self.show_cur = False
        self.show_zero = False
        self.account_drill = "osv_account"  # where a click on an account row goes
        self.exclude_off_balance_total = True
        self.__dict__.update(kw)


def build_balance(report, flt_, chart, titles, st):
    scope = Scope(flt_, chart, st.levels, st.by_currency, st.leaves)
    opening = aggregate(scope, None, flt_.date_from)
    turnover = aggregate(scope, flt_.date_from, flt_.end)

    nodes = {}  # (account, path) -> Agg
    expanded = {}  # (account, path) -> Exp
    index = {}  # (account, path) -> set of next path values

    def add_key(key, agg, exp):
        account, values, currency = key
        cls = scope.by_account[account]
        path = [v for v, slot in zip(values, cls.level_slots) if slot is not None]
        if st.by_currency and chart.get(account).currency_accounting:
            path.append(currency)
        for k in range(len(path) + 1):
            node = nodes.setdefault((account, tuple(path[:k])), [0.0] * AGG_SIZE)
            _add(node, agg)
            _add_exp(expanded, (account, tuple(path[:k])), exp)
            if k:
                index.setdefault((account, tuple(path[: k - 1])), set()).add(path[k - 1])
        for anc in chart.ancestors(account):
            _add(nodes.setdefault((anc, ()), [0.0] * AGG_SIZE), agg)
            _add_exp(expanded, (anc, ()), exp)

    leaves = {}  # key -> Agg of the leaf (opening and turnover together)
    for key, v in opening.items():
        _add(leaves.setdefault(key, [0.0] * AGG_SIZE), [v[0] - v[1], v[2] - v[3], v[4] - v[5], 0, 0, 0, 0, 0, 0])
    for key, v in turnover.items():
        _add(leaves.setdefault(key, [0.0] * AGG_SIZE), [0, 0, 0, v[0], v[1], v[2], v[3], v[4], v[5]])
    for key, agg in leaves.items():
        add_key(key, agg, _leaf_exp(agg))

    def element(account, k):
        """What the k-th path element of the account is: ("sub", sub row) or ("cur", None)."""
        cls = scope.by_account[account]
        slots = [s for s in cls.level_slots if s is not None]
        if k < len(slots):
            return "sub", chart.get(account).subs[slots[k]]
        return "cur", None

    # one query per DocType for the titles of all subconto values
    pairs = []
    for (account, path), values in index.items():
        kind, sub = element(account, len(path))
        if kind == "sub":
            t = chart.types.get(sub.subconto_type)
            if t and t.reference_doctype and not t.is_dynamic:
                pairs.extend((t.reference_doctype, v) for v in values)
    titles.preload(pairs)

    def value_label(account, k, value):
        kind, sub = element(account, k)
        if kind == "cur":
            return value or _("<без валюти>")
        t = chart.types.get(sub.subconto_type)
        if not value:
            return _("<не задано>")
        if t and t.reference_doctype and not t.is_dynamic:
            return titles.get(t.reference_doctype, value)
        return value

    def path_filters(account, path):
        """Subconto filters (and currency) that select the rows of a path."""
        subconto, currency = [], ""
        for k, value in enumerate(path):
            kind, sub = element(account, k)
            if kind == "cur":
                currency = value
            else:
                subconto.append({"type": sub.subconto_type, "values": [value]})
        return subconto, currency

    rows = []
    root_cells = []
    cur_always = bool(flt_.currency)

    def emit(account, path, parent, level, is_root=False):
        agg = nodes.get((account, path))
        exp = expanded.get((account, path))
        if agg is None or (_zero(agg) and _zero(exp) and not st.show_zero):
            return None
        acc = chart.get(account)
        row_id = f"{account}|{'|'.join(path)}"
        cur_valid = st.show_cur and (cur_always or (path and element(account, len(path) - 1)[0] == "cur"))
        cells = present(agg, exp, cur_valid)

        if not path:
            cells["label"] = chart.label(account)
            drill = {"to": st.account_drill, "account": account}
        else:
            cells["label"] = value_label(account, len(path) - 1, path[-1])
            subconto, currency = path_filters(account, path)
            drill = {"to": "account_card", "account": account, "subconto": subconto, "currency": currency}
        row = model.make_row(row_id, cells, level=level, kind="item", parent=parent, drill=drill)
        rows.append(row)

        children = 0
        if not path and acc.is_group:
            if st.with_children:
                for child in chart.children.get(account, []):
                    if emit(child, (), row_id, level + 1):
                        children += 1
        else:
            values = index.get((account, path), ())
            ordered = sorted(values, key=lambda v: value_label(account, len(path), v).lower())
            for value in ordered:
                if emit(account, path + (value,), row_id, level + 1):
                    children += 1
        if children:
            row["kind"] = "group"
            row["bold"] = True
        if is_root:
            root_cells.append((acc, agg, cells))
        return row

    for root in st.roots:
        # a class (level 0) is not shown: its accounts are the top rows
        if chart.depth(root) == 0 and chart.get(root).is_group:
            for child in chart.children.get(root, []):
                emit(child, (), None, 0, is_root=True)
        else:
            emit(root, (), None, 0, is_root=True)

    header, columns = balance_columns(st.first_label, st.show_qty, st.show_cur)
    if rows:
        rows.append(_total_row(root_cells, st))

    return {
        "report": report,
        "title": st.title,
        "lines": model.header_lines(flt_, chart, titles),
        "header": header,
        "columns": columns,
        "rows": rows,
        "truncated": False,
        "message": "" if rows else _("Немає даних за вибраними умовами"),
    }


def _total_row(root_cells, st):
    chosen = [c for acc, _agg, c in root_cells if not acc.off_balance]
    if not chosen or not st.exclude_off_balance_total:
        chosen = [c for _acc, _agg, c in root_cells]
    cells = {"label": _("Усього")}
    for key in chosen[0]:
        if key == "label" or key.endswith("_qty") or key.endswith("_cur"):
            continue
        cells[key] = model.money(sum(c.get(key) or 0 for c in chosen))
    return model.make_row("total", cells, kind="total", bold=True)
