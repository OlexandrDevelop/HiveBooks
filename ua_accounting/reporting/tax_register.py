"""Реєстр податкових накладних: issued and received ПН and РК with the ЄРПН status.

Options (besides the common filters): direction, erpn_status, counterparty, group_by.
group_by is empty (a flat list), counterparty, erpn_status or month: the rows are grouped by the core
report composition engine, every group has a subtotal and a drill into its documents. The totals row
is made by the engine in every mode.
"""

from frappe import _
from frappe.beeone.report_engine import compose, drill_rows

from ua_accounting.accounting import tax
from ua_accounting.reporting import model
from ua_accounting.reporting.filters import parse_filters
from ua_accounting.reporting.titles import Titles


def build(raw):
    flt_ = parse_filters(raw)
    titles = Titles()
    opts = flt_.opts
    orgs = flt_.organizations or [None]
    rows = []
    for org in orgs:
        data = tax.register_data(
            org,
            flt_.date_from,
            flt_.date_to,
            opts.get("direction") or None,
            opts.get("erpn_status") or None,
            opts.get("counterparty") or None,
        )
        rows.extend(data["rows"])
    rows.sort(key=lambda r: (r["date"], r["name"]))
    group_by = opts.get("group_by") or ""
    if group_by not in GROUPINGS:
        group_by = ""
    for r in rows:
        r["month"] = _to_date(r["date"]).strftime("%Y-%m")
    composed = compose(
        rows,
        [{"field": group_by, "label": lambda v: v or _("<не задано>")}] if group_by else [],
        [{"field": k, "precision": 2} for k in ("base", "vat", "total")],
        detail=False,
        label_field="name",
        total_label=_("Разом"),
    )
    totals = composed[-1]["values"]
    titles.preload(("UA Counterparty", r["counterparty"]) for r in rows)

    columns = [
        {"key": "number", "kind": "doc", "align": "left"},
        {"key": "date", "kind": "date", "align": "left"},
        {"key": "counterparty", "kind": "text", "align": "left"},
        {"key": "base", "kind": "money", "align": "right"},
        {"key": "vat", "kind": "money", "align": "right"},
        {"key": "total", "kind": "money", "align": "right"},
        {"key": "erpn_status", "kind": "text", "align": "left"},
        {"key": "erpn_reg_number", "kind": "text", "align": "left"},
    ]
    header = [
        [
            model.header_cell(_("Номер")),
            model.header_cell(_("Дата")),
            model.header_cell(_("Контрагент")),
            model.header_cell(_("База")),
            model.header_cell(_("ПДВ")),
            model.header_cell(_("Сума")),
            model.header_cell(_("Статус ЄРПН")),
            model.header_cell(_("Номер реєстрації")),
        ]
    ]
    def item_row(r, parent=None):
        label = r["number"] or r["name"]
        if r["doctype"] == tax.RK:
            label = f"{_('РК')} {label}"
        return model.make_row(
            r["name"],
            {
                "number": label,
                "date": model.fmt_date(_to_date(r["date"])),
                "counterparty": titles.get("UA Counterparty", r["counterparty"]),
                "base": r["base"],
                "vat": r["vat"],
                "total": r["total"],
                "erpn_status": r["erpn_status"],
                "erpn_reg_number": r["erpn_reg_number"] or "",
            },
            level=1 if parent else 0,
            parent=parent,
            links={"number": {"doctype": r["doctype"], "name": r["name"]}},
        )

    out = []
    if group_by:
        for node in composed[:-1]:
            out.append(
                model.make_row(
                    node["id"],
                    {"number": node["label"], **{k: model.money(v) for k, v in node["values"].items()}},
                    kind="group",
                    bold=True,
                    drill={"group_by": group_by, "filters": node["drill"]["filters"]},
                )
            )
            out.extend(item_row(r, node["id"]) for r in drill_rows(rows, node["drill"]["filters"]))
    else:
        out.extend(item_row(r) for r in rows)
    if out:
        out.append(
            model.make_row(
                "total",
                {"number": composed[-1]["label"], **{k: model.money(v) for k, v in totals.items()}},
                kind="total",
                bold=True,
            )
        )
    lines = [
        _("Період: з {0} по {1}").format(model.fmt_date(flt_.date_from), model.fmt_date(flt_.date_to)),
    ]
    if opts.get("direction"):
        lines.append(_("Напрям: {0}").format(opts["direction"]))
    return {
        "report": "tax_invoice_register",
        "title": _("Реєстр податкових накладних"),
        "lines": lines,
        "header": header,
        "columns": columns,
        "rows": out,
        "truncated": False,
        "message": "" if out else _("За вибраними умовами податкових накладних немає"),
    }


GROUPINGS = ("counterparty", "erpn_status", "month")


def _to_date(value):
    from frappe.utils import getdate

    return getdate(value)
