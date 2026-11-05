"""Hooks of ua_accounting for the beeone desktop shell: sections and widgets.

The commands come from the former ua_shell.js (T-539). The core filters them by read
permission, merges the sections of other apps and draws the desk.
"""

import frappe

# The six roles of the accounting (setup/seed.py ROLES) and the system manager.
ACCOUNTING_ROLES = (
    "UA Accountant",
    "UA Accounting Manager",
    "UA Chief Accountant",
    "UA Cashier",
    "UA HR Officer",
    "UA Administrator",
    "System Manager",
)

# Role desks (core hook `beeone_role_desks`): role -> section ids ("*" = all sections the
# user may read) and the tiles of the home page. A tile is ("section", id) or ("command", key).
# An empty tile list gives one tile per visible section. The core cuts commands by permission.
ROLE_DESKS = {
    "UA Accountant": ("*", ()),
    "UA Accounting Manager": ("*", ()),
    "UA Chief Accountant": ("*", ()),
    "System Manager": ("*", ()),
    "UA Cashier": (
        ("bank", "settlements", "reports", "catalogs"),
        (
            ("command", "cash_receipt"),
            ("command", "cash_payment"),
            ("command", "cash_book"),
            ("section", "bank"),
            ("section", "settlements"),
            ("section", "reports"),
            ("section", "catalogs"),
        ),
    ),
    "UA HR Officer": (
        ("payroll", "reports", "catalogs"),
        (
            ("command", "hiring"),
            ("command", "timesheet"),
            ("command", "payroll"),
            ("section", "payroll"),
            ("section", "reports"),
            ("section", "catalogs"),
        ),
    ),
    "UA Administrator": (
        ("admin", "reports", "catalogs"),
        (
            ("command", "users"),
            ("command", "accounting_settings"),
            ("section", "admin"),
            ("section", "reports"),
            ("section", "catalogs"),
        ),
    ),
}

COMMANDS = {
    'customer_order': ('Замовлення покупця', 'doctype', 'UA Customer Order'),
    'invoice': ('Інвойси', 'doctype', 'UA Payment Invoice'),
    'supplier_order': ('Замовлення постачальнику', 'doctype', 'UA Supplier Order'),
    'purchase_receipt': ('Надходження товарів та послуг', 'doctype', 'UA Purchase Receipt'),
    'cash_receipt': ('Надходження коштів', 'doctype', 'UA Cash Receipt'),
    'cash_payment': ('Витрата коштів', 'doctype', 'UA Cash Payment'),
    'operation': ('Операції (бухгалтерські)', 'doctype', 'UA Journal Operation'),
    'tax_invoice': ('Податкові накладні', 'doctype', 'UA Tax Invoice'),
    'tax_adjustment': ('Розрахунки коригування', 'doctype', 'UA Tax Adjustment'),
    'vat_allocation': ('Розподіл ПДВ', 'doctype', 'UA VAT Allocation'),
    'vat_return': ('Декларації з ПДВ', 'doctype', 'UA VAT Return'),
    'vat_setting': ('Налаштування ПДВ (ліміт реєстрації)', 'doctype', 'UA VAT Setting'),
    'tax_differences': ('Розрахунок податкових різниць', 'page', 'ua-tax-differences'),
    'regulated_reports': ('Регламентована звітність', 'page', 'ua-regulated-reports'),
    'regulated_report': ('Регламентовані звіти', 'doctype', 'UA Regulated Report'),
    'statistical_report': ('Статистична звітність', 'doctype', 'UA Statistical Report'),
    'signed_document': ('Архів поданих документів', 'doctype', 'UA Signed Document'),
    'e_reporting_setting': ('Налаштування електронної звітності', 'doctype', 'UA E-Reporting Setting'),
    'tax_difference_item': ('Статті податкових різниць', 'doctype', 'UA Tax Difference Item'),
    'tax_register': ('Реєстр податкових накладних', 'page', 'ua-tax-invoice-register'),
    'month_closing': ('Закриття місяця', 'page', 'ua-month-closing'),
    'report_builder': ('Універсальний звіт', 'page', 'ua-report-builder'),
    'employee': ('Співробітники', 'doctype', 'UA Employee'),
    'position': ('Посади', 'doctype', 'UA Position'),
    'work_schedule': ('Графіки роботи', 'doctype', 'UA Work Schedule'),
    'hiring': ('Прийом на роботу', 'doctype', 'UA Hiring'),
    'staff_transfer': ('Кадрове переміщення', 'doctype', 'UA Staff Transfer'),
    'dismissal': ('Звільнення', 'doctype', 'UA Dismissal'),
    'timesheet': ('Табель', 'doctype', 'UA Timesheet'),
    'payroll': ('Нарахування зарплати', 'doctype', 'UA Payroll'),
    'salary_payment': ('Виплата зарплати', 'doctype', 'UA Salary Payment'),
    'payslip': ('Розрахунковий листок', 'report', 'UA Payslip'),
    'payroll_accruals': ('Звіт по нарахуваннях', 'report', 'UA Payroll Accruals Report'),
    'appendix_4df': ('Додаток 4ДФ', 'report', 'UA Appendix 4DF'),
    'bad_debt_write_off': ('Списання безнадійної заборгованості', 'doctype', 'UA Bad Debt Write-off'),
    'vacation_inventory': ('Інвентаризація резерву відпусток', 'doctype', 'UA Vacation Reserve Inventory'),
    'provision_accrual': ('Нарахування резервів', 'doctype', 'UA Provision Accrual'),
    'provision_settings': ('Налаштування резервів', 'doctype', 'UA Provision Settings'),
    'payment_assistant': ('Помічник оплати', 'page', 'ua-payment-assistant'),
    'vat_assistant': ('Помічник ПДВ', 'page', 'ua-vat-assistant'),
    'manager_monitor': ('Монітор керівника', 'page', 'ua-manager-monitor'),
    'accountant_task': ('Завдання бухгалтера', 'doctype', 'UA Accountant Task'),
    'tax_payment_account': ('Рахунки для сплати податків', 'doctype', 'UA Tax Payment Account'),
    'doubtful_reserve': ('Розрахунок резерву сумнівних боргів', 'page', 'ua-doubtful-debts-reserve'),
    'data_exchange': ('Обмін даними', 'page', 'ua-data-exchange'),
    'exchange_settings': ('Налаштування обміну', 'single', 'UA Exchange Settings'),
    'exchange_log': ('Журнал обміну', 'doctype', 'UA Exchange Log'),
    'uktzed': ('УКТЗЕД', 'doctype', 'UA UKTZED'),
    'kved': ('КВЕД', 'doctype', 'UA KVED'),
    'dkpp': ('ДКПП', 'doctype', 'UA DKPP'),
    'counterparty': ('Контрагенти', 'doctype', 'UA Counterparty'),
    'contract': ('Договори контрагентів', 'doctype', 'UA Counterparty Contract'),
    'item': ('Номенклатура', 'doctype', 'UA Item'),
    'uom': ('Одиниці виміру', 'doctype', 'UA UOM'),
    'warehouse': ('Склади', 'doctype', 'UA Warehouse'),
    'bank': ('Банки', 'doctype', 'UA Bank'),
    'bank_account': ('Банківські рахунки', 'doctype', 'UA Bank Account'),
    'cash_desk': ('Каси', 'doctype', 'UA Cash Desk'),
    'payment_order': ('Платіжні доручення', 'doctype', 'UA Payment Order'),
    'bank_statement': ('Банківські виписки', 'doctype', 'UA Bank Statement'),
    'advance_report': ('Авансові звіти', 'doctype', 'UA Advance Report'),
    'cash_disbursement': ('Видаткові відомості', 'doctype', 'UA Cash Disbursement'),
    'currency_exchange': ('Купівля/продаж валюти', 'doctype', 'UA Currency Exchange'),
    'dividend_accrual': ('Нарахування дивідендів', 'doctype', 'UA Dividend Accrual'),
    'tax_payment': ('Сплата податків', 'doctype', 'UA Tax Payment'),
    'loan': ('Кредити і позики', 'doctype', 'UA Loan'),
    'loan_drawdown': ('Отримання кредиту / позики', 'doctype', 'UA Loan Drawdown'),
    'loan_interest': ('Нарахування відсотків за кредитами', 'doctype', 'UA Loan Interest Accrual'),
    'loan_repayment': ('Погашення кредиту / позики', 'doctype', 'UA Loan Repayment'),
    'currency_revaluation': ('Переоцінка валютних розрахунків', 'doctype', 'UA Currency Revaluation'),
    'opening_balances': ('Введення початкових залишків', 'doctype', 'UA Opening Balances'),
    'accountable_report': ('Розрахунки з підзвітними особами', 'report', 'UA Accountable Persons Report'),
    'founder_report': ('Розрахунки із засновниками', 'report', 'UA Founder Settlements Report'),
    'budget_report': ('Розрахунки з бюджетом за податками', 'report', 'UA Budget Settlements Report'),
    'loans_report': ('Кредити і позики (звіт)', 'report', 'UA Loans Report'),
    'stock_transfer': ('Переміщення товарів', 'doctype', 'UA Stock Transfer'),
    'stock_writeoff': ('Списання товарів', 'doctype', 'UA Stock Writeoff'),
    'stock_surplus': ('Оприбуткування товарів', 'doctype', 'UA Stock Surplus'),
    'stock_inventory': ('Інвентаризація товарів', 'doctype', 'UA Stock Inventory'),
    'stock_assembly': ('Комплектація/розкомплектація', 'doctype', 'UA Stock Assembly'),
    'low_value_issue': ('Передача матеріалів в експлуатацію', 'doctype', 'UA Low Value Issue'),
    'special_wear_issue': ('Передача в експлуатацію спецодягу', 'doctype', 'UA Special Wear Issue'),
    'special_wear_monthly': ('Списання вартості спецодягу за місяць', 'doctype', 'UA Special Wear Monthly Writeoff'),
    'special_wear_return': ('Повернення спецодягу на склад', 'doctype', 'UA Special Wear Return'),
    'special_wear_writeoff': ('Списання спецодягу з експлуатації', 'doctype', 'UA Special Wear Writeoff'),
    'special_wear_in_use': ('Відомість спецодягу в експлуатації', 'report', 'UA Special Wear In Use Report'),
    'requirement_invoice': ('Вимога-накладна', 'doctype', 'UA Requirement Invoice'),
    'commission_receipt': ('Надходження товарів на комісію', 'doctype', 'UA Commission Receipt'),
    'commission_transfer': ('Передача на комісію', 'doctype', 'UA Commission Transfer'),
    'commission_agent_report': ('Звіт комісіонера', 'doctype', 'UA Commission Agent Report'),
    'principal_report': ('Звіт комітенту', 'doctype', 'UA Principal Report'),
    'commission_return': ('Повернення комітенту', 'doctype', 'UA Commission Return'),
    'tolling_transfer': ('Передача сировини в переробку', 'doctype', 'UA Tolling Transfer'),
    'tolling_receipt': ('Отримання з переробки', 'doctype', 'UA Tolling Receipt'),
    'tolling_intake': ('Сировина, прийнята в переробку', 'doctype', 'UA Tolling Intake'),
    'tolling_output': ('Передача готової продукції замовнику', 'doctype', 'UA Tolling Output'),
    'packaging_return': ('Повернення тари', 'doctype', 'UA Packaging Return'),
    'packaging_balance': ('Розрахунки за тару', 'report', 'UA Packaging Balance'),
    'production_report': ('Звіт виробництва за зміну', 'doctype', 'UA Production Report'),
    'production_closing': ('Закриття місяця (виробництво)', 'doctype', 'UA Production Month Closing'),
    'own_work_act': ('Акт про виконання робіт власного виробництва', 'doctype', 'UA Own Work Act'),
    'item_specification': ('Специфікації номенклатури', 'doctype', 'UA Item Specification'),
    'planned_price': ('Планові ціни', 'doctype', 'UA Planned Price'),
    'production_cost': ('Звіт про собівартість випуску', 'report', 'UA Production Cost Report'),
    'stock_balance': ('Залишки товарів', 'page', 'ua-stock-balance'),
    'stock_statement': ('Відомість по товарах на складах', 'page', 'ua-stock-statement'),
    'cash_book': ('Касова книга', 'page', 'ua-cash-book'),
    'bank_journal': ('Журнал банківських документів', 'report', 'UA Bank Journal'),
    'currency': ('Валюти', 'doctype', 'UA Currency'),
    'cash_flow_item': ('Статті руху грошових коштів', 'doctype', 'UA Cash Flow Item'),
    'expense_item': ('Статті витрат', 'doctype', 'UA Expense Item'),
    'organization': ('Організації', 'doctype', 'UA Organization'),
    'accounting_policy': ('Облікова політика', 'doctype', 'UA Accounting Policy'),
    'accounting_settings': ('Налаштування обліку', 'single', 'UA Accounting Settings'),
    'numbering': ('Налаштування нумерації', 'doctype', 'UA Numbering Setting'),
    'change_log': ('Журнал реєстрації змін', 'doctype', 'UA Change Log'),
    'department': ('Підрозділи', 'doctype', 'UA Department'),
    'person': ('Фізичні особи', 'doctype', 'UA Person'),
    'fixed_asset': ('Основні засоби', 'doctype', 'UA Fixed Asset'),
    'intangible': ('Нематеріальні активи', 'doctype', 'UA Intangible Asset'),
    'low_value': ('Малоцінні активи (МНМА)', 'doctype', 'UA Low Value Asset'),
    'asset_acceptance': ('Прийняття до обліку ОЗ / НМА', 'doctype', 'UA Asset Acceptance'),
    'asset_depreciation': ('Нарахування амортизації', 'doctype', 'UA Asset Depreciation'),
    'asset_modernization': ('Модернізація ОЗ', 'doctype', 'UA Asset Modernization'),
    'asset_transfer': ('Переміщення ОЗ', 'doctype', 'UA Asset Transfer'),
    'asset_writeoff': ('Списання ОЗ', 'doctype', 'UA Asset Writeoff'),
    'asset_sale': ('Продаж ОЗ', 'doctype', 'UA Asset Sale'),
    'asset_revaluation': ('Переоцінка ОЗ', 'doctype', 'UA Asset Revaluation'),
    'fixed_asset_card': ('Інвентарна картка обліку основних засобів (ОЗ-6)', 'report', 'UA Fixed Asset Card'),
    'lease_agreement': ('Договори оренди', 'doctype', 'UA Lease Agreement'),
    'leased_asset_receipt': ('Отримання майна в оренду', 'doctype', 'UA Leased Asset Receipt'),
    'leased_asset_return': ('Повернення майна з оренди', 'doctype', 'UA Leased Asset Return'),
    'rent_accrual': ('Нарахування орендної плати', 'doctype', 'UA Rent Accrual'),
    'finance_lease_receipt': ('Отримання майна у фінансову оренду', 'doctype', 'UA Finance Lease Receipt'),
    'lease_interest_accrual': ('Нарахування відсотків за фінансовою орендою', 'doctype', 'UA Lease Interest Accrual'),
    'lease_payment': ('Лізинговий платіж', 'doctype', 'UA Lease Payment'),
    'lease_obligations': ("Зобов'язання за орендою", 'report', 'UA Lease Obligations Report'),
    'depreciation_statement': ('Відомість амортизації', 'report', 'UA Depreciation Statement'),
    'account': ('План рахунків', 'tree', 'UA Account'),
    'subconto': ('Види субконто', 'doctype', 'UA Subconto Type'),
    'vat_rate': ('Ставки ПДВ', 'doctype', 'UA VAT Rate'),
    'tax_type': ('Види податків', 'doctype', 'UA Tax Type'),
    'osv': ('Оборотно-сальдова відомість', 'page', 'ua-osv'),
    'osv_account': ('ОСВ по рахунку', 'page', 'ua-osv-account'),
    'account_card': ('Картка рахунку', 'page', 'ua-account-card'),
    'subconto_analysis': ('Аналіз субконто', 'page', 'ua-subconto-analysis'),
    'osv_subconto': ('ОСВ по субконто', 'page', 'ua-osv-subconto'),
    'account_turnover': ('Обороти рахунку', 'page', 'ua-account-turnover'),
    'account_analysis': ('Аналіз рахунку', 'page', 'ua-account-analysis'),
    'general_ledger': ('Головна книга', 'page', 'ua-general-ledger'),
    'journal_order': ('Журнал-ордер', 'page', 'ua-journal-order'),
    'chess_sheet': ('Шахова відомість', 'page', 'ua-chess-sheet'),
    'entries_report': ('Звіт по проводках', 'page', 'ua-entries-report'),
    'subconto_card': ('Картка субконто', 'page', 'ua-subconto-card'),
    'accounting_check': ('Експрес-перевірка ведення обліку', 'page', 'ua-accounting-check'),
    'entries': ('Журнал проводок', 'doctype', 'UA Accounting Entry'),
    'turnover': ('Підсумки по рахунках', 'route', 'ua-account-turnover/view/list'),
    'vat_liability': ('ПДВ нараховане', 'doctype', 'UA VAT Liability Entry'),
    'vat_credit': ('ПДВ кредит', 'doctype', 'UA VAT Credit Entry'),
    'users': ('Користувачі', 'doctype', 'User'),
    'roles': ('Ролі', 'doctype', 'Role'),
    'system_settings': ('Налаштування системи', 'single', 'System Settings'),
}

# id, label, sub-title, icon, quick-create commands, then columns docs/refs/reps/svc
SECTIONS = (
    (
        'buy', 'Покупки', 'Закупівлі та постачальники', 'cart',
        ['purchase_receipt', 'supplier_order'],
        {
            'docs': ['purchase_receipt', 'supplier_order', 'tax_invoice'],
            'refs': ['counterparty', 'contract', 'item', 'warehouse'],
            'reps': ['osv_account', 'account_card'],
            'svc': ['vat_credit'],
        },
    ),
    (
        'sell', 'Продажі', 'Інвойси та покупці', 'trending',
        ['invoice', 'customer_order'],
        {
            'docs': ['invoice', 'customer_order', 'tax_invoice', 'tax_adjustment'],
            'refs': ['counterparty', 'contract', 'item'],
            'reps': ['osv_account', 'account_card'],
            'svc': ['vat_liability'],
        },
    ),
    (
        'stock', 'Склад', 'Рух і залишки товарів', 'package',
        ['purchase_receipt'],
        {
            'docs': ['purchase_receipt', 'stock_transfer', 'stock_writeoff', 'stock_surplus', 'stock_inventory', 'stock_assembly', 'low_value_issue', 'requirement_invoice', 'commission_receipt', 'commission_transfer', 'commission_agent_report', 'principal_report', 'commission_return', 'tolling_transfer', 'tolling_receipt', 'tolling_intake', 'tolling_output', 'packaging_return', 'special_wear_issue', 'special_wear_monthly', 'special_wear_return', 'special_wear_writeoff'],
            'refs': ['warehouse', 'item', 'uom'],
            'reps': ['stock_balance', 'stock_statement', 'packaging_balance', 'special_wear_in_use', 'osv_account', 'account_card'],
            'svc': [],
        },
    ),
    (
        'production', 'Виробництво', 'Випуск, планова та фактична собівартість', 'package',
        ['production_report'],
        {
            'docs': ['production_report', 'production_closing', 'own_work_act'],
            'refs': ['item_specification', 'planned_price', 'item', 'department', 'expense_item'],
            'reps': ['production_cost', 'osv_account', 'account_card'],
            'svc': [],
        },
    ),
    (
        'bank', 'Банк і каса', 'Надходження і витрата коштів', 'landmark',
        ['cash_receipt', 'cash_payment'],
        {
            'docs': ['cash_receipt', 'cash_payment', 'payment_order', 'bank_statement', 'advance_report', 'cash_disbursement', 'currency_exchange'],
            'refs': ['bank_account', 'bank', 'cash_desk', 'currency', 'cash_flow_item'],
            'reps': ['cash_book', 'bank_journal', 'osv_account', 'account_card'],
            'svc': ['payment_assistant'],
        },
    ),
    (
        'settlements', 'Розрахунки', 'Підзвітні особи, засновники, бюджет, кредити', 'landmark',
        ['opening_balances'],
        {
            'docs': ['dividend_accrual', 'tax_payment', 'loan_drawdown', 'loan_interest', 'loan_repayment', 'currency_revaluation', 'opening_balances'],
            'refs': ['loan', 'person'],
            'reps': ['accountable_report', 'founder_report', 'budget_report', 'loans_report', 'osv_account'],
            'svc': [],
        },
    ),
    (
        'payroll', 'Зарплата та кадри', 'Співробітники, нарахування, виплата', 'user',
        ['payroll', 'salary_payment'],
        {
            'docs': ['hiring', 'staff_transfer', 'dismissal', 'timesheet', 'payroll', 'salary_payment'],
            'refs': ['employee', 'position', 'work_schedule', 'department', 'person'],
            'reps': ['payslip', 'payroll_accruals', 'appendix_4df', 'osv_account'],
            'svc': [],
        },
    ),
    (
        'assets', 'ОС і НМА', 'Основні засоби, нематеріальні активи', 'building',
        [],
        {
            'docs': ['asset_acceptance', 'asset_depreciation', 'asset_modernization', 'asset_transfer', 'asset_writeoff', 'asset_sale', 'asset_revaluation', 'leased_asset_receipt', 'leased_asset_return', 'rent_accrual', 'finance_lease_receipt', 'lease_interest_accrual', 'lease_payment'],
            'refs': ['fixed_asset', 'intangible', 'low_value', 'lease_agreement'],
            'reps': ['fixed_asset_card', 'depreciation_statement', 'lease_obligations', 'osv_account'],
            'svc': [],
        },
    ),
    (
        'reports', 'Звіти', 'Стандартні звіти та регістри', 'chart',
        ['osv'],
        {
            'docs': ['operation', 'tax_invoice', 'tax_adjustment', 'vat_allocation', 'vat_return', 'tax_difference_item', 'month_closing', 'provision_accrual', 'bad_debt_write_off', 'vacation_inventory', 'regulated_report', 'statistical_report', 'signed_document', 'e_reporting_setting'],
            'refs': ['account', 'subconto'],
            'reps': ['osv', 'osv_account', 'account_card', 'subconto_analysis', 'osv_subconto', 'account_turnover', 'account_analysis', 'general_ledger', 'journal_order', 'chess_sheet', 'entries_report', 'subconto_card', 'accounting_check', 'tax_register', 'tax_differences', 'doubtful_reserve', 'regulated_reports', 'report_builder', 'manager_monitor'],
            'svc': ['entries', 'turnover', 'vat_liability', 'vat_credit', 'vat_setting', 'provision_settings', 'vat_assistant', 'accountant_task', 'tax_payment_account'],
        },
    ),
    (
        'catalogs', 'Довідники', 'Нормативно-довідкова інформація', 'book',
        ['item', 'counterparty'],
        {
            'docs': [],
            'refs': ['organization', 'counterparty', 'contract', 'item', 'warehouse', 'uom', 'bank_account', 'bank', 'cash_desk', 'currency', 'cash_flow_item', 'expense_item', 'department', 'person', 'uktzed', 'kved', 'dkpp'],
            'reps': [],
            'svc': [],
        },
    ),
    (
        'admin', 'Адміністрування', 'Налаштування, користувачі, облік', 'sliders',
        [],
        {
            'docs': ['operation'],
            'refs': ['account', 'subconto', 'vat_rate', 'tax_type', 'accounting_policy'],
            'reps': [],
            'svc': ['data_exchange', 'exchange_log', 'exchange_settings', 'users', 'roles', 'accounting_settings', 'numbering', 'change_log', 'system_settings'],
        },
    ),
)


def beeone_sections(user=None):
    roles = set(frappe.get_roles(user or frappe.session.user))
    if not roles & set(ACCOUNTING_ROLES):
        return []
    out = []
    for order, (sid, label, sub, icon, quick, columns) in enumerate(SECTIONS, start=1):
        commands = []
        for column, keys in columns.items():
            for key in keys:
                label_, kind, target = COMMANDS[key]
                commands.append({"column": column, "label": label_, "type": kind, "target": target})
        create = [
            {"doctype": COMMANDS[k][2]} for k in quick if COMMANDS[k][1] == "doctype"
        ]
        out.append(
            {
                "id": sid,
                "label": label,
                "description": sub,
                "icon": icon,
                # The accounting command is first when trade has a section with the same label.
                "order": order,
                "create": create,
                "commands": commands,
            }
        )
    return out


def beeone_role_desks():
    """Hook `beeone_role_desks`: which sections each accounting role sees and its home tiles."""
    out = {}
    for role, (sections, tiles) in ROLE_DESKS.items():
        items = []
        for kind, key in tiles:
            if kind == "section":
                items.append({"section": key})
                continue
            label, ctype, target = COMMANDS[key]
            items.append({"label": label, "type": ctype, "target": target})
        out[role] = {"sections": sections if sections == "*" else list(sections), "tiles": items}
    return out


def beeone_widgets():
    return {
        "sources": [
            {
                "id": "ua_invoice",
                "label": "Інвойси",
                "doctype": "UA Payment Invoice",
                "types": ["beeone.count", "beeone.number", "beeone.recent"],
                "filters": {"docstatus": 1},
                "number": {"field": "total_amount", "date_field": "posting_date", "currency": True},
            },
            {
                "id": "ua_purchase_receipt",
                "label": "Надходження",
                "doctype": "UA Purchase Receipt",
                "types": ["beeone.count", "beeone.number", "beeone.recent"],
                "filters": {"docstatus": 1},
                "number": {"field": "total_amount", "date_field": "posting_date", "currency": True},
            },
            {
                "id": "ua_customer_order",
                "label": "Замовлення покупців",
                "doctype": "UA Customer Order",
                "types": ["beeone.count", "beeone.recent"],
            },
        ],
        "defaults": {
            "System Manager": [
                {"type": "beeone.number", "source": "ua_invoice", "size": "m"},
                {"type": "beeone.count", "source": "ua_customer_order", "size": "s"},
                {"type": "beeone.count", "source": "ua_purchase_receipt", "size": "s"},
                {"type": "beeone.recent", "source": "ua_invoice", "size": "l"},
            ],
            "UA Accountant": [
                {"type": "beeone.number", "source": "ua_invoice", "size": "m"},
                {"type": "beeone.count", "source": "ua_customer_order", "size": "s"},
                {"type": "beeone.recent", "source": "ua_invoice", "size": "l"},
            ],
            "UA Accounting Manager": [
                {"type": "beeone.number", "source": "ua_invoice", "size": "m"},
                {"type": "beeone.count", "source": "ua_customer_order", "size": "s"},
                {"type": "beeone.recent", "source": "ua_invoice", "size": "l"},
            ],
            "UA Chief Accountant": [
                {"type": "beeone.number", "source": "ua_invoice", "size": "m"},
                {"type": "beeone.count", "source": "ua_purchase_receipt", "size": "s"},
                {"type": "beeone.recent", "source": "ua_invoice", "size": "l"},
            ],
        },
    }
