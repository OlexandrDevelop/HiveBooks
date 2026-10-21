"""ОСВ по рахунку: one account, rows by the subconto the user picks.

Options (besides the common filters):
    account          the account (a group opens its sub-accounts)
    levels           up to 3 subconto type names, in the order of the rows
    by_subaccounts   1 (default) = rows of sub-accounts when the account is a group
    show_quantity, show_currency   used only when the account has those flags
"""

import frappe
from frappe import _

from ua_accounting.reporting.balance import Settings, build_balance
from ua_accounting.reporting.chart import Chart
from ua_accounting.reporting.filters import as_list, parse_filters
from ua_accounting.reporting.titles import Titles


def build(raw):
    flt_ = parse_filters(raw)
    if len(flt_.accounts) != 1:
        frappe.throw(_("Вкажіть один рахунок"))
    chart = Chart()
    titles = Titles()
    account = chart.get(flt_.accounts[0]).name
    leaves = chart.expand([account])

    level_types = as_list(flt_.opts.get("levels"))[:3]
    if not level_types and len(leaves) == 1:
        first = chart.get(leaves[0]).subs
        level_types = [first[0].subconto_type] if first else []
    # one type only once
    level_types = list(dict.fromkeys(level_types))

    has_qty = any(chart.get(a).quantity_accounting for a in leaves)
    has_cur = any(chart.get(a).currency_accounting for a in leaves)
    show_qty = has_qty and (flt_.flag("show_quantity", 1))
    show_cur = has_cur and (flt_.flag("show_currency", 1))

    st = Settings(
        title=_("Оборотно-сальдова відомість по рахунку {0}").format(chart.label(account)),
        first_label=_("Рахунок, субконто") if chart.get(account).is_group else _("Субконто"),
        levels=[("type", t) for t in level_types],
        leaves=leaves,
        roots=[account],
        with_children=flt_.flag("by_subaccounts", 1),
        by_currency=show_cur,
        show_qty=show_qty,
        show_cur=show_cur,
        show_zero=flt_.flag("show_zero"),
        account_drill="account_card",
        exclude_off_balance_total=False,
    )
    return build_balance("osv_account", flt_, chart, titles, st)
