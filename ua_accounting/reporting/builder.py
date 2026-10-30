"""Universal report (a light analog of 1C СКД): user settings over the ledger, a UA DocType or a built-in report.

Settings object (see tests/blackbox/backlog/T-444/CONTRACT.md):
    columns, group_by, measures, filters, sort, format
run(source, settings, filters, report) -> {columns, rows, totals, count}
Rows are read with frappe.get_list: the rights and the organization limits of the user always apply.
"""

import re
from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import cint, flt

LEDGER = "UA Accounting Entry"
LEDGER_CODE = "ledger"
UNIVERSAL = "universal"
# report codes that read the ledger rows
LEDGER_REPORTS = ("entries_report",)

SKIP_TYPES = (
    "Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table", "Table MultiSelect", "Image",
    "Heading", "Fold", "Attach", "Attach Image", "Signature", "Barcode", "Geolocation", "Code", "Long Text",
    "Text Editor", "Markdown Editor", "HTML Editor", "JSON", "Password", "Read Only", "Duration",
)
NUMBER_TYPES = ("Currency", "Float", "Int", "Percent")
TOTAL_TYPES = ("Currency", "Float")
DATE_TYPES = ("Date", "Datetime")
OPS = ("=", "!=", ">", ">=", "<", "<=", "in", "not in", "like", "between", "is set", "is not set")
AGGS = ("sum", "count", "avg", "min", "max")
PARTS = ("month", "year")
MAX_LEVELS = 3
STANDARD = (
    ("name", "Код", "Data"),
    ("docstatus", "Статус документа", "Int"),
    ("creation", "Створено", "Datetime"),
    ("modified", "Змінено", "Datetime"),
)


def bad(message):
    frappe.throw(message, frappe.ValidationError)


# ------------------------------------------------------------------ sources
def is_ledger(source):
    return source in (LEDGER_CODE, LEDGER)


def doctype_of(source):
    """The DocType that is read for the source; checks the name and the read right."""
    if is_ledger(source):
        doctype = LEDGER
    else:
        doctype = source
        if not isinstance(doctype, str) or not doctype.startswith("UA ") or not frappe.db.exists("DocType", doctype):
            bad(_("Невідоме джерело звіту {0}").format(source))
        if frappe.get_meta(doctype).istable:
            bad(_("Таблиця документа не може бути джерелом звіту"))
    frappe.has_permission(doctype, "read", throw=True)
    return doctype


def doctype_fields(doctype):
    meta = frappe.get_meta(doctype)
    out = OrderedDict()
    for fieldname, label, fieldtype in STANDARD:
        if fieldname == "docstatus" and not meta.is_submittable:
            continue
        out[fieldname] = {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "options": None}
    for df in meta.fields:
        if df.fieldtype in SKIP_TYPES or not df.fieldname or df.hidden:
            continue
        out[df.fieldname] = {
            "fieldname": df.fieldname, "label": df.label or df.fieldname, "fieldtype": df.fieldtype, "options": df.options,
        }
    return out


def model_fields(table):
    """Fields of a built-in report: the columns of its table model."""
    kinds = {"money": "Currency", "qty": "Float", "date": "Date"}
    labels = {}
    if table.get("header") and len(table["header"][-1]) == len(table["columns"]):
        labels = {c["key"]: h["label"] for c, h in zip(table["columns"], table["header"][-1])}
    out = OrderedDict()
    for col in table["columns"]:
        out[col["key"]] = {
            "fieldname": col["key"], "label": labels.get(col["key"]) or col["key"],
            "fieldtype": kinds.get(col["kind"], "Data"), "options": None,
        }
    return out


class Source:
    """What the settings are applied to: the field list and the way to read the records."""

    def __init__(self, source, report=UNIVERSAL):
        self.source = source
        self.report = report or UNIVERSAL
        self.table = None
        if self.report == UNIVERSAL or self.report in LEDGER_REPORTS:
            self.doctype = doctype_of(source if self.report == UNIVERSAL else LEDGER_CODE)
            self.fields = doctype_fields(self.doctype)
            self.meta = frappe.get_meta(self.doctype)
        else:
            from ua_accounting.reporting.api import REPORTS

            if self.report not in REPORTS:
                bad(_("Невідомий звіт {0}").format(self.report))
            self.doctype = None
            self.meta = None
            self.fields = None  # known after the report is built

    def set_table(self, table):
        self.table = table
        self.fields = model_fields(table)


def get_fields(source, report=UNIVERSAL):
    if report == UNIVERSAL or report in LEDGER_REPORTS:
        src = Source(source, report)
        return list(src.fields.values())
    bad(_("Поля вбудованого звіту відомі після його формування"))


# ------------------------------------------------------------------ settings
def parse_settings(settings):
    data = frappe.parse_json(settings) if isinstance(settings, str) else settings
    if not data:
        return {}
    if not isinstance(data, dict):
        bad(_("Налаштування звіту мають бути об'єктом"))
    return dict(data)


def as_list(value, name):
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        bad(_("Налаштування {0} мають бути списком").format(name))
    return list(value)


def check_field(fields, name):
    if name not in fields:
        bad(_("Невідоме поле {0}").format(name))
    return fields[name]


def clean_columns(fields, raw):
    out = []
    for item in as_list(raw, "columns"):
        if isinstance(item, str):
            item = {"field": item}
        if not isinstance(item, dict) or not item.get("field"):
            bad(_("Колонку звіту не знайдено. Виберіть колонку зі списку"))
        df = check_field(fields, item["field"])
        out.append({"field": item["field"], "label": item.get("label") or df["label"]})
    return out


def clean_group(fields, raw):
    out = []
    for item in as_list(raw, "group_by"):
        name, _sep, part = str(item).partition(":")
        df = check_field(fields, name)
        if part and (part not in PARTS or df["fieldtype"] not in DATE_TYPES):
            bad(_("Частину дати «{0}» не розпізнано. Виберіть рік, квартал, місяць або день").format(part))
        if any(g["field"] == name for g in out):
            bad(_("Поле {0} вже є в групуванні").format(name))
        out.append({"field": name, "part": part})
    if len(out) > MAX_LEVELS:
        bad(_("Групувань може бути не більше {0}").format(MAX_LEVELS))
    return out


def clean_measures(fields, raw):
    out = []
    for item in as_list(raw, "measures"):
        if isinstance(item, str):
            item = {"field": item}
        if not isinstance(item, dict):
            bad(_("Показник звіту не знайдено. Виберіть показник зі списку"))
        df = check_field(fields, item.get("field"))
        numeric = df["fieldtype"] in NUMBER_TYPES
        agg = item.get("agg") or ("sum" if numeric else "count")
        if agg not in AGGS:
            bad(_("Невідома функція {0}").format(agg))
        if agg in ("sum", "avg") and not numeric:
            bad(_("Функція {0} потребує числового поля").format(agg))
        out.append({"field": item["field"], "agg": agg})
    return out


def clean_rules(fields, raw, name):
    out = []
    for item in as_list(raw, name):
        if not isinstance(item, dict):
            bad(_("Правило «{0}» не розпізнано. Виберіть правило зі списку").format(name))
        check_field(fields, item.get("field"))
        op = item.get("op")
        if op not in OPS:
            bad(_("Невідома умова {0}").format(op))
        value = item.get("value")
        if op == "between" and not (isinstance(value, (list, tuple)) and len(value) == 2):
            bad(_("Умова «між» потребує двох значень"))
        if op in ("in", "not in") and not isinstance(value, (list, tuple)):
            bad(_("Умова «{0}» потребує списку").format(op))
        rule = {"field": item["field"], "op": op, "value": value}
        if name == "format":
            style = item.get("style") or {}
            if not isinstance(style, dict):
                bad(_("Оформлення не розпізнано. Виберіть оформлення зі списку"))
            rule["style"] = style
        out.append(rule)
    return out


def clean_sort(fields, raw):
    out = []
    for item in as_list(raw, "sort"):
        if isinstance(item, str):
            item = {"field": item}
        check_field(fields, item.get("field"))
        direction = item.get("dir") or "asc"
        if direction not in ("asc", "desc"):
            bad(_("Напрям сортування «{0}» не розпізнано. Виберіть «за зростанням» або «за спаданням»").format(direction))
        out.append({"field": item["field"], "dir": direction})
    return out


def clean(fields, settings):
    """Validated settings; an unknown field, condition or function stops the report."""
    s = parse_settings(settings)
    return {
        "columns": clean_columns(fields, s.get("columns")),
        "group_by": clean_group(fields, s.get("group_by")),
        "measures": clean_measures(fields, s.get("measures")),
        "filters": clean_rules(fields, s.get("filters"), "filters"),
        "sort": clean_sort(fields, s.get("sort")),
        "format": clean_rules(fields, s.get("format"), "format"),
    }


def validate_settings(source, settings, report=UNIVERSAL):
    """Check the settings of a variant (a built-in report: the fields are known only at run time)."""
    s = parse_settings(settings)
    if report == UNIVERSAL or report in LEDGER_REPORTS:
        clean(Source(source, report).fields, s)
    return s


# ------------------------------------------------------------------ conditions
def to_text(value):
    return "" if value is None else str(value)


def _cmp_value(fieldtype, value):
    if fieldtype in NUMBER_TYPES or fieldtype == "Check":
        return flt(value)
    return to_text(value)


def matches(value, op, expected, fieldtype):
    """The condition of a filter or of a format rule for one value (Python side)."""
    if op in ("is set", "is not set"):
        filled = value not in (None, "")
        return filled if op == "is set" else not filled
    if op == "between":
        low, high = (_cmp_value(fieldtype, v) for v in expected)
        return low <= _cmp_value(fieldtype, value) <= high
    if op in ("in", "not in"):
        found = _cmp_value(fieldtype, value) in [_cmp_value(fieldtype, v) for v in expected]
        return found if op == "in" else not found
    if op == "like":
        wild = {"%": ".*", "_": "."}
        pattern = "".join(wild.get(ch) or re.escape(ch) for ch in str(expected))
        return re.fullmatch(pattern, to_text(value), re.I | re.S) is not None
    left, right = _cmp_value(fieldtype, value), _cmp_value(fieldtype, expected)
    return {
        "=": left == right, "!=": left != right, ">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right,
    }[op]


def db_filter(rule):
    """A rule as a frappe.get_list filter."""
    field, op, value = rule["field"], rule["op"], rule.get("value")
    if op == "is set":
        return [field, "is", "set"]
    if op == "is not set":
        return [field, "is", "not set"]
    return [field, op, value]


def outer_filters(src, raw):
    """The common filters (period, organizations) as get_list filters, for the fields that exist."""
    f = frappe.parse_json(raw) if isinstance(raw, str) else dict(raw or {})
    out = []
    if src.meta.has_field("posting_date"):
        if f.get("date_from"):
            out.append(["posting_date", ">=", f["date_from"]])
        if f.get("date_to"):
            out.append(["posting_date", "<=", f["date_to"]])
    orgs = f.get("organizations")
    if isinstance(orgs, str):
        orgs = frappe.parse_json(orgs) if orgs.strip().startswith("[") else [o.strip() for o in orgs.split(",") if o.strip()]
    if orgs and src.meta.has_field("organization"):
        out.append(["organization", "in", list(orgs)])
    return out


# ------------------------------------------------------------------ reading
def read_records(src, s, raw_filters, needed):
    """Records as dicts; the filters are applied by the database."""
    if src.table is not None:
        return read_model(src, s, raw_filters)
    if src.meta.issingle:
        return read_single(src, s)
    filters = outer_filters(src, raw_filters) + [db_filter(r) for r in s["filters"]]
    if src.meta.is_submittable and not any(r["field"] == "docstatus" for r in s["filters"]):
        filters.append(["docstatus", "=", 1])
    fields = [f for f in needed if f in src.fields]
    if "name" not in fields:
        fields.append("name")
    order = "posting_date asc, creation asc" if src.meta.has_field("posting_date") else "creation asc"
    return frappe.get_list(src.doctype, fields=fields, filters=filters, limit_page_length=0, order_by=order)


def read_single(src, s):
    """A Single DocType is one record made of its values (the read right is checked in doctype_of)."""
    record = frappe.get_doc(src.doctype).as_dict()
    record["name"] = src.doctype
    rows = [dict(record)]
    return [r for r in rows if all(matches(r.get(f["field"]), f["op"], f.get("value"), src.fields[f["field"]]["fieldtype"]) for f in s["filters"])]


def read_model(src, s, raw_filters):
    rows = []
    for row in src.table["rows"]:
        if row.get("kind") in ("item", None):
            rows.append(dict(row["cells"]))
    return [r for r in rows if all(matches(r.get(f["field"]), f["op"], f.get("value"), src.fields[f["field"]]["fieldtype"]) for f in s["filters"])]


# ------------------------------------------------------------------ calculation
def date_key(value, part):
    text = to_text(value)
    if not text:
        return ""
    return text[:7] if part == "month" else text[:4] if part == "year" else text


def aggregate(agg, values):
    nums = [v for v in values if v is not None]
    if agg == "count":
        return len(nums)
    if not nums:
        return 0
    if agg == "sum":
        return flt(sum(flt(v) for v in nums), 2)
    if agg == "avg":
        return flt(sum(flt(v) for v in nums) / len(nums), 2)
    return min(nums) if agg == "min" else max(nums)


def sort_key(value):
    if value is None or value == "":
        return (0, 0, "")
    if isinstance(value, (int, float)):
        return (1, value, "")
    return (2, 0, to_text(value))


def sort_by(items, getter, direction):
    items.sort(key=lambda x: sort_key(getter(x)), reverse=direction == "desc")


def default_measures(src, s):
    names = [c["field"] for c in s["columns"]] or list(src.fields)
    grouped = [g["field"] for g in s["group_by"]]
    numeric = [n for n in names if src.fields[n]["fieldtype"] in TOTAL_TYPES and n not in grouped]
    return [{"field": n, "agg": "sum"} for n in numeric]


def style_row(row, rules, fields):
    styles = {}
    for rule in rules:
        field = rule["field"]
        if field in row and matches(row[field], rule["op"], rule.get("value"), fields[field]["fieldtype"]):
            styles[field] = rule["style"]
    if styles:
        row["_format"] = styles


def build_flat(src, s, records):
    columns = s["columns"] or [{"field": n, "label": d["label"]} for n, d in src.fields.items() if n not in ("creation", "modified")]
    for item in reversed(s["sort"]):
        sort_by(records, lambda r, f=item["field"]: r.get(f), item["dir"])
    rows = []
    for rec in records:
        row = {c["field"]: rec.get(c["field"]) for c in columns}
        # a rule is checked on the whole record, also on a field that is not shown
        styles = {}
        for rule in s["format"]:
            f = rule["field"]
            if matches(rec.get(f), rule["op"], rule.get("value"), src.fields[f]["fieldtype"]):
                styles[f] = rule["style"]
        if styles:
            row["_format"] = styles
        rows.append(row)
    totals = {
        c["field"]: flt(sum(flt(r.get(c["field"])) for r in records), 2)
        for c in columns if src.fields[c["field"]]["fieldtype"] in TOTAL_TYPES
    }
    result_columns = [
        {"fieldname": c["field"], "label": c["label"], "fieldtype": src.fields[c["field"]]["fieldtype"]} for c in columns
    ]
    return result_columns, rows, totals


def build_grouped(src, s, records):
    groups = s["group_by"]
    group_fields = [g["field"] for g in groups]
    # a measure of a group field gets its own key: the group value stays in the field
    measures = [
        dict(m, key=f"{m['field']}_{m['agg']}" if m["field"] in group_fields else m["field"])
        for m in (s["measures"] or default_measures(src, s))
    ]
    labels = {c["field"]: c["label"] for c in s["columns"]}

    def key_of(rec, level):
        g = groups[level]
        value = rec.get(g["field"])
        return date_key(value, g["part"]) if g["part"] else value

    def measure_values(recs):
        return {m["key"]: aggregate(m["agg"], [r.get(m["field"]) for r in recs]) for m in measures}

    def walk(recs, level, parent):
        buckets = OrderedDict()
        for rec in recs:
            buckets.setdefault(key_of(rec, level), []).append(rec)
        nodes = [(key, items) for key, items in buckets.items()]
        sort_by(nodes, lambda n: n[0], "asc")
        field = groups[level]["field"]
        built = []
        for key, items in nodes:
            row = dict(parent)
            row.update({"_level": level + 1, "_count": len(items), field: key})
            row.update(measure_values(items))
            built.append((row, items))
        for item in reversed(s["sort"]):
            if item["field"] == field or any(m["key"] == item["field"] for m in measures):
                sort_by(built, lambda b, f=item["field"]: b[0].get(f), item["dir"])
        out = []
        for row, items in built:
            out.append(row)
            if level + 1 < len(groups):
                keys = {g["field"]: row[g["field"]] for g in groups[: level + 1]}
                out.extend(walk(items, level + 1, keys))
        return out

    rows = walk(records, 0, {})
    for row in rows:
        style_row(row, s["format"], src.fields)
    totals = measure_values(records)
    columns = []
    for g in groups:
        df = src.fields[g["field"]]
        columns.append({
            "fieldname": g["field"], "label": labels.get(g["field"]) or df["label"],
            "fieldtype": "Data" if g["part"] else df["fieldtype"],
        })
    for m in measures:
        df = src.fields[m["field"]]
        columns.append({
            "fieldname": m["key"], "label": labels.get(m["field"]) or df["label"],
            "fieldtype": "Int" if m["agg"] == "count" else df["fieldtype"],
        })
    return columns, rows, totals


def needed_fields(src, s):
    names = [c["field"] for c in s["columns"]] or [n for n in src.fields if n not in ("creation", "modified")]
    names += [g["field"] for g in s["group_by"]] + [m["field"] for m in s["measures"]]
    names += [i["field"] for i in s["sort"]] + [i["field"] for i in s["format"]]
    if s["group_by"] and not s["measures"]:
        names += [n for n in src.fields if src.fields[n]["fieldtype"] in TOTAL_TYPES]
    return list(OrderedDict.fromkeys(names))


def run(source, settings, filters=None, report=UNIVERSAL):
    src = Source(source, report)
    if src.table is None and src.fields is None:
        from ua_accounting.reporting.api import _build

        src.set_table(_build(src.report, filters))
    s = clean(src.fields, settings)
    records = read_records(src, s, filters, needed_fields(src, s))
    if s["group_by"]:
        columns, rows, totals = build_grouped(src, s, records)
    else:
        columns, rows, totals = build_flat(src, s, records)
    return {"columns": columns, "rows": rows, "totals": totals, "count": len(records)}
