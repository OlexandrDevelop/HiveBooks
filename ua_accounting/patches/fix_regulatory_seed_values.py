"""Fix seed values of T-458 on sites that already ran the first seed patches. Idempotent.

- add the 2023 rows of the living minimum, ПСП and its limit (payroll for 2023 needs them);
- change the schema id of the seeded single-tax form rows to the one the exporter always used
  (F01033 / J01035). Only the exact old seeded value is changed, so user edits stay.
"""

import frappe

OLD_SCHEMA = {
    ("EP3_FOP", "F0103309 ver. 9"): "F01033 v.9",
    ("EP3_LEGAL", "J0103509 ver. 9"): "J01035 v.9",
}


def execute():
    from ua_accounting.patches import seed_regulatory_parameters

    seed_regulatory_parameters.execute()
    for (code, old), new in OLD_SCHEMA.items():
        for name in frappe.get_all("UA Report Form Version", filters={"form_code": code, "schema_version": old},
                                   pluck="name"):
            frappe.db.set_value("UA Report Form Version", name, "schema_version", new)
