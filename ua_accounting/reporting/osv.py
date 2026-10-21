"""Оборотно-сальдова відомість.

Options (besides the common filters):
    by_subaccounts   1 = show sub-accounts below the synthetic accounts
    subconto_levels  0..3 = open leaf accounts by their first N subconto
    show_quantity, show_currency, show_zero
"""

from frappe import _

from ua_accounting.reporting.balance import Settings, build_balance
from ua_accounting.reporting.chart import Chart
from ua_accounting.reporting.filters import parse_filters
from ua_accounting.reporting.titles import Titles


def build(raw):
    flt_ = parse_filters(raw)
    chart = Chart()
    titles = Titles()
    levels = max(0, min(flt_.number("subconto_levels"), 3))

    if flt_.accounts:
        roots = chart.top_level([chart.get(a).name for a in flt_.accounts])
    else:
        roots = chart.children.get("", [])

    st = Settings(
        title=_("Оборотно-сальдова відомість"),
        first_label=_("Рахунок"),
        levels=[("slot", i) for i in range(1, levels + 1)],
        roots=roots,
        with_children=flt_.flag("by_subaccounts"),
        show_qty=flt_.flag("show_quantity"),
        show_cur=flt_.flag("show_currency"),
        show_zero=flt_.flag("show_zero"),
        account_drill="osv_account",
    )
    return build_balance("osv", flt_, chart, titles, st)
