"""Seed the dated legal parameters (UA Regulatory Parameter) with their real history. Idempotent."""

import frappe

# code -> (unit, legal basis, [(effective_from, value)])
PARAMETERS = {
    "MIN_WAGE": ("UAH", "Закон про Державний бюджет України (мінімальна зарплата)",
                 [("2023-01-01", 6700), ("2024-01-01", 7100), ("2025-01-01", 8000), ("2026-01-01", 8647)]),
    "LIVING_MINIMUM": ("UAH", "Закон про Державний бюджет України (прожитковий мінімум для працездатних)",
                       [("2023-01-01", 2684), ("2024-01-01", 3028), ("2025-01-01", 3028),
                        ("2026-01-01", 3328)]),
    "PSP": ("UAH", "ПКУ 169.1.1 (50 % прожиткового мінімуму на 1 січня)",
            [("2023-01-01", 1342), ("2024-01-01", 1514), ("2025-01-01", 1514), ("2026-01-01", 1664)]),
    "PSP_LIMIT": ("UAH", "ПКУ 169.4.1: 1,4 прожиткового мінімуму на 1 січня, округлено до 10 грн",
                  [("2023-01-01", 3758), ("2024-01-01", 4240), ("2025-01-01", 4240), ("2026-01-01", 4660)]),
    "PDFO_RATE": ("%", "ПКУ 167.1", [("2015-01-01", 18)]),
    "VZ_RATE": ("%", "ПКУ 161 прим.1", [("2015-01-01", 1.5), ("2024-12-01", 5)]),
    "VZ_FOP_G3_RATE": ("%", "ПКУ 161 прим.1: ФОП на єдиному податку 3 групи", [("2025-01-01", 1)]),
    "VZ_FOP_FIXED_PCT": ("%", "ПКУ 161 прим.1: ФОП 1, 2 груп, % мінімальної зарплати за місяць", [("2025-01-01", 10)]),
    "ESV_RATE": ("%", "ЗУ 2464-VI ст. 8", [("2016-01-01", 22)]),
    "ESV_MAX_BASE_MULT": ("x мін. зарплата", "ЗУ 2464-VI ст. 7", [("2016-01-01", 15)]),
    "EP_LIMIT_G1_MULT": ("x мін. зарплата", "ПКУ 291.4", [("2017-01-01", 167)]),
    "EP_LIMIT_G2_MULT": ("x мін. зарплата", "ПКУ 291.4", [("2017-01-01", 834)]),
    "EP_LIMIT_G3_MULT": ("x мін. зарплата", "ПКУ 291.4", [("2017-01-01", 1167)]),
    "VAT_REG_LIMIT": ("UAH", "ПКУ 181.1", [("2020-01-01", 1000000)]),
}


def execute():
    for code, (unit, basis, rows) in PARAMETERS.items():
        for date, value in rows:
            if frappe.db.exists("UA Regulatory Parameter", {"parameter_code": code, "effective_from": date}):
                continue
            frappe.get_doc({
                "doctype": "UA Regulatory Parameter", "parameter_code": code, "effective_from": date,
                "value": value, "unit": unit, "legal_basis": basis,
            }).insert(ignore_permissions=True)
