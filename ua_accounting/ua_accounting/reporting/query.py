"""The shared query layer of the reports.

All reports read the ledger only through this module.

Speed rule: a period is cut into whole months and edge days.
    whole months  -> UA Account Turnover (monthly totals)
    edge days     -> UA Accounting Entry (only the partial months)
So a year report reads at most 12 totals rows per key plus two partial months.

Scope = the filters resolved against the chart of accounts:
    - the leaf accounts to read,
    - for each account the subconto slot of every filter and of every grouping level.
Accounts with the same layout are read together ("classes"), so the SQL stays short.

A new filter: add it to filters.py, then to Scope (resolve) and `_common_where`
(SQL for both tables). All reports get it.
"""

import frappe
from frappe.utils import flt, get_first_day

TOTALS = "tabUA Account Turnover"
ENTRIES = "tabUA Accounting Entry"
SIDES = ("dr", "cr")
# order of the numbers in a result vector
SUMS = ("debit", "credit", "qty_dr", "qty_cr", "cur_dr", "cur_cr")

ENTRY_FIELDS = [
    "name",
    "posting_date",
    "registrar_type",
    "registrar",
    "line_no",
    "organization",
    "account_dr",
    "account_cr",
    *[f"subconto_{s}{i}_type" for s in SIDES for i in (1, 2, 3)],
    *[f"subconto_{s}{i}" for s in SIDES for i in (1, 2, 3)],
    "amount",
    "quantity_dr",
    "quantity_cr",
    "currency_dr",
    "currency_cr",
    "currency_amount_dr",
    "currency_amount_cr",
    "content",
]


# ---------------------------------------------------------------- periods


def split_range(begin, end):
    """Cut the days [begin, end) into whole months and edge days.

    begin=None means "from the start of the books".
    Returns (months, edges):
        months  (first_period, last_period_exclusive) read from totals, or None
        edges   list of (from_day, to_day_exclusive) read from entries
    """
    if begin is not None and end <= begin:
        return None, []
    edges = []
    m_from = begin
    if begin is not None and begin.day != 1:
        m_from = get_first_day(begin, 0, 1)
        if end <= m_from:
            return None, [(begin, end)]
        edges.append((begin, m_from))
    m_to = end
    if end.day != 1:
        m_to = get_first_day(end)
        edges.append((m_to, end))
    if m_from is not None and m_to <= m_from:
        return None, edges
    return (m_from, m_to), edges


# ---------------------------------------------------------------- scope


class _Class:
    """Accounts that share one layout, so one SQL statement reads them all."""

    def __init__(self, level_slots, filter_slots, slow):
        self.level_slots = level_slots  # slot (0-based) or None per grouping level
        self.filter_slots = filter_slots  # slot (0-based) per subconto filter
        self.slow = slow
        self.accounts = []


class Scope:
    """Filters resolved against the chart.

    levels: grouping levels, each ("slot", n) with n 1-based, or ("type", name).
    by_currency: group by the currency of the totals key too.
    leaves: accounts to read; default is the accounts of the filter (or all).
    """

    def __init__(self, flt_, chart, levels=(), by_currency=False, leaves=None):
        self.flt = flt_
        self.chart = chart
        self.levels = list(levels)
        self.by_currency = by_currency
        if leaves is None:
            leaves = chart.expand(flt_.accounts) if flt_.accounts else chart.all_leaves()
        classes = {}
        self.by_account = {}
        for name in leaves:
            fslots = []
            for f in flt_.subconto:
                idx = chart.type_index(name, f["type"])
                if idx is None:
                    break
                fslots.append(idx)
            else:
                lslots = tuple(self._level_slot(name, lv) for lv in self.levels)
                # Turnover-only subconto is not stored in the totals (1C rule), so
                # an account that is grouped or filtered by it is read from entries.
                subs = chart.get(name).subs
                used = [s for s in (*fslots, *lslots) if s is not None]
                slow = any(subs[s].turnover_only for s in used)
                key = (lslots, tuple(fslots), slow)
                cls = classes.get(key)
                if cls is None:
                    cls = classes[key] = _Class(lslots, tuple(fslots), slow)
                cls.accounts.append(name)
                self.by_account[name] = cls
        self.classes = list(classes.values())

    def _level_slot(self, account, level):
        kind, value = level
        if kind == "slot":
            return value - 1 if value <= len(self.chart.get(account).subs) else None
        return self.chart.type_index(account, value)

    def side_matches(self, row, side):
        """Does one side of an entry row belong to the scope (accounts + filters)?"""
        cls = self.by_account.get(row.get(f"account_{side}"))
        if cls is None:
            return False
        for f, slot in zip(self.flt.subconto, cls.filter_slots):
            if (row.get(f"subconto_{side}{slot + 1}") or "") not in f["values"]:
                return False
        if self.flt.currency and (row.get(f"currency_{side}") or "") != self.flt.currency:
            return False
        return True


# ---------------------------------------------------------------- SQL helpers


class _Where:
    def __init__(self):
        self.parts = []
        self.params = []

    def add(self, sql, *params):
        self.parts.append(sql)
        self.params.extend(params)

    def in_(self, column, values):
        values = list(values)
        if not values:
            self.parts.append("1 = 0")
            return
        self.parts.append(f"{column} IN ({', '.join(['%s'] * len(values))})")
        self.params.extend(values)

    def sql(self):
        return " AND ".join(self.parts) if self.parts else "1 = 1"


def _common_where(scope, cls, w, cols, with_org=True):
    """Conditions that are the same for the totals table and one side of the entries.

    cols: column names {"account", "org", "currency", "slot": fn(n) -> column}
    """
    flt_ = scope.flt
    if with_org and flt_.organizations:
        w.in_(cols["org"], flt_.organizations)
    w.in_(cols["account"], cls.accounts)
    if flt_.currency:
        w.add(f"{cols['currency']} = %s", flt_.currency)
    for f, slot in zip(flt_.subconto, cls.filter_slots):
        w.in_(cols["slot"](slot + 1), f["values"])


def _select_dims(scope, cls, cols):
    """SELECT list and GROUP BY list for account, grouping levels and currency."""
    select = [f"{cols['account']} AS account"]
    group = [cols["account"]]
    for i, slot in enumerate(cls.level_slots):
        if slot is None:
            select.append(f"'' AS l{i}")
        else:
            select.append(f"{cols['slot'](slot + 1)} AS l{i}")
            group.append(f"l{i}")
    if scope.by_currency:
        select.append(f"{cols['currency']} AS currency")
        group.append("currency")
    else:
        select.append("'' AS currency")
    return select, group


def _merge(out, rows, n_levels):
    for r in rows:
        key = (r["account"], tuple(r[f"l{i}"] or "" for i in range(n_levels)), r["currency"] or "")
        vec = out.get(key)
        if vec is None:
            vec = out[key] = [0.0] * len(SUMS)
        for i, name in enumerate(SUMS):
            vec[i] += flt(r[name])


# ---------------------------------------------------------------- aggregation


def _read_totals(scope, cls, months, out):
    m_from, m_to = months
    w = _Where()
    if m_from is not None:
        w.add("period >= %s", m_from)
    w.add("period < %s", m_to)
    cols = {
        "account": "account",
        "org": "organization",
        "currency": "currency",
        "slot": lambda n: f"subconto{n}",
    }
    _common_where(scope, cls, w, cols)
    select, group = _select_dims(scope, cls, cols)
    sql = (
        f"SELECT {', '.join(select)}, SUM(debit) AS debit, SUM(credit) AS credit, "
        "SUM(quantity_dr) AS qty_dr, SUM(quantity_cr) AS qty_cr, "
        "SUM(currency_dr) AS cur_dr, SUM(currency_cr) AS cur_cr "
        f"FROM `{TOTALS}` WHERE {w.sql()} GROUP BY {', '.join(group)}"
    )
    _merge(out, frappe.db.sql(sql, w.params, as_dict=True), len(scope.levels))


def _read_entries(scope, cls, edges, out):
    for begin, end in edges:
        for side in SIDES:
            w = _Where()
            if begin is not None:
                w.add("posting_date >= %s", begin)
            w.add("posting_date < %s", end)
            cols = {
                "account": f"account_{side}",
                "org": "organization",
                "currency": f"currency_{side}",
                "slot": lambda n, side=side: f"subconto_{side}{n}",
            }
            _common_where(scope, cls, w, cols)
            select, group = _select_dims(scope, cls, cols)
            if side == "dr":
                sums = (
                    "SUM(amount) AS debit, 0 AS credit, SUM(quantity_dr) AS qty_dr, 0 AS qty_cr, "
                    "SUM(currency_amount_dr) AS cur_dr, 0 AS cur_cr"
                )
            else:
                sums = (
                    "0 AS debit, SUM(amount) AS credit, 0 AS qty_dr, SUM(quantity_cr) AS qty_cr, "
                    "0 AS cur_dr, SUM(currency_amount_cr) AS cur_cr"
                )
            sql = (
                f"SELECT {', '.join(select)}, {sums} FROM `{ENTRIES}` "
                f"WHERE {w.sql()} GROUP BY {', '.join(group)}"
            )
            _merge(out, frappe.db.sql(sql, w.params, as_dict=True), len(scope.levels))


def aggregate(scope, begin, end):
    """Turnovers of the days [begin, end). begin=None: from the start.

    Returns {(account, (level values...), currency): [debit, credit, qty_dr, qty_cr,
    cur_dr, cur_cr]}. Grouping levels without a subconto for the account give "".
    """
    out = {}
    months, edges = split_range(begin, end)
    for cls in scope.classes:
        if cls.slow:
            _read_entries(scope, cls, [(begin, end)], out)
            continue
        if months:
            _read_totals(scope, cls, months, out)
        _read_entries(scope, cls, edges, out)
    return out


def sum_vectors(result):
    """One vector with the sum of all rows of an aggregate() result."""
    total = [0.0] * len(SUMS)
    for vec in result.values():
        for i, v in enumerate(vec):
            total[i] += v
    return total


# ---------------------------------------------------------------- entry rows


def list_entries(scope, begin, end, limit):
    """Entries of the days [begin, end) that touch the scope on at least one side.

    Ordered by date and order of posting. Returns (rows, truncated).
    """
    flt_ = scope.flt
    w = _Where()
    w.add("posting_date >= %s", begin)
    w.add("posting_date < %s", end)
    if flt_.organizations:
        w.in_("organization", flt_.organizations)

    sides = []
    side_params = []
    for cls in scope.classes:
        for side in SIDES:
            sw = _Where()
            cols = {
                "account": f"account_{side}",
                "org": "organization",
                "currency": f"currency_{side}",
                "slot": lambda n, side=side: f"subconto_{side}{n}",
            }
            # the organization is already in the outer condition
            _common_where(scope, cls, sw, cols, with_org=False)
            sides.append(f"({sw.sql()})")
            side_params.extend(sw.params)
    if not sides:
        return [], False
    w.add(f"({' OR '.join(sides)})")
    w.params.extend(side_params)

    fields = ", ".join(f"`{f}`" for f in ENTRY_FIELDS)
    rows = frappe.db.sql(
        f"SELECT {fields} FROM `{ENTRIES}` WHERE {w.sql()} "
        "ORDER BY posting_date ASC, name ASC LIMIT %s",
        [*w.params, limit + 1],
        as_dict=True,
    )
    truncated = len(rows) > limit
    return rows[:limit], truncated
