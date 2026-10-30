"""HiveBooks navigation supplied to the country-neutral BeeOne desktop shell."""

import frappe


def sections(user=None):
    """Return the accounting catalog for BeeOne's multi-window desktop."""
    user = user or frappe.session.user
    if user == "Guest":
        return []

    def cmd(target, label, column="docs", kind="doctype"):
        return {"column": column, "type": kind, "target": target, "label": label}

    groups = [
        {
            "id": "home",
            "label": "Головне",
            "description": "Робочий стіл HiveBooks",
            "icon": "home",
            "commands": [cmd("ua-home", "Робочий стіл", "docs", "page")],
        },
        {
            "id": "purchases",
            "label": "Покупки",
            "description": "Закупівлі та постачальники",
            "icon": "cart",
            "commands": [
                cmd("UA Purchase Receipt", "Надходження товарів і послуг"),
                cmd("UA Supplier Order", "Замовлення постачальнику"),
                cmd("UA Counterparty", "Контрагенти", "refs"),
                cmd("UA Counterparty Contract", "Договори", "refs"),
                cmd("UA Item", "Номенклатура", "refs"),
                cmd("UA Warehouse", "Склади", "refs"),
            ],
        },
        {
            "id": "sales",
            "label": "Продажі",
            "description": "Реалізація та покупці",
            "icon": "trending",
            "commands": [
                cmd("UA Sales Invoice", "Реалізація товарів і послуг"),
                cmd("UA Customer Order", "Замовлення покупця"),
                cmd("UA Counterparty", "Контрагенти", "refs"),
                cmd("UA Counterparty Contract", "Договори", "refs"),
                cmd("UA Item", "Номенклатура", "refs"),
            ],
        },
        {
            "id": "stock",
            "label": "Склад",
            "description": "Залишки та рух товарів",
            "icon": "package",
            "commands": [
                cmd("UA Stock Transfer", "Переміщення товарів"),
                cmd("UA Stock Inventory", "Інвентаризація"),
                cmd("UA Stock Writeoff", "Списання товарів"),
                cmd("UA Stock Surplus", "Оприбуткування надлишків"),
                cmd("UA Item", "Номенклатура", "refs"),
                cmd("UA Warehouse", "Склади", "refs"),
                cmd("UA UOM", "Одиниці виміру", "refs"),
            ],
        },
        {
            "id": "bank",
            "label": "Банк і каса",
            "description": "Грошові кошти та платежі",
            "icon": "landmark",
            "commands": [
                cmd("UA Cash Receipt", "Надходження коштів"),
                cmd("UA Cash Payment", "Витрата коштів"),
                cmd("UA Payment Order", "Платіжні доручення"),
                cmd("UA Bank Statement", "Банківські виписки"),
                cmd("UA Bank Account", "Банківські рахунки", "refs"),
                cmd("UA Cash Desk", "Каси", "refs"),
                cmd("UA Bank", "Банки", "refs"),
                cmd("UA Cash Flow Item", "Статті руху коштів", "refs"),
            ],
        },
        {
            "id": "reports",
            "label": "Звіти",
            "description": "Бухгалтерські та податкові звіти",
            "icon": "chart",
            "commands": [
                cmd("UA Account", "План рахунків", "refs"),
                cmd("UA Accounting Entry", "Проводки"),
                cmd("ua-report-builder", "Універсальний звіт", "reps", "page"),
                cmd("ua-tax-invoice-register", "Реєстр податкових накладних", "reps", "page"),
                cmd("ua-month-closing", "Закриття місяця", "reps", "page"),
                cmd("UA Report Variant", "Варіанти звітів", "refs"),
            ],
        },
        {
            "id": "directories",
            "label": "Довідники",
            "description": "Нормативно-довідкова інформація",
            "icon": "book",
            "commands": [
                cmd("UA Organization", "Організації", "refs"),
                cmd("UA Counterparty", "Контрагенти", "refs"),
                cmd("UA Item", "Номенклатура", "refs"),
                cmd("UA Currency", "Валюти", "refs"),
                cmd("UA Department", "Підрозділи", "refs"),
                cmd("UA Employee", "Працівники", "refs"),
                cmd("UA Bank", "Банки", "refs"),
                cmd("UA UKTZED", "УКТЗЕД", "refs"),
                cmd("UA KVED", "КВЕД", "refs"),
            ],
        },
        {
            "id": "administration",
            "label": "Адміністрування",
            "description": "Налаштування та службові функції",
            "icon": "sliders",
            "commands": [
                cmd("UA Accounting Settings", "Налаштування обліку", "svc"),
                cmd("UA Accounting Policy", "Облікова політика", "svc"),
                cmd("UA Subconto Type", "Типи субконто", "refs"),
                cmd("User", "Користувачі", "svc"),
                cmd("Role", "Ролі", "svc"),
                cmd("System Settings", "Системні налаштування", "svc"),
            ],
        },
    ]
    return [{**group, "order": i * 10, "create": []} for i, group in enumerate(groups)]
