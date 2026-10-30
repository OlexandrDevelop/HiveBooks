"""Розрахунок податкових різниць (ПКУ ст. 138–141) for the profit tax return."""

from frappe import _

from ua_accounting.accounting import tax_ledger
from ua_accounting.reporting import model
from ua_accounting.reporting.filters import parse_filters


def build(raw):
    flt_ = parse_filters(raw)
    orgs = flt_.organizations or ([flt_.opts["organization"]] if flt_.opts.get("organization") else [])
    columns = [
        {"key": "kind", "kind": "text", "align": "left"},
        {"key": "article", "kind": "text", "align": "left"},
        {"key": "book", "kind": "money", "align": "right"},
        {"key": "tax", "kind": "money", "align": "right"},
        {"key": "adjustment", "kind": "money", "align": "right"},
    ]
    header = [
        [
            model.header_cell(_("Вид різниці")),
            model.header_cell(_("Стаття ПКУ")),
            model.header_cell(_("Сума БО")),
            model.header_cell(_("Сума ПО")),
            model.header_cell(_("Коригування")),
        ]
    ]
    lines = [_("Період: з {0} по {1}").format(model.fmt_date(flt_.date_from), model.fmt_date(flt_.date_to))]
    if len(orgs) != 1:
        return _result(header, columns, lines, [], _("Оберіть одну організацію"))
    res = tax_ledger.tax_differences(orgs[0], flt_.date_from, flt_.date_to)
    lines.append(
        _("Дохід за останній річний період: {0} грн (поріг {1} грн)").format(
            _fmt(res["income"]), _fmt(res["threshold"])
        )
    )
    if not res["required"]:
        return _result(header, columns, lines, [], _("Коригування фінансового результату не обов'язкові"))
    rows = [
        model.make_row(
            r["kind"],
            {
                "kind": _(r["kind"]),
                "article": r["article"],
                "book": model.money(r["book_amount"]),
                "tax": model.money(r["tax_amount"]),
                "adjustment": model.money(r["adjustment"]),
            },
        )
        for r in res["rows"]
    ]
    rows.append(
        model.make_row(
            "total",
            {"kind": _("Усього коригування"), "adjustment": model.money(res["total_adjustment"])},
            kind="total",
            bold=True,
        )
    )
    return _result(header, columns, lines, rows, "")


def _fmt(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _result(header, columns, lines, rows, message):
    return {
        "report": "tax_differences",
        "title": _("Розрахунок податкових різниць"),
        "lines": lines,
        "header": header,
        "columns": columns,
        "rows": rows,
        "truncated": False,
        "message": message,
    }
