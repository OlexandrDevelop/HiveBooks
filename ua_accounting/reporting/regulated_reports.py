"""Регламентована звітність: reports of the year by period with deadlines (workplace)."""

from frappe import _
from frappe.utils import getdate

from ua_accounting.accounting import regulated_report as rr
from ua_accounting.reporting import model
from ua_accounting.reporting.filters import parse_filters


def build(raw):
    flt_ = parse_filters(raw)
    orgs = flt_.organizations or ([flt_.opts["organization"]] if flt_.opts.get("organization") else [])
    columns = [
        {"key": "report", "kind": "text", "align": "left"},
        {"key": "period", "kind": "text", "align": "left"},
        {"key": "deadline", "kind": "text", "align": "left"},
        {"key": "status", "kind": "text", "align": "left"},
    ]
    header = [
        [
            model.header_cell(_("Звіт")),
            model.header_cell(_("Період")),
            model.header_cell(_("Строк подання")),
            model.header_cell(_("Статус")),
        ]
    ]
    result = {
        "report": "regulated_reports",
        "title": _("Регламентована звітність"),
        "lines": [_("Рік: {0}").format(flt_.date_to.year)],
        "header": header,
        "columns": columns,
        "rows": [],
        "truncated": False,
        "message": "",
    }
    if len(orgs) != 1:
        result["message"] = _("Оберіть одну організацію")
        return result
    rr.check_access(orgs[0])
    for i, r in enumerate(rr.calendar(orgs[0], flt_.date_to.year)):
        result["rows"].append(
            model.make_row(
                r["report"] or f"{i}",
                {
                    "report": _(r["report_kind"]),
                    "period": f"{model.fmt_date(getdate(r['period_from']))} – {model.fmt_date(getdate(r['period_to']))}",
                    "deadline": model.fmt_date(getdate(r["deadline"])),
                    "status": _(r["status"]),
                },
            )
        )
    return result
