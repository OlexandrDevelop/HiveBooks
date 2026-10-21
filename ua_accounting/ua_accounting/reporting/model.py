"""The table model: what the browser draws, prints and what the Excel export writes.

{
  "report": "osv", "title": "...", "lines": ["Організація: ...", ...],
  "header": [[{"label", "colspan", "rowspan"}, ...], ...],
  "columns": [{"key", "kind", "align"}],      kind: label|money|qty|text|date|doc|lines
  "rows": [{"id", "parent", "level", "kind", "bold", "cells": {key: value},
            "drill": {...}, "links": {key: {"doctype", "name"}}}],
  "truncated": false, "message": ""
}
Row kinds: group, item, total, open, close.
"""

from frappe import _
from frappe.utils import flt

LABEL = {"key": "label", "kind": "label", "align": "left"}


def fmt_date(value):
    return value.strftime("%d.%m.%Y")


def header_cell(label, colspan=1, rowspan=1):
    return {"label": label, "colspan": colspan, "rowspan": rowspan}


def money(value):
    return flt(value, 2)


def qty(value):
    return flt(value, 3)


def make_row(
    row_id,
    cells,
    level=0,
    kind="item",
    bold=False,
    parent=None,
    drill=None,
    links=None,
):
    return {
        "id": row_id,
        "parent": parent,
        "level": level,
        "kind": kind,
        "bold": bold,
        "cells": cells,
        "drill": drill,
        "links": links or {},
    }


def header_lines(flt_, chart, titles):
    """Lines under the report title: organization, period, active filters."""
    if flt_.organizations:
        titles.preload(("UA Organization", o) for o in flt_.organizations)
        names = ", ".join(titles.get("UA Organization", o) for o in flt_.organizations)
        org_line = _("Організація: {0}").format(names)
    else:
        org_line = _("Організація: усі")
    lines = [
        org_line,
        _("Період: з {0} по {1}").format(fmt_date(flt_.date_from), fmt_date(flt_.date_to)),
    ]
    parts = []
    if flt_.accounts:
        parts.append(_("Рахунок: {0}").format(", ".join(chart.label(a) for a in flt_.accounts)))
    for f in flt_.subconto:
        t = chart.types.get(f["type"])
        dt = t.reference_doctype if t and not t.is_dynamic else None
        if dt:
            titles.preload((dt, v) for v in f["values"])
        vals = ", ".join((titles.get(dt, v) if dt else v) or _("<не задано>") for v in f["values"])
        parts.append(f"{chart.type_title(f['type'])}: {vals}")
    if flt_.currency:
        parts.append(_("Валюта: {0}").format(flt_.currency))
    if parts:
        lines.append(_("Відбір: {0}").format("; ".join(parts)))
    return lines
