"""The shared query layer of the reports.

All reports read the ledger only through this module. The SQL itself lives in the core
(frappe.beeone.accounting_query: acc_turnover, acc_entries, acc_corr_turnover); this module
resolves the filters against the Ukrainian chart of accounts and gives the core its groups.

Speed rule (done by the core): a period is cut into whole months and edge days.
    whole months  -> UA Account Turnover (monthly totals)
    edge days     -> UA Accounting Entry (only the partial months)
So a year report reads at most 12 totals rows per key plus two partial months.

Scope = the filters resolved against the chart of accounts:
    - the leaf accounts to read,
    - for each account the subconto slot of every filter and of every grouping level.
Accounts with the same layout are read together ("classes"), so the SQL stays short.

A new filter: add it to filters.py, then to Scope (resolve). All reports get it.
"""

from frappe.beeone import accounting_query as core

REGISTER = "UA Accounting Entry"
ENTRIES = "tabUA Accounting Entry"
SIDES = ("dr", "cr")
LONG = {"dr": "debit", "cr": "credit"}
# order of the numbers in a result vector
SUMS = core.SUMS

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

split_range = core.split_range
sum_vectors = core.sum_vectors


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


# ---------------------------------------------------------------- core readers


def _groups(scope):
    return [
        core.Group(cls.accounts, cls.level_slots, zip(cls.filter_slots, (f["values"] for f in scope.flt.subconto)), cls.slow)
        for cls in scope.classes
    ]


def _org(scope):
    return scope.flt.organizations


def aggregate(scope, begin, end):
    """Turnovers of the days [begin, end). begin=None: from the start.

    Returns {(account, (level values...), currency): [debit, credit, qty_dr, qty_cr,
    cur_dr, cur_cr]}. Grouping levels without a subconto for the account give "".
    """
    return core.acc_turnover(
        REGISTER,
        begin,
        end,
        _groups(scope),
        _org(scope),
        scope.flt.currency,
        scope.by_currency,
        len(scope.levels),
    )


def side_condition(scope, sides=SIDES):
    """SQL (sql, params) for entries that touch the scope on at least one of `sides`.

    Accounts, currency and subconto filters of the scope apply to the same side of the entry.
    The organization is not included. None when no account of the scope can match.
    """
    return core.acc_side_condition(REGISTER, _groups(scope), [LONG[s] for s in sides], scope.flt.currency)


def list_entries(scope, begin, end, limit):
    """Entries of the days [begin, end) that touch the scope on at least one side.

    Ordered by date and order of posting. Returns (rows, truncated).
    """
    return core.acc_entries(
        REGISTER, begin, end, _groups(scope), ENTRY_FIELDS, limit, _org(scope), scope.flt.currency
    )


def corr_turnover(scope, begin, end):
    """Turnover of the scope accounts split by the corresponding account.

    Returns {(account, corr_account): [debit, credit]}. Read from entries (the totals
    table has no corresponding account). begin=None: from the start.
    """
    return core.acc_corr_turnover(REGISTER, begin, end, _groups(scope), _org(scope), scope.flt.currency)
