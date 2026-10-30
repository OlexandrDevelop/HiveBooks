"""Seed the register of report form versions (UA Report Form Version) and the first release note. Idempotent."""

import frappe

# ДПС XSD registry, checked 2026-10-23:
# https://tax.gov.ua/elektronna-zvitnist/platnikam-podatkiv-pro/informatsiyno-analitichne-za/reestr-elektronnih-form-po/reestr-form/
# https://tax.gov.ua/data/material/000/357/453385/xsd_all.arj
# Effective periods: https://zt.tax.gov.ua/media-ark/news-ark/print-460323.html (J0200123),
# https://dp.tax.gov.ua/media-ark/news-ark/print-706136.html (J0200125),
# https://sumy.tax.gov.ua/media-ark/news-ark/print-836714.html (J0200126).
# code -> (name, legal basis, [(effective_from, version_no, schema_version)])
FORMS = {
    "BALANCE_F1": ("Баланс (Звіт про фінансовий стан), форма 1", "НП(С)БО 1; наказ Мінфіну №433",
                   [("2023-01-01", "7", "J0900107 v.7")]),
    "FIN_RESULT_F2": ("Звіт про фінансові результати, форма 2", "НП(С)БО 1; наказ Мінфіну №433",
                      [("2023-01-01", "7", "J0900207 v.7")]),
    "CASHFLOW_F3": ("Звіт про рух грошових коштів, форма 3", "НП(С)БО 1; наказ Мінфіну №433",
                    [("2023-01-01", "7", "J0900307 v.7")]),
    "BALANCE_F1_M": ("Баланс, форма 1-м", "Наказ Мінфіну №433", [("2023-01-01", "7", "J0901107 v.7")]),
    "FIN_RESULT_F2_M": ("Звіт про фінансові результати, форма 2-м", "Наказ Мінфіну №433",
                        [("2023-01-01", "7", "J0901207 v.7")]),
    "BALANCE_F1_MS": ("Баланс, форма 1-мс", "Наказ Мінфіну №433", [("2023-01-01", "7", "J0902107 v.7")]),
    "FIN_RESULT_F2_MS": ("Звіт про фінансові результати, форма 2-мс", "Наказ Мінфіну №433",
                         [("2023-01-01", "7", "J0902207 v.7")]),
    "VAT_RETURN": ("Декларація з ПДВ", "ПКУ 203; наказ Мінфіну №21, №256, №400", [
        ("2021-04-01", "23", "J0200123 v.23"),
        ("2023-08-01", "25", "J0200125 v.25"),
        ("2024-10-01", "26", "J0200126 v.26"),
    ]),
    "TAX_INVOICE_PN": ("Податкова накладна", "ПКУ 201; наказ Мінфіну №1307, №256, №400", [
        ("2023-08-01", "15", "J1201015 v.15"),
        ("2024-10-01", "16", "J1201016 v.16"),
    ]),
    "ADJUSTMENT_RK": ("Розрахунок коригування", "ПКУ 192; наказ Мінфіну №1307, №256, №400", [
        ("2023-08-01", "15", "J1201215 v.15"),
        ("2024-10-01", "16", "J1201216 v.16"),
    ]),
    "PROFIT_TAX": ("Декларація з податку на прибуток", "ПКУ 46", [("2023-01-01", "29", "J0100129 v.29")]),
    "EP3_FOP": ("Декларація платника єдиного податку (ФОП)", "ПКУ 296", [("2023-01-01", "9", "F01033 v.9")]),
    "EP3_LEGAL": ("Декларація платника єдиного податку (юрособа)", "ПКУ 296",
                  [("2023-01-01", "9", "J01035 v.9")]),
    "ESV": ("Звіт з ЄСВ", "ЗУ 2464-VI", [("2023-01-01", "1", "J0400101 v.1")]),
    "PROFIT_TAX_RI": ("Додаток РІ до декларації з податку на прибуток", "ПКУ 46",
                      [("2023-01-01", "29", "J0111829 v.29")]),
    "PROFIT_TAX_PZ": ("Додаток ПЗ до декларації з податку на прибуток", "ПКУ 46",
                      [("2023-01-01", "29", "J0111329 v.29")]),
}


def execute():
    for code, (name, basis, rows) in FORMS.items():
        for date, version, schema in rows:
            if frappe.db.exists("UA Report Form Version", {"form_code": code, "effective_from": date}):
                continue
            frappe.get_doc({
                "doctype": "UA Report Form Version", "form_code": code, "form_name": name, "version_no": version,
                "effective_from": date, "schema_version": schema,
                "xsd_file": schema.split()[0] + ".xsd", "legal_basis": basis, "status": "Діє",
            }).insert(ignore_permissions=True)
    if not frappe.db.exists("UA Release Note", {"release_version": "1.0.0"}):
        frappe.get_doc({
            "doctype": "UA Release Note", "release_version": "1.0.0", "release_date": "2026-10-23",
            "title": "Нормативні параметри та версії форм звітності", "change_type": "Форма звітності",
            "effective_from": "2023-01-01",
            "description": "Ставки та ліміти (мінімальна зарплата, ПДФО, ВЗ, ЄСВ, ліміти ЄП, ліміт ПДВ) "
                           "та версії форм звітності ведуться датованими записами.",
            "patch_name": "seed_regulatory_forms",
        }).insert(ignore_permissions=True)
