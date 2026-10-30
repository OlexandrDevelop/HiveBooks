import frappe

__version__ = "0.0.1"

# Fail-fast check for beeone core
if not hasattr(frappe, "beeone_version"):
    raise RuntimeError(
        "ua_accounting requires beeone core (frappe.beeone_version). Pure upstream Frappe is not supported."
    )

