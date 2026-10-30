"""Accountant calendar: tasks for taxes and reports, home page buckets and reminders."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from ua_accounting.accounting import deadlines as dl
from ua_accounting.accounting_policy import policy_for

TASK = "UA Accountant Task"
DONE = "Виконано"
OPEN = "Не виконано"
LATE = "Прострочено"
AUTO = "Автоматично"
MANUAL = "Вручну"
REMINDER_MARK = "ua-reminder:"

T_TAX, T_REPORT, T_OTHER = "Податок", "Звіт", "Інше"
FIELDS = ["name", "organization", "rule_code", "title", "task_type", "period_start", "period_end", "due_date",
          "status", "source", "assigned_to", "remind_days", "done_on"]


def effective_status(status, due_date, today):
    if status == DONE:
        return DONE
    return LATE if getdate(due_date) < getdate(today) else OPEN


# ---------------------------------------------------------------- generation


def _taxation(organization, period_end):
    """(VAT payer, tax system) valid on the end of the period."""
    policy = policy_for(organization, period_end)
    if policy:
        return bool(policy.vat_payer), policy.tax_system or ""
    org = frappe.db.get_value("UA Organization", organization, ["vat_payer", "tax_system"], as_dict=True)
    return bool(org.vat_payer), org.tax_system or ""


def _is_single(system):
    return system.startswith("Єдиний податок") and system[-7:-6] in ("3", "4")


def _is_general(system):
    return not system or system == "Загальна система"


def _periods(year):
    for month in range(1, 13):
        yield dl.month_end(year, month), month


def planned_tasks(organization, year):
    """Rows of the tasks of the reporting periods that lie in `year`."""
    rows = []

    def add(code, title, kind, start, end, due):
        rows.append(
            {"rule_code": code, "title": title, "task_type": kind, "period_start": start, "period_end": end, "due_date": due}
        )

    for end, month in _periods(year):
        start = end.replace(day=1)
        label = dl.month_title(year, month)
        vat_payer, _system = _taxation(organization, end)
        if vat_payer:
            decl, pay = dl.vat_return(end)
            add(dl.VAT_DECL, f"Декларація з ПДВ за {label}", T_REPORT, start, end, decl)
            add(dl.VAT_PAY, f"Сплата ПДВ за {label}", T_TAX, start, end, pay)
        add(dl.ESV_REPORT, f"Єдиний звіт з ЄСВ за {label}", T_REPORT, start, end, dl.esv_report(end))
    for quarter in range(1, 5):
        end = dl.quarter_end(year, quarter)
        start = end.replace(month=quarter * 3 - 2, day=1)
        label = dl.quarter_title(year, quarter)
        _vat, system = _taxation(organization, end)
        decl, pay = dl.quarter_return(end)
        if _is_general(system):
            add(dl.CIT_DECL, f"Декларація з податку на прибуток за {label}", T_REPORT, start, end, decl)
            add(dl.CIT_PAY, f"Сплата податку на прибуток за {label}", T_TAX, start, end, pay)
        elif _is_single(system):
            add(dl.SINGLE_DECL, f"Декларація єдиного податку за {label}", T_REPORT, start, end, decl)
            add(dl.SINGLE_PAY, f"Сплата єдиного податку за {label}", T_TAX, start, end, pay)
    return rows


def generate(organization, year):
    year = cint(year)
    if year < 2000 or year > 2100:
        frappe.throw(_("Рік {0} не підтримується").format(year), frappe.ValidationError)
    if not frappe.db.exists("UA Organization", organization):
        frappe.throw(_("Організацію {0} не знайдено").format(organization), frappe.ValidationError)
    created = skipped = 0
    for row in planned_tasks(organization, year):
        if frappe.db.exists(
            TASK, {"organization": organization, "rule_code": row["rule_code"], "period_start": row["period_start"]}
        ):
            skipped += 1
            continue
        frappe.get_doc({"doctype": TASK, "organization": organization, "source": AUTO, "remind_days": 3, **row}).insert()
        created += 1
    return {"created": created, "skipped": skipped}


# ---------------------------------------------------------------- home page


def _row(task, today):
    status = effective_status(task.status, task.due_date, today)
    return {
        **{k: (str(v) if k.endswith("_date") or k.endswith("_start") or k.endswith("_end") or k == "done_on" else v)
           for k, v in task.items() if v is not None},
        "status": status,
        "days_left": date_diff(task.due_date, today),
    }


def get_home(organization, today=None, horizon_days=30):
    today = getdate(today or nowdate())
    horizon = cint(horizon_days if horizon_days is not None else 30)
    tasks = frappe.get_all(
        TASK, filters={"organization": organization, "status": ("!=", DONE)}, fields=FIELDS,
        order_by="due_date asc, rule_code asc, name asc", limit_page_length=0,
    )
    out = {"overdue": [], "today": [], "upcoming": []}
    limit = add_days(today, horizon)
    for task in tasks:
        due = getdate(task.due_date)
        if due < today:
            out["overdue"].append(_row(task, today))
        elif due == today:
            out["today"].append(_row(task, today))
        elif due <= limit:
            out["upcoming"].append(_row(task, today))
    out["counts"] = {key: len(out[key]) for key in ("overdue", "today", "upcoming")}
    return out


def _get(name):
    if not frappe.db.exists(TASK, name):
        frappe.throw(_("Завдання {0} не знайдено").format(name), frappe.DoesNotExistError)
    doc = frappe.get_doc(TASK, name)
    doc.check_permission("write")
    return doc


def complete(name):
    doc = _get(name)
    doc.status = DONE
    doc.done_on = nowdate()
    doc.save()
    return {"name": doc.name, "status": doc.status, "done_on": str(doc.done_on)}


def reopen(name):
    doc = _get(name)
    doc.status = OPEN
    doc.done_on = None
    doc.save()
    return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------- reminders (the bell)


def send_reminders(today=None):
    today = getdate(today or nowdate())
    mark = f"<!-- {REMINDER_MARK}{today} -->"
    sent = 0
    reminded = []
    tasks = frappe.get_all(
        TASK, filters={"status": ("!=", DONE), "assigned_to": ("is", "set")}, fields=FIELDS, limit_page_length=0
    )
    for task in tasks:
        left = date_diff(task.due_date, today)
        if left > cint(task.remind_days):
            continue
        if frappe.db.exists(
            "Notification Log",
            {"document_type": TASK, "document_name": task.name, "for_user": task.assigned_to, "email_content": ("like", f"%{mark}%")},
        ):
            continue
        due = getdate(task.due_date).strftime("%d.%m.%Y")
        subject = (
            _("Прострочено: {0} (строк {1})").format(task.title, due)
            if left < 0
            else _("Нагадування: {0} (строк {1})").format(task.title, due)
        )
        frappe.get_doc(
            {
                "doctype": "Notification Log", "type": "Alert", "for_user": task.assigned_to, "subject": subject,
                "email_content": f"<div>{frappe.utils.escape_html(subject)}</div>{mark}",
                "document_type": TASK, "document_name": task.name,
            }
        ).insert(ignore_permissions=True)
        sent += 1
        reminded.append({"organization": task.organization, "task": task.name})
    return {"sent": sent, "tasks": reminded}
