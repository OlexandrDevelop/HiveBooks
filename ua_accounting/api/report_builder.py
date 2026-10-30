"""Whitelisted methods of the universal report and of its saved variants (reporting/builder.py)."""

import base64
import json

import frappe
from frappe import _
from frappe.utils import cint

from ua_accounting.reporting import builder, builder_export

VARIANT = "UA Report Variant"
VARIANT_FIELDS = ["name", "variant_name", "owner", "is_shared", "is_default", "source", "report", "settings"]
SETTING_KEYS = ("columns", "group_by", "measures", "filters", "sort", "format")


def _variants(**filters):
    """Variants the user may see: own and shared (the data rights are not touched here)."""
    user = frappe.session.user
    rows = frappe.get_all(VARIANT, filters=filters, fields=VARIANT_FIELDS, ignore_permissions=True, limit_page_length=0)
    return [r for r in rows if r.owner == user or cint(r.is_shared)]


def _find_variant(variant, source, report):
    user = frappe.session.user
    found = _variants(variant_name=variant, source=source, report=report)
    found.sort(key=lambda r: r.owner != user)
    if not found:
        found = [r for r in _variants(name=variant) if r.report == report and r.source == source]
    if not found:
        frappe.throw(_("Варіант звіту {0} не знайдено").format(variant), frappe.DoesNotExistError)
    return found[0]


def _settings(source, settings, report, variant):
    """The settings of the call over the settings of the variant, key by key."""
    own = builder.parse_settings(settings)
    if not variant:
        return own
    merged = builder.parse_settings(_find_variant(variant, source, report).settings)
    merged.update({k: v for k, v in own.items() if k in SETTING_KEYS})
    return merged


def _run(source, settings, filters, report, variant):
    report = report or builder.UNIVERSAL
    return builder.run(source, _settings(source, settings, report, variant), filters, report)


def _title(source, report):
    if report != builder.UNIVERSAL:
        return _("Універсальний звіт")
    name = _("Проводки") if builder.is_ledger(source) else _(source)
    return f"{_('Універсальний звіт')}: {name}"


@frappe.whitelist(methods=["POST"])
def run(source, settings=None, filters=None, report=builder.UNIVERSAL, variant=None):
    return _run(source, settings, filters, report, variant)


@frappe.whitelist(methods=["POST"])
def get_fields(source, report=builder.UNIVERSAL):
    return builder.get_fields(source, report or builder.UNIVERSAL)


@frappe.whitelist(methods=["POST"])
def export_excel(source, settings=None, filters=None, report=builder.UNIVERSAL, variant=None):
    result = _run(source, settings, filters, report, variant)
    content = builder_export.to_xlsx(_title(source, report), result)
    return {"filename": "universal_report.xlsx", "content": base64.b64encode(content).decode()}


@frappe.whitelist(methods=["POST"])
def export_pdf(source, settings=None, filters=None, report=builder.UNIVERSAL, variant=None):
    from frappe.utils.pdf import get_pdf

    result = _run(source, settings, filters, report, variant)
    html = builder_export.to_html(_title(source, report), result)
    content = get_pdf(html, {"orientation": "Landscape"})
    return {"filename": "universal_report.pdf", "content": base64.b64encode(content).decode()}


@frappe.whitelist(methods=["POST"])
def save_variant(variant_name, source, settings=None, report=builder.UNIVERSAL, is_shared=0, is_default=0):
    """Save the settings under a name. The same name of the same user updates the variant."""
    report = report or builder.UNIVERSAL
    name = (variant_name or "").strip()
    if not name:
        frappe.throw(_("Вкажіть назву варіанту"), frappe.ValidationError)
    data = builder.validate_settings(source, settings, report)
    user = frappe.session.user
    existing = frappe.db.get_value(
        VARIANT, {"owner": user, "variant_name": name, "source": source, "report": report}, "name"
    )
    doc = frappe.get_doc(VARIANT, existing) if existing else frappe.new_doc(VARIANT)
    doc.update({
        "variant_name": name, "source": source, "report": report, "settings": json.dumps(data, ensure_ascii=False),
        "is_shared": cint(is_shared), "is_default": cint(is_default),
    })
    doc.save() if existing else doc.insert()
    if doc.is_default:
        others = frappe.get_all(
            VARIANT, filters={"owner": user, "source": source, "report": report, "is_default": 1, "name": ("!=", doc.name)},
            pluck="name", ignore_permissions=True,
        )
        for other in others:
            frappe.db.set_value(VARIANT, other, "is_default", 0)
    return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def list_variants(source, report=builder.UNIVERSAL):
    user = frappe.session.user
    rows = _variants(source=source, report=report or builder.UNIVERSAL)
    rows.sort(key=lambda r: (r.owner != user, r.variant_name))
    return [
        {
            "name": r.name, "variant_name": r.variant_name, "owner": r.owner, "is_shared": cint(r.is_shared),
            "is_default": cint(r.is_default), "is_mine": int(r.owner == user),
        }
        for r in rows
    ]


@frappe.whitelist(methods=["POST"])
def delete_variant(name):
    """Only the owner (and System Manager) deletes a variant."""
    frappe.delete_doc(VARIANT, name)
    return {"deleted": name}


@frappe.whitelist(methods=["POST"])
def sources():
    """Sources the user may read: the ledger and the UA DocTypes (not child tables)."""
    out = [{"value": builder.LEDGER_CODE, "label": _("Проводки")}]
    names = frappe.get_all(
        "DocType", filters={"name": ("like", "UA %"), "istable": 0}, pluck="name",
        ignore_permissions=True, limit_page_length=0,
    )
    for name in names:
        if name != builder.LEDGER and frappe.has_permission(name, "read"):
            out.append({"value": name, "label": _(name)})
    out[1:] = sorted(out[1:], key=lambda x: x["label"])
    return out
