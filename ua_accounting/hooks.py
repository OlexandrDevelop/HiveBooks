app_name = "ua_accounting"
app_title = "HiveBooks"
app_publisher = "UA Accounting"
app_description = "Accounting system for Ukraine (chart of accounts No. 291, subconto, ledger)"
app_email = "olexandr.develop@gmail.com"
app_license = "MIT"

# the app depends only on frappe
required_apps = []

add_to_apps_screen = [
    {
        "name": "ua_accounting",
        "logo": "/assets/ua_accounting/images/logo.svg",
        "title": "HiveBooks",
        "route": "/app/ua-home",
    }
]



def _asset_version():
    # The files are served without a hash and browsers keep them for 12 hours.
    # A version from their content makes the browser load new files after each change.
    import hashlib
    import os

    public = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")
    digest = hashlib.md5(usedforsecurity=False)
    for folder in ("css", "js"):
        path = os.path.join(public, folder)
        for name in sorted(os.listdir(path)):
            with open(os.path.join(path, name), "rb") as f:
                digest.update(f.read())
    return digest.hexdigest()[:12]


_v = _asset_version()

app_include_css = [
    f"/assets/ua_accounting/css/{name}.css?v={_v}"
    for name in ("ua_theme", "ua_components", "ua_desk", "ua_report")
]
app_include_js = [
    f"/assets/ua_accounting/js/{name}.js?v={_v}"
    for name in (
        "ua_desk",
        "ua_ui",
        "ua_tree_sidebar",
        "ua_list",
        "ua_form_toolbar",
        "ua_form",
        "ua_report",
        "ua_report_more",
        "ua_documents",
    )
]

# BeeOne owns the desktop shell. The former ua_shell.js rendered a second,
# competing sidebar on startup and hid the platform's multi-window desktop.
beeone_sections = ["ua_accounting.beeone_shell.sections"]

jinja = {
    "methods": [
        "ua_accounting.accounting.utils.uk_money",  # Ukrainian-specific: money formatting
        "ua_accounting.accounting.utils.uk_date",  # Ukrainian-specific: date formatting
        "ua_accounting.accounting.utils.money_in_words",  # amount_in_words hook handler
        "ua_accounting.accounting.utils.org_info",  # Ukrainian-specific: organization details
        "ua_accounting.accounting.utils.party_info",  # Ukrainian-specific: counterparty details
        "ua_accounting.accounting.utils.bank_info",  # Ukrainian-specific: bank account details
        "ua_accounting.accounting.utils.uktzed",  # Ukrainian-specific: УКТЗЕД code
        "ua_accounting.accounting.utils.person_name",  # Ukrainian-specific: person name from UA Person
    ]
    # title_of, amount_in_words come from core
}

scheduler_events = {
    # rates of the NBU (the job does nothing when the setting «Завантажувати курси НБУ щодня» is off)
    "daily": ["ua_accounting.exchange.nbu.scheduled_load", "ua_accounting.api.calendar.send_reminders"],
}

# handlers of the exchange framework of the core; the rules are seeded by setup.seed.setup_exchange
beeone_exchange_handlers = {
    "nbu_rates": "ua_accounting.exchange.nbu.rule_load_rates",
    "banks": "ua_accounting.exchange.nbu.rule_load_banks",
}

beeone_exchange_logged = ["ua_accounting.exchange.common.mirror_log"]

before_install = "ua_accounting.install.before_install"
after_install = "ua_accounting.install.after_install"
before_migrate = "ua_accounting.install.before_migrate"
after_migrate = "ua_accounting.install.after_migrate"

# the link search must not show hash names
override_whitelisted_methods = {
    "frappe.desk.search.search_link": "ua_accounting.search.search_link",
    "frappe.utils.print_format.download_multi_pdf": "frappe.beeone.print.download_multi_pdf",  # beeone: core batch print
}

from ua_accounting.administration import QUERY_DOCTYPES

permission_query_conditions = {
    doctype: f"ua_accounting.administration.query_{doctype.lower().replace(' ', '_')}"
    for doctype in QUERY_DOCTYPES
}
has_permission = {doctype: "ua_accounting.administration.has_permission" for doctype in QUERY_DOCTYPES}

permission_query_conditions["UA Report Variant"] = "ua_accounting.ua_documents.doctype.ua_report_variant.ua_report_variant.permission_query"
has_permission["UA Report Variant"] = "ua_accounting.ua_documents.doctype.ua_report_variant.ua_report_variant.has_permission"

doc_events = {
    "*": {
        "validate": "ua_accounting.administration.check_access",
        "before_submit": "ua_accounting.administration.check_period",
        "before_cancel": ["ua_accounting.administration.check_period", "ua_accounting.accounting.month_closing.guard_cancel"],
        "on_trash": "ua_accounting.administration.check_period",
        "before_update_after_submit": "ua_accounting.administration.check_access",
        "on_submit": ["ua_accounting.accounting.stock.recalc_later"],
        "on_cancel": ["ua_accounting.accounting.stock.recalc_later"],
    }
}

# beeone change log: the accounting tracks UA documents and copies entries to UA Change Log
beeone_change_log_predicates = ["ua_accounting.audit.is_tracked"]
beeone_change_log_sinks = ["ua_accounting.audit.on_entry"]

permission_query_conditions["UA Change Log"] = "ua_accounting.audit.log_permission_query"
has_permission["UA Change Log"] = "ua_accounting.audit.log_has_permission"
beeone_change_log_context = ["ua_accounting.audit.log_context"]
beeone_change_log_deleted_access = ["ua_accounting.audit.deleted_access"]

# beeone localisation frame: existing functions, same names and error texts
amount_in_words = {"uk": "ua_accounting.accounting.utils.money_in_words"}
beeone_validators = {
    "edrpou": "ua_accounting.ua_catalogs.doctype.ua_counterparty.ua_counterparty.check_edrpou",
    "iban": "ua_accounting.exchange.nbu.validate_iban",
}
beeone_lock_date = ["ua_accounting.accounting.ledger.get_lock_date"]

# beeone provider contracts: the signature library (EUSign) and the receipt service format stay in this app
beeone_signature_providers = {"iit_eusign": "ua_accounting.accounting.signature_provider.EUSignSignature"}
beeone_receipt_importers = {"checkbox": "ua_accounting.integrations.prro.CheckboxImporter"}

# beeone: "Create on basis" commands (core registry frappe.beeone.basis); each method returns an unsaved document
basis_map = [
    {"source": "UA Customer Order", "target": "UA Sales Invoice", "label": "Реалізація товарів та послуг", "method": "ua_accounting.ua_documents.doctype.ua_customer_order.ua_customer_order.make_sales_invoice", "submit_first": True},
    {"source": "UA Supplier Order", "target": "UA Purchase Receipt", "label": "Надходження товарів та послуг", "method": "ua_accounting.ua_documents.doctype.ua_supplier_order.ua_supplier_order.make_purchase_receipt", "submit_first": True},
    {"source": "UA Sales Invoice", "target": "UA Cash Receipt", "label": "Надходження коштів", "method": "ua_accounting.ua_documents.doctype.ua_sales_invoice.ua_sales_invoice.make_cash_receipt", "submit_first": True},
    {"source": "UA Sales Invoice", "target": "UA Tax Invoice", "label": "Податкова накладна", "method": "ua_accounting.api.tax_invoice.make_from_sale", "submit_first": True},
    {"source": "UA Purchase Receipt", "target": "UA Cash Payment", "label": "Витрата коштів", "method": "ua_accounting.ua_documents.doctype.ua_purchase_receipt.ua_purchase_receipt.make_cash_payment", "submit_first": True},
    {"source": "UA Purchase Receipt", "target": "UA Tax Invoice", "label": "Податкова накладна (отримана)", "method": "ua_accounting.api.tax_invoice.make_from_receipt", "submit_first": True},
    {"source": "UA Cash Receipt", "target": "UA Tax Invoice", "label": "Податкова накладна (аванс)", "method": "ua_accounting.api.tax_invoice.make_from_cash_receipt", "submit_first": True},
    {"source": "UA Cash Payment", "target": "UA Tax Invoice", "label": "Податкова накладна (аванс)", "method": "ua_accounting.api.tax_invoice.make_from_cash_payment", "submit_first": True},
    {"source": "UA Tax Invoice", "target": "UA Tax Adjustment", "label": "Розрахунок коригування", "method": "ua_accounting.api.tax_adjustment.make_adjustment", "submit_first": True},
]

# beeone: subordination tree (T-538); documents supporting the structure of subordination
beeone_documents = [
    "UA Sales Invoice",
    "UA Purchase Receipt",
    "UA Customer Order",
    "UA Supplier Order",
    "UA Cash Receipt",
    "UA Cash Payment",
    "UA Journal Operation",
]
