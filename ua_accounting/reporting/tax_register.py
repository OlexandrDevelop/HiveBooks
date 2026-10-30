"""Реєстр податкових накладних: issued and received ПН and РК with the ЄРПН status.

Options (besides the common filters): direction, erpn_status, counterparty.
"""

from frappe import _

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
    totals = {"base": 0.0, "vat": 0.0, "total": 0.0}
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
        for k in totals:
            totals[k] += data["totals"][k]
    rows.sort(key=lambda r: (r["date"], r["name"]))
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
    out = []
    for r in rows:
        label = r["number"] or r["name"]
        if r["doctype"] == tax.RK:
            label = f"{_('РК')} {label}"
        out.append(
            model.make_row(
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
                links={"number": {"doctype": r["doctype"], "name": r["name"]}},
            )
        )
    if out:
        out.append(
            model.make_row(
                "total",
                {"number": _("Разом"), **{k: model.money(v) for k, v in totals.items()}},
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


def _to_date(value):
    from frappe.utils import getdate

    return getdate(value)
