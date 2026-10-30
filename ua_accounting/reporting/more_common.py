"""Shared parts of the extra accounting reports (subconto, ledger, chess sheet, check).

A builder gets the request data and returns the result of the contract:
    {columns, rows, totals, ...extra, table}
`table` is the display model (see model.py) used by the pages, the print and the Excel export.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_first_day, get_last_day, getdate

from ua_accounting.accounting.utils import org_info, uk_money
from ua_accounting.administration import _scope
from ua_accounting.reporting import model
from ua_accounting.reporting.chart import Chart
from ua_accounting.reporting.filters import as_list, parse_filters
from ua_accounting.reporting.titles import Titles

NO_ORG = "—"  # a name no organization has: "nothing is permitted"
BAL_KEYS = ("opening_dr", "opening_cr", "turnover_dr", "turnover_cr", "closing_dr", "closing_cr")


class Ctx:
    """Parsed request: filters, chart, titles and the organizations the user may read."""

    def __init__(self, raw, single_org=False):
        data = frappe.parse_json(raw) if isinstance(raw, str) else dict(raw or {})
        asked = as_list(data.get("organizations")) or as_list(data.get("organization"))
        if not asked:
            frappe.throw(_("Вкажіть організацію"))
        permitted = _scope(frappe.session.user)["organizations"]
        orgs = [o for o in asked if not permitted or o in permitted]
        self.asked = asked
        data["organizations"] = orgs or [NO_ORG]
        data.pop("organization", None)
        sub = data.get("subconto")
        if isinstance(sub, str) and sub.strip().startswith("{"):
            sub = frappe.parse_json(sub)
        if isinstance(sub, dict):
            data["subconto"] = [sub]
        elif isinstance(sub, str) and sub.strip() and not sub.strip().startswith("["):
            # card: the value of the subconto type given in `subconto_type`
            if not data.get("subconto_type"):
                frappe.throw(_("Вкажіть вид субконто"))
            data["subconto"] = [{"type": data["subconto_type"], "value": sub.strip()}]
        self.chart = Chart()
        self.titles = Titles()
        if isinstance(data.get("subconto"), list):
            data["subconto"] = [dict(x, type=self.type_code(x.get("type"))) for x in data["subconto"] if x.get("type")]
        self.data = data
        self.flt = parse_filters(data)

    def type_code(self, value):
        """Subconto type by its code («Item») or by the DocType it refers to («UA Item»)."""
        if value in self.chart.types:
            return value
        for t in self.chart.types.values():
            if t.reference_doctype and t.reference_doctype == value:
                return t.name
        frappe.throw(_("Вид субконто {0} не знайдено").format(value))

    def type_doctype(self, code):
        """DocType stored in the entries for a type (the type itself when it is dynamic)."""
        t = self.chart.types.get(code)
        return (t.reference_doctype if t and t.reference_doctype and not t.is_dynamic else None) or code

    def opt(self, key, default=""):
        value = self.flt.opts.get(key, default)
        return default if value is None else value

    def need(self, key, message):
        value = self.opt(key)
        if not value:
            frappe.throw(message)
        return value

    def account(self):
        """The one account of the filter (required)."""
        if not self.flt.accounts:
            frappe.throw(_("Вкажіть рахунок"))
        return self.chart.get(self.flt.accounts[0]).name

    def lines(self):
        orgs = []
        for o in self.asked:
            orgs.append(org_info(o).title if frappe.db.exists("UA Organization", o) else o)
        return [
            _("Організація: {0}").format(", ".join(orgs)),
            _("Період: з {0} по {1}").format(model.fmt_date(self.flt.date_from), model.fmt_date(self.flt.date_to)),
        ]

    def base_filters(self, **extra):
        """Filters of a drill-down target: organization and period of this report."""
        out = {
            "organizations": list(self.asked),
            "date_from": str(self.flt.date_from),
            "date_to": str(self.flt.date_to),
        }
        out.update(extra)
        return out


# ---------------------------------------------------------------- balances


def split(net):
    """Signed balance (debit - credit) -> (debit, credit), never negative."""
    net = flt(net, 2)
    return (net, 0.0) if net > 0 else (0.0, -net)


def bal_row(opening_net, debit, credit):
    """The six numbers of an OSV row from the opening balance and the turnovers."""
    closing = opening_net + debit - credit
    o_dr, o_cr = split(opening_net)
    c_dr, c_cr = split(closing)
    return dict(
        zip(
            BAL_KEYS,
            (o_dr, o_cr, model.money(debit), model.money(credit), c_dr, c_cr),
            strict=True,
        )
    )


def add_bal(total, row):
    for k in BAL_KEYS:
        total[k] = model.money(total.get(k, 0) + row[k])


def is_zero(row):
    return all(abs(row[k]) < 0.005 for k in BAL_KEYS)


def months(date_from, date_to):
    """[(first day of the month, from_day, to_day_exclusive)] of the period, edges are cut."""
    out = []
    first = get_first_day(date_from)
    end = add_days(date_to, 1)
    while first < end:
        nxt = add_months(first, 1)
        out.append((first, max(first, date_from), min(nxt, end)))
        first = nxt
    return out


MONTHS = (
    "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
)  # fmt: skip


def month_label(first):
    return f"{MONTHS[first.month - 1]} {first.year}"


def month_end(first, date_to):
    return min(get_last_day(first), getdate(date_to))


# ---------------------------------------------------------------- table model


def col(key, label, kind="text", align=None, group=None):
    if align is None:
        align = "right" if kind in ("money", "qty") else "left"
    return {"key": key, "label": label, "kind": kind, "align": align, "group": group}


def bal_cols(first_label="Субконто", first_key="label"):
    cols = [col(first_key, first_label, "label")]
    for group, base in (("Сальдо на початок", "opening"), ("Обороти за період", "turnover"), ("Сальдо на кінець", "closing")):
        cols.append(col(f"{base}_dr", _("Дебет"), "money", group=_(group)))
        cols.append(col(f"{base}_cr", _("Кредит"), "money", group=_(group)))
    return cols


def make_header(cols):
    """One or two head rows; grouped columns share a cell of the first row."""
    if not any(c["group"] for c in cols):
        return [[model.header_cell(c["label"]) for c in cols]]
    first, second = [], []
    i = 0
    while i < len(cols):
        c = cols[i]
        if not c["group"]:
            first.append(model.header_cell(c["label"], 1, 2))
            i += 1
            continue
        n = 1
        while i + n < len(cols) and cols[i + n]["group"] == c["group"]:
            n += 1
        first.append(model.header_cell(c["group"], n))
        second.extend(model.header_cell(x["label"]) for x in cols[i : i + n])
        i += n
    return [first, second]


def make_table(report, title, lines, cols, rows, message="", truncated=False):
    return {
        "report": report,
        "title": title,
        "lines": lines,
        "header": make_header(cols),
        "columns": [{"key": c["key"], "kind": c["kind"], "align": c["align"]} for c in cols],
        "rows": rows,
        "truncated": truncated,
        "message": message,
    }


def flat_columns(cols):
    return [
        {"fieldname": c["key"], "label": f"{c['group']} {c['label']}" if c["group"] else c["label"]}
        for c in cols
    ]


def drill(report, filters):
    return {"report": report, "filters": filters}


def total_row(cells, label=None):
    cells = dict(cells)
    cells.setdefault("label", label or _("Разом"))
    return model.make_row("total", cells, kind="total", bold=True)


# ---------------------------------------------------------------- print


def table_html(table):
    from frappe.utils import escape_html

    head = "".join(
        "<tr>"
        + "".join(
            f'<th colspan="{c.get("colspan", 1)}" rowspan="{c.get("rowspan", 1)}">{escape_html(c["label"])}</th>' for c in r
        )
        + "</tr>"
        for r in table["header"]
    )
    body = []
    for row in table["rows"]:
        tds = []
        for c in table["columns"]:
            v = row["cells"].get(c["key"])
            if c["kind"] == "money":
                text = uk_money(v) if v not in (None, "") and abs(v) > 0.0000001 else ""
            elif c["kind"] == "qty":
                text = f"{flt(v):,.3f}".replace(",", " ").replace(".", ",") if v else ""
            elif isinstance(v, (list, tuple)):
                text = "<br>".join(escape_html(str(x)) for x in v)
                tds.append(f'<td class="ua-a-{c["align"]}">{text}</td>')
                continue
            else:
                text = "" if v is None else str(v)
            tds.append(f'<td class="ua-a-{c["align"]}">{escape_html(text)}</td>')
        body.append(f'<tr class="ua-row-{row["kind"]}{" ua-bold" if row.get("bold") else ""}">{"".join(tds)}</tr>')
    return f'<table class="ua-rpt"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


PRINT_CSS = """
body { font-family: Arial, sans-serif; font-size: 11px; margin: 12mm; }
h1 { font-size: 16px; margin: 0 0 6px; }
.ua-lines div { margin: 1px 0; }
table.ua-rpt { border-collapse: collapse; width: 100%; margin-top: 10px; }
.ua-rpt th, .ua-rpt td { border: 1px solid #777; padding: 2px 5px; vertical-align: top; }
.ua-rpt th { background: #e8e8e8; text-align: center; }
.ua-a-right { text-align: right; white-space: nowrap; }
.ua-a-center { text-align: center; }
.ua-bold td { font-weight: bold; }
.ua-row-total td, .ua-row-open td, .ua-row-close td { background: #f3f3f3; }
@page { size: A4 landscape; margin: 10mm; }
"""


def print_html(table):
    from frappe.utils import escape_html

    lines = "".join(f"<div>{escape_html(x)}</div>" for x in table["lines"])
    return (
        f'<html><head><meta charset="utf-8"><title>{escape_html(table["title"])}</title><style>{PRINT_CSS}</style></head>'
        f'<body><h1>{escape_html(table["title"])}</h1><div class="ua-lines">{lines}</div>{table_html(table)}</body></html>'
    )


def result(table, cols, rows, totals, **extra):
    out = {"columns": flat_columns(cols), "rows": rows, "totals": totals, "table": table}
    out.update(extra)
    return out

