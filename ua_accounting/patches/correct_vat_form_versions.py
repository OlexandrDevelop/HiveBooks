"""Replace the erroneous VAT XML seed rows and add the dated official forms."""

import frappe

from ua_accounting.patches.seed_regulatory_forms import FORMS


WRONG_SEEDS = {
    "VAT_RETURN": "J0200123 v.9",
    "TAX_INVOICE_PN": "J1201015 v.9",
    "ADJUSTMENT_RK": "J1201115 v.9",
}


def execute():
    for code, wrong_schema in WRONG_SEEDS.items():
        # Only remove the exact row created by the old seed; preserve user-maintained rows.
        for row in frappe.get_all("UA Report Form Version", filters={
            "form_code": code, "effective_from": "2023-01-01", "schema_version": wrong_schema,
        }, pluck="name"):
            frappe.delete_doc("UA Report Form Version", row, ignore_permissions=True)
        name, basis, versions = FORMS[code]
        for date, version, schema in versions:
            if frappe.db.exists("UA Report Form Version", {"form_code": code, "effective_from": date}):
                continue
            frappe.get_doc({
                "doctype": "UA Report Form Version", "form_code": code, "form_name": name,
                "version_no": version, "effective_from": date, "schema_version": schema,
                "xsd_file": schema.split()[0] + ".xsd", "legal_basis": basis, "status": "Діє",
            }).insert(ignore_permissions=True)
