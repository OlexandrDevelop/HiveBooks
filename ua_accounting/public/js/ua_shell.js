// Shell of the accounting desk (T-433): light sidebar, function panel, top bar, Ctrl K search.
// Sections and their commands are data (ua_accounting.shell.SECTIONS): one source for the sidebar,
// the function panel, the search and the home page.
frappe.provide("ua_accounting.shell");

// own scope: all scripts of the desk share one global scope
(function () {
	const UA_ROLES = ["UA Accountant", "UA Accounting Manager", "System Manager"];
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const icon = (name, cls) => ua_accounting.ui.icon(name, cls);

	// kept for older callers: icon(name) with a size is the same icon
	ua_accounting.shell.icon = (name) => icon(name);

	// ---------------------------------------------------------------- sections (data only)
	// Command: {label, doctype} -> list; {doctype, view: "Tree"} -> tree; {page} -> page;
	// {doctype, single: 1} -> settings form. A command is hidden if the user cannot read it.
	const C = {
		customer_order: { label: "Замовлення покупця", doctype: "UA Customer Order" },
		sales_invoice: { label: "Реалізація товарів та послуг", doctype: "UA Sales Invoice" },
		supplier_order: { label: "Замовлення постачальнику", doctype: "UA Supplier Order" },
		purchase_receipt: { label: "Надходження товарів та послуг", doctype: "UA Purchase Receipt" },
		cash_receipt: { label: "Надходження коштів", doctype: "UA Cash Receipt" },
		cash_payment: { label: "Витрата коштів", doctype: "UA Cash Payment" },
		operation: { label: "Операції (бухгалтерські)", doctype: "UA Journal Operation" },
		tax_invoice: { label: "Податкові накладні", doctype: "UA Tax Invoice" },
		tax_adjustment: { label: "Розрахунки коригування", doctype: "UA Tax Adjustment" },
		vat_allocation: { label: "Розподіл ПДВ", doctype: "UA VAT Allocation" },
		vat_return: { label: "Декларації з ПДВ", doctype: "UA VAT Return" },
		vat_setting: { label: "Налаштування ПДВ (ліміт реєстрації)", doctype: "UA VAT Setting" },
		tax_differences: { label: "Розрахунок податкових різниць", page: "ua-tax-differences" },
		regulated_reports: { label: "Регламентована звітність", page: "ua-regulated-reports" },
		regulated_report: { label: "Регламентовані звіти", doctype: "UA Regulated Report" },
		statistical_report: { label: "Статистична звітність", doctype: "UA Statistical Report" },
		signed_document: { label: "Архів поданих документів", doctype: "UA Signed Document" },
		e_reporting_setting: { label: "Налаштування електронної звітності", doctype: "UA E-Reporting Setting" },
		tax_difference_item: { label: "Статті податкових різниць", doctype: "UA Tax Difference Item" },
		tax_register: { label: "Реєстр податкових накладних", page: "ua-tax-invoice-register" },
		month_closing: { label: "Закриття місяця", page: "ua-month-closing" },
		report_builder: { label: "Універсальний звіт", page: "ua-report-builder" },
		employee: { label: "Співробітники", doctype: "UA Employee" },
		position: { label: "Посади", doctype: "UA Position" },
		work_schedule: { label: "Графіки роботи", doctype: "UA Work Schedule" },
		hiring: { label: "Прийом на роботу", doctype: "UA Hiring" },
		staff_transfer: { label: "Кадрове переміщення", doctype: "UA Staff Transfer" },
		dismissal: { label: "Звільнення", doctype: "UA Dismissal" },
		timesheet: { label: "Табель", doctype: "UA Timesheet" },
		payroll: { label: "Нарахування зарплати", doctype: "UA Payroll" },
		salary_payment: { label: "Виплата зарплати", doctype: "UA Salary Payment" },
		payslip: { label: "Розрахунковий листок", page: "query-report/UA Payslip" },
		payroll_accruals: { label: "Звіт по нарахуваннях", page: "query-report/UA Payroll Accruals Report" },
		appendix_4df: { label: "Додаток 4ДФ", page: "query-report/UA Appendix 4DF" },
		bad_debt_write_off: { label: "Списання безнадійної заборгованості", doctype: "UA Bad Debt Write-off" },
		vacation_inventory: { label: "Інвентаризація резерву відпусток", doctype: "UA Vacation Reserve Inventory" },
		provision_accrual: { label: "Нарахування резервів", doctype: "UA Provision Accrual" },
		provision_settings: { label: "Налаштування резервів", doctype: "UA Provision Settings" },
		payment_assistant: { label: "Помічник оплати", page: "ua-payment-assistant" },
		vat_assistant: { label: "Помічник ПДВ", page: "ua-vat-assistant" },
		manager_monitor: { label: "Монітор керівника", page: "ua-manager-monitor" },
		accountant_task: { label: "Завдання бухгалтера", doctype: "UA Accountant Task" },
		tax_payment_account: { label: "Рахунки для сплати податків", doctype: "UA Tax Payment Account" },
		doubtful_reserve: { label: "Розрахунок резерву сумнівних боргів", page: "ua-doubtful-debts-reserve" },
		data_exchange: { label: "Обмін даними", page: "ua-data-exchange" },
		exchange_settings: { label: "Налаштування обміну", doctype: "UA Exchange Settings", single: 1 },
		exchange_log: { label: "Журнал обміну", doctype: "UA Exchange Log" },
		uktzed: { label: "УКТЗЕД", doctype: "UA UKTZED" },
		kved: { label: "КВЕД", doctype: "UA KVED" },
		dkpp: { label: "ДКПП", doctype: "UA DKPP" },
		counterparty: { label: "Контрагенти", doctype: "UA Counterparty" },
		contract: { label: "Договори контрагентів", doctype: "UA Counterparty Contract" },
		item: { label: "Номенклатура", doctype: "UA Item" },
		uom: { label: "Одиниці виміру", doctype: "UA UOM" },
		warehouse: { label: "Склади", doctype: "UA Warehouse" },
		bank: { label: "Банки", doctype: "UA Bank" },
		bank_account: { label: "Банківські рахунки", doctype: "UA Bank Account" },
		cash_desk: { label: "Каси", doctype: "UA Cash Desk" },
		payment_order: { label: "Платіжні доручення", doctype: "UA Payment Order" },
		bank_statement: { label: "Банківські виписки", doctype: "UA Bank Statement" },
		advance_report: { label: "Авансові звіти", doctype: "UA Advance Report" },
		cash_disbursement: { label: "Видаткові відомості", doctype: "UA Cash Disbursement" },
		currency_exchange: { label: "Купівля/продаж валюти", doctype: "UA Currency Exchange" },
		dividend_accrual: { label: "Нарахування дивідендів", doctype: "UA Dividend Accrual" },
		tax_payment: { label: "Сплата податків", doctype: "UA Tax Payment" },
		loan: { label: "Кредити і позики", doctype: "UA Loan" },
		loan_drawdown: { label: "Отримання кредиту / позики", doctype: "UA Loan Drawdown" },
		loan_interest: { label: "Нарахування відсотків за кредитами", doctype: "UA Loan Interest Accrual" },
		loan_repayment: { label: "Погашення кредиту / позики", doctype: "UA Loan Repayment" },
		currency_revaluation: { label: "Переоцінка валютних розрахунків", doctype: "UA Currency Revaluation" },
		opening_balances: { label: "Введення початкових залишків", doctype: "UA Opening Balances" },
		accountable_report: { label: "Розрахунки з підзвітними особами", page: "query-report/UA Accountable Persons Report" },
		founder_report: { label: "Розрахунки із засновниками", page: "query-report/UA Founder Settlements Report" },
		budget_report: { label: "Розрахунки з бюджетом за податками", page: "query-report/UA Budget Settlements Report" },
		loans_report: { label: "Кредити і позики (звіт)", page: "query-report/UA Loans Report" },
		stock_transfer: { label: "Переміщення товарів", doctype: "UA Stock Transfer" },
		stock_writeoff: { label: "Списання товарів", doctype: "UA Stock Writeoff" },
		stock_surplus: { label: "Оприбуткування товарів", doctype: "UA Stock Surplus" },
		stock_inventory: { label: "Інвентаризація товарів", doctype: "UA Stock Inventory" },
		stock_assembly: { label: "Комплектація/розкомплектація", doctype: "UA Stock Assembly" },
		low_value_issue: { label: "Передача матеріалів в експлуатацію", doctype: "UA Low Value Issue" },
		special_wear_issue: { label: "Передача в експлуатацію спецодягу", doctype: "UA Special Wear Issue" },
		special_wear_monthly: { label: "Списання вартості спецодягу за місяць", doctype: "UA Special Wear Monthly Writeoff" },
		special_wear_return: { label: "Повернення спецодягу на склад", doctype: "UA Special Wear Return" },
		special_wear_writeoff: { label: "Списання спецодягу з експлуатації", doctype: "UA Special Wear Writeoff" },
		special_wear_in_use: { label: "Відомість спецодягу в експлуатації", page: "query-report/UA Special Wear In Use Report" },
		requirement_invoice: { label: "Вимога-накладна", doctype: "UA Requirement Invoice" },
		commission_receipt: { label: "Надходження товарів на комісію", doctype: "UA Commission Receipt" },
		commission_transfer: { label: "Передача на комісію", doctype: "UA Commission Transfer" },
		commission_agent_report: { label: "Звіт комісіонера", doctype: "UA Commission Agent Report" },
		principal_report: { label: "Звіт комітенту", doctype: "UA Principal Report" },
		commission_return: { label: "Повернення комітенту", doctype: "UA Commission Return" },
		tolling_transfer: { label: "Передача сировини в переробку", doctype: "UA Tolling Transfer" },
		tolling_receipt: { label: "Отримання з переробки", doctype: "UA Tolling Receipt" },
		tolling_intake: { label: "Сировина, прийнята в переробку", doctype: "UA Tolling Intake" },
		tolling_output: { label: "Передача готової продукції замовнику", doctype: "UA Tolling Output" },
		packaging_return: { label: "Повернення тари", doctype: "UA Packaging Return" },
		packaging_balance: { label: "Розрахунки за тару", page: "query-report/UA Packaging Balance" },
		production_report: { label: "Звіт виробництва за зміну", doctype: "UA Production Report" },
		production_closing: { label: "Закриття місяця (виробництво)", doctype: "UA Production Month Closing" },
		own_work_act: { label: "Акт про виконання робіт власного виробництва", doctype: "UA Own Work Act" },
		item_specification: { label: "Специфікації номенклатури", doctype: "UA Item Specification" },
		planned_price: { label: "Планові ціни", doctype: "UA Planned Price" },
		production_cost: { label: "Звіт про собівартість випуску", page: "query-report/UA Production Cost Report" },
		stock_balance: { label: "Залишки товарів", page: "ua-stock-balance" },
		stock_statement: { label: "Відомість по товарах на складах", page: "ua-stock-statement" },
		cash_book: { label: "Касова книга", page: "ua-cash-book" },
		bank_journal: { label: "Журнал банківських документів", page: "query-report/UA Bank Journal" },
		currency: { label: "Валюти", doctype: "UA Currency" },
		cash_flow_item: { label: "Статті руху грошових коштів", doctype: "UA Cash Flow Item" },
		expense_item: { label: "Статті витрат", doctype: "UA Expense Item" },
		organization: { label: "Організації", doctype: "UA Organization" },
		accounting_policy: { label: "Облікова політика", doctype: "UA Accounting Policy" },
		accounting_settings: { label: "Налаштування обліку", doctype: "UA Accounting Settings", single: 1 },
		numbering: { label: "Налаштування нумерації", doctype: "UA Numbering Setting" },
		change_log: { label: "Журнал реєстрації змін", doctype: "UA Change Log" },
		department: { label: "Підрозділи", doctype: "UA Department" },
		person: { label: "Фізичні особи", doctype: "UA Person" },
		fixed_asset: { label: "Основні засоби", doctype: "UA Fixed Asset" },
		intangible: { label: "Нематеріальні активи", doctype: "UA Intangible Asset" },
		low_value: { label: "Малоцінні активи (МНМА)", doctype: "UA Low Value Asset" },
		asset_acceptance: { label: "Прийняття до обліку ОЗ / НМА", doctype: "UA Asset Acceptance" },
		asset_depreciation: { label: "Нарахування амортизації", doctype: "UA Asset Depreciation" },
		asset_modernization: { label: "Модернізація ОЗ", doctype: "UA Asset Modernization" },
		asset_transfer: { label: "Переміщення ОЗ", doctype: "UA Asset Transfer" },
		asset_writeoff: { label: "Списання ОЗ", doctype: "UA Asset Writeoff" },
		asset_sale: { label: "Продаж ОЗ", doctype: "UA Asset Sale" },
		asset_revaluation: { label: "Переоцінка ОЗ", doctype: "UA Asset Revaluation" },
		fixed_asset_card: { label: "Інвентарна картка обліку основних засобів (ОЗ-6)", page: "query-report/UA Fixed Asset Card" },
		lease_agreement: { label: "Договори оренди", doctype: "UA Lease Agreement" },
		leased_asset_receipt: { label: "Отримання майна в оренду", doctype: "UA Leased Asset Receipt" },
		leased_asset_return: { label: "Повернення майна з оренди", doctype: "UA Leased Asset Return" },
		rent_accrual: { label: "Нарахування орендної плати", doctype: "UA Rent Accrual" },
		finance_lease_receipt: { label: "Отримання майна у фінансову оренду", doctype: "UA Finance Lease Receipt" },
		lease_interest_accrual: { label: "Нарахування відсотків за фінансовою орендою", doctype: "UA Lease Interest Accrual" },
		lease_payment: { label: "Лізинговий платіж", doctype: "UA Lease Payment" },
		lease_obligations: { label: "Зобов'язання за орендою", page: "query-report/UA Lease Obligations Report" },
		depreciation_statement: { label: "Відомість амортизації", page: "query-report/UA Depreciation Statement" },
		account: { label: "План рахунків", doctype: "UA Account", view: "Tree" },
		subconto: { label: "Види субконто", doctype: "UA Subconto Type" },
		vat_rate: { label: "Ставки ПДВ", doctype: "UA VAT Rate" },
		tax_type: { label: "Види податків", doctype: "UA Tax Type" },
		osv: { label: "Оборотно-сальдова відомість", page: "ua-osv" },
		osv_account: { label: "ОСВ по рахунку", page: "ua-osv-account" },
		account_card: { label: "Картка рахунку", page: "ua-account-card" },
		subconto_analysis: { label: "Аналіз субконто", page: "ua-subconto-analysis" },
		osv_subconto: { label: "ОСВ по субконто", page: "ua-osv-subconto" },
		account_turnover: { label: "Обороти рахунку", page: "ua-account-turnover" },
		account_analysis: { label: "Аналіз рахунку", page: "ua-account-analysis" },
		general_ledger: { label: "Головна книга", page: "ua-general-ledger" },
		journal_order: { label: "Журнал-ордер", page: "ua-journal-order" },
		chess_sheet: { label: "Шахова відомість", page: "ua-chess-sheet" },
		entries_report: { label: "Звіт по проводках", page: "ua-entries-report" },
		subconto_card: { label: "Картка субконто", page: "ua-subconto-card" },
		accounting_check: { label: "Експрес-перевірка ведення обліку", page: "ua-accounting-check" },
		entries: { label: "Журнал проводок", doctype: "UA Accounting Entry" },
		turnover: { label: "Підсумки по рахунках", doctype: "UA Account Turnover", route: ["ua-account-turnover", "view", "list"] },
		vat_liability: { label: "ПДВ нараховане", doctype: "UA VAT Liability Entry" },
		vat_credit: { label: "ПДВ кредит", doctype: "UA VAT Credit Entry" },
		users: { label: "Користувачі", doctype: "User" },
		roles: { label: "Ролі", doctype: "Role" },
		system_settings: { label: "Налаштування системи", doctype: "System Settings", single: 1 },
	};
	ua_accounting.shell.COMMANDS = C;

	// The function panel has four columns: Документи / Довідники / Звіти / Сервіс.
	const COLUMNS = [
		{ key: "docs", title: "Документи", icon: "file" },
		{ key: "refs", title: "Довідники", icon: "book" },
		{ key: "reps", title: "Звіти", icon: "chart" },
		{ key: "svc", title: "Сервіс", icon: "gear" },
	];

	const SECTIONS = [
		{ id: "home", label: "Головне", icon: "home", page: "ua-home" },
		{
			id: "buy",
			label: "Покупки",
			icon: "cart",
			sub: "Закупівлі та постачальники",
			quick: [C.purchase_receipt, C.supplier_order],
			docs: [C.purchase_receipt, C.supplier_order, C.tax_invoice],
			refs: [C.counterparty, C.contract, C.item, C.warehouse],
			reps: [C.osv_account, C.account_card],
			svc: [C.vat_credit],
		},
		{
			id: "sell",
			label: "Продажі",
			icon: "trending",
			sub: "Реалізація та покупці",
			quick: [C.sales_invoice, C.customer_order],
			docs: [C.sales_invoice, C.customer_order, C.tax_invoice, C.tax_adjustment],
			refs: [C.counterparty, C.contract, C.item],
			reps: [C.osv_account, C.account_card],
			svc: [C.vat_liability],
		},
		{
			id: "stock",
			label: "Склад",
			icon: "package",
			sub: "Рух і залишки товарів",
			quick: [C.purchase_receipt, C.sales_invoice],
			docs: [C.purchase_receipt, C.sales_invoice, C.stock_transfer, C.stock_writeoff, C.stock_surplus, C.stock_inventory, C.stock_assembly, C.low_value_issue, C.requirement_invoice, C.commission_receipt, C.commission_transfer, C.commission_agent_report, C.principal_report, C.commission_return, C.tolling_transfer, C.tolling_receipt, C.tolling_intake, C.tolling_output, C.packaging_return, C.special_wear_issue, C.special_wear_monthly, C.special_wear_return, C.special_wear_writeoff],
			refs: [C.warehouse, C.item, C.uom],
			reps: [C.stock_balance, C.stock_statement, C.packaging_balance, C.special_wear_in_use, C.osv_account, C.account_card],
			svc: [],
		},
		{
			id: "production",
			label: "Виробництво",
			icon: "package",
			sub: "Випуск, планова та фактична собівартість",
			quick: [C.production_report],
			docs: [C.production_report, C.production_closing, C.own_work_act],
			refs: [C.item_specification, C.planned_price, C.item, C.department, C.expense_item],
			reps: [C.production_cost, C.osv_account, C.account_card],
			svc: [],
		},
		{
			id: "bank",
			label: "Банк і каса",
			icon: "landmark",
			sub: "Надходження і витрата коштів",
			quick: [C.cash_receipt, C.cash_payment],
			docs: [C.cash_receipt, C.cash_payment, C.payment_order, C.bank_statement, C.advance_report, C.cash_disbursement, C.currency_exchange],
			refs: [C.bank_account, C.bank, C.cash_desk, C.currency, C.cash_flow_item],
			reps: [C.cash_book, C.bank_journal, C.osv_account, C.account_card],
			svc: [C.payment_assistant],
		},
		{
			id: "settlements",
			label: "Розрахунки",
			icon: "landmark",
			sub: "Підзвітні особи, засновники, бюджет, кредити",
			quick: [C.opening_balances],
			docs: [C.dividend_accrual, C.tax_payment, C.loan_drawdown, C.loan_interest, C.loan_repayment, C.currency_revaluation, C.opening_balances],
			refs: [C.loan, C.person],
			reps: [C.accountable_report, C.founder_report, C.budget_report, C.loans_report, C.osv_account],
			svc: [],
		},
		{
			id: "payroll",
			label: "Зарплата та кадри",
			icon: "user",
			sub: "Співробітники, нарахування, виплата",
			quick: [C.payroll, C.salary_payment],
			docs: [C.hiring, C.staff_transfer, C.dismissal, C.timesheet, C.payroll, C.salary_payment],
			refs: [C.employee, C.position, C.work_schedule, C.department, C.person],
			reps: [C.payslip, C.payroll_accruals, C.appendix_4df, C.osv_account],
			svc: [],
		},
		{
			id: "assets",
			label: "ОС і НМА",
			icon: "building",
			sub: "Основні засоби, нематеріальні активи",
			quick: [],
			docs: [
				C.asset_acceptance,
				C.asset_depreciation,
				C.asset_modernization,
				C.asset_transfer,
				C.asset_writeoff,
				C.asset_sale,
				C.asset_revaluation,
				C.leased_asset_receipt,
				C.leased_asset_return,
				C.rent_accrual,
				C.finance_lease_receipt,
				C.lease_interest_accrual,
				C.lease_payment,
			],
			refs: [C.fixed_asset, C.intangible, C.low_value, C.lease_agreement],
			reps: [C.fixed_asset_card, C.depreciation_statement, C.lease_obligations, C.osv_account],
			svc: [],
		},
		{
			id: "reports",
			label: "Звіти",
			icon: "chart",
			sub: "Стандартні звіти та регістри",
			quick: [C.osv],
			docs: [C.operation, C.tax_invoice, C.tax_adjustment, C.vat_allocation, C.vat_return, C.tax_difference_item, C.month_closing, C.provision_accrual, C.bad_debt_write_off, C.vacation_inventory, C.regulated_report, C.statistical_report, C.signed_document, C.e_reporting_setting],
			refs: [C.account, C.subconto],
			reps: [
				C.osv,
				C.osv_account,
				C.account_card,
				C.subconto_analysis,
				C.osv_subconto,
				C.account_turnover,
				C.account_analysis,
				C.general_ledger,
				C.journal_order,
				C.chess_sheet,
				C.entries_report,
				C.subconto_card,
				C.accounting_check,
				C.tax_register,
				C.tax_differences,
				C.doubtful_reserve,
				C.regulated_reports,
				C.report_builder,
				C.manager_monitor,
			],
			svc: [C.entries, C.turnover, C.vat_liability, C.vat_credit, C.vat_setting, C.provision_settings, C.vat_assistant, C.accountant_task, C.tax_payment_account],
		},
		{
			id: "catalogs",
			label: "Довідники",
			icon: "book",
			sub: "Нормативно-довідкова інформація",
			quick: [C.item, C.counterparty],
			docs: [],
			refs: [
				C.organization,
				C.counterparty,
				C.contract,
				C.item,
				C.warehouse,
				C.uom,
				C.bank_account,
				C.bank,
				C.cash_desk,
				C.currency,
				C.cash_flow_item,
				C.expense_item,
				C.department,
				C.person,
				C.uktzed,
				C.kved,
				C.dkpp,
			],
			reps: [],
			svc: [],
		},
		{
			id: "admin",
			label: "Адміністрування",
			icon: "sliders",
			sub: "Налаштування, користувачі, облік",
			quick: [],
			docs: [C.operation],
			refs: [C.account, C.subconto, C.vat_rate, C.tax_type, C.accounting_policy],
			reps: [],
			svc: [C.data_exchange, C.exchange_log, C.exchange_settings, C.users, C.roles, C.accounting_settings, C.numbering, C.change_log, C.system_settings],
		},
	];
	// older callers read section.groups: one group per column
	SECTIONS.forEach((s) => {
		s.groups = COLUMNS.map((c) => ({ title: c.title, key: c.key, items: s[c.key] || [] })).filter(
			(g) => g.items.length
		);
	});
	ua_accounting.shell.SECTIONS = SECTIONS;

	// Doctypes the home page offers as quick create tiles.
	ua_accounting.shell.QUICK_CREATE = [
		"UA Sales Invoice",
		"UA Purchase Receipt",
		"UA Customer Order",
		"UA Cash Receipt",
		"UA Cash Payment",
	];

	ua_accounting.shell.can_open = function (cmd) {
		if (cmd.page) return true;
		return frappe.model.can_read(cmd.doctype) || frappe.boot.user.can_read.includes(cmd.doctype);
	};

	ua_accounting.shell.cmd_route = function (cmd) {
		if (cmd.page) return [cmd.page];
		if (cmd.route) return cmd.route;
		if (cmd.single) return ["Form", cmd.doctype];
		if (cmd.view) return [cmd.view, cmd.doctype];
		return ["List", cmd.doctype];
	};

	ua_accounting.shell.open = function (cmd) {
		if (cmd.new) frappe.new_doc(cmd.doctype);
		else frappe.set_route(ua_accounting.shell.cmd_route(cmd));
	};

	ua_accounting.shell.cmd_id = function (c) {
		return (c.page || c.doctype) + (c.view ? ":" + c.view : "");
	};

	// Sections with the commands the user may open. Empty columns are dropped.
	ua_accounting.shell.visible_sections = function () {
		return SECTIONS.map((section) => {
			const s = Object.assign({}, section);
			["quick"].concat(COLUMNS.map((c) => c.key)).forEach((k) => {
				s[k] = (section[k] || []).filter(ua_accounting.shell.can_open);
			});
			s.quick = s.quick.filter((c) => c.doctype && frappe.model.can_create(c.doctype));
			s.groups = section.groups
				.map((g) => ({ title: g.title, key: g.key, items: g.items.filter(ua_accounting.shell.can_open) }))
				.filter((g) => g.items.length);
			return s;
		}).filter((s) => s.page || s.groups.length);
	};

	ua_accounting.shell.find_command = function (id) {
		const all = Object.values(C);
		return all.find((c) => ua_accounting.shell.cmd_id(c) === id) || null;
	};

	// The section that owns a command (the first one that lists it; reports go to "Звіти").
	ua_accounting.shell.section_of = function (target) {
		if (!target) return null;
		const order = SECTIONS.slice().sort((a, b) => (b.id === "reports") - (a.id === "reports"));
		if (target === "ua-home") return SECTIONS[0];
		let found = null;
		order.forEach((s) => {
			if (found) return;
			if (s.page === target) found = s;
			(s.groups || []).forEach((g) =>
				g.items.forEach((c) => {
					if (!found && (c.page || c.doctype) === target) found = s;
				})
			);
		});
		// documents belong to their trade section first
		const doc_home = {
			"UA Sales Invoice": "sell",
			"UA Customer Order": "sell",
			"UA Purchase Receipt": "buy",
			"UA Supplier Order": "buy",
			"UA Cash Receipt": "bank",
			"UA Cash Payment": "bank",
			"UA Journal Operation": "reports",
			"UA Tax Invoice": "reports",
			"UA Tax Adjustment": "reports",
			"UA VAT Allocation": "reports",
			"UA VAT Return": "reports",
			"UA Tax Difference Item": "reports",
			"UA Regulated Report": "reports",
			"UA Statistical Report": "reports",
			"UA Signed Document": "reports",
			"UA E-Reporting Setting": "reports",
		}[target];
		if (doc_home) found = SECTIONS.find((s) => s.id === doc_home);
		const catalog_home = { "UA Item": "catalogs", "UA Counterparty": "catalogs" }[target];
		if (catalog_home) found = SECTIONS.find((s) => s.id === catalog_home);
		return found;
	};

	// ---------------------------------------------------------------- history and favourites (per browser)

	ua_accounting.shell.store = {
		key(kind) {
			return `ua_shell:${frappe.session.user}:${kind}`;
		},
		get(kind) {
			try {
				const v = JSON.parse(localStorage.getItem(this.key(kind)) || "[]");
				return Array.isArray(v) ? v : [];
			} catch (e) {
				return [];
			}
		},
		set(kind, list) {
			try {
				localStorage.setItem(this.key(kind), JSON.stringify(list));
			} catch (e) {
				// storage full or blocked: history is not important
			}
		},
		raw(kind, value) {
			try {
				if (value === undefined) return localStorage.getItem(this.key(kind));
				localStorage.setItem(this.key(kind), value);
			} catch (e) {
				return null;
			}
		},
	};

	ua_accounting.shell.route_key = function (route) {
		return (route || []).join("/");
	};

	// a short label for the current page (title of the form, the list or the report)
	ua_accounting.shell.current_label = function () {
		const route = frappe.get_route() || [];
		if (route[0] === "Form" && window.cur_frm && cur_frm.doctype === route[1]) {
			return `${__(route[1])} ${cur_frm.doc.name || ""}`.trim();
		}
		if ((route[0] === "List" || route[0] === "Tree") && route[1]) return __(route[1]);
		const cmd = Object.values(C).find((c) => c.page === route[0] || c.page === route.join("/"));
		if (cmd) return __(cmd.label);
		const wrapper = frappe.pages && frappe.pages[route[0]];
		if (wrapper && wrapper.page && wrapper.page.title) return wrapper.page.title;
		return (document.title || "").replace(/\s*\(\d+\)\s*$/, "");
	};

	ua_accounting.shell.track = function () {
		const route = frappe.get_route();
		if (!route || !route.length || route[0] === "ua-home") return;
		// the title is written after the route change
		setTimeout(() => {
			if (ua_accounting.shell.route_key(frappe.get_route()) !== ua_accounting.shell.route_key(route)) return;
			const key = ua_accounting.shell.route_key(route);
			const label = ua_accounting.shell.current_label();
			const list = ua_accounting.shell.store.get("hist").filter((h) => h.key !== key);
			list.unshift({ key, route, label });
			ua_accounting.shell.store.set("hist", list.slice(0, 30));
		}, 600);
	};

	// Favourites: commands of the panel ({cmd}) or any page ({route}).
	ua_accounting.shell.favs = function () {
		return ua_accounting.shell.store.get("fav");
	};

	ua_accounting.shell.fav_key_of_cmd = (cmd) => "cmd:" + ua_accounting.shell.cmd_id(cmd);

	ua_accounting.shell.is_fav = function (key) {
		return ua_accounting.shell.favs().some((f) => f.key === key);
	};

	ua_accounting.shell.toggle_fav = function (entry) {
		let list = ua_accounting.shell.favs();
		const on = !list.some((f) => f.key === entry.key);
		if (on) list.push(entry);
		else list = list.filter((f) => f.key !== entry.key);
		ua_accounting.shell.store.set("fav", list);
		ua_accounting.ui.toast({
			title: on ? __("Додано в Обране") : __("Прибрано з Обраного"),
			text: entry.label,
			type: "info",
			duration: 2600,
		});
		ua_accounting.shell.render_fav_count();
		$(document).trigger("ua-favs-changed");
		return on;
	};

	ua_accounting.shell.open_fav = function (f) {
		const cmd = f.cmd && ua_accounting.shell.find_command(f.cmd);
		if (cmd) ua_accounting.shell.open(cmd);
		else if (f.route) frappe.set_route(f.route);
	};

	// "Продажі · Документи" for a favourite command
	ua_accounting.shell.fav_meta = function (f) {
		const cmd = f.cmd && ua_accounting.shell.find_command(f.cmd);
		if (!cmd) return "";
		const s = ua_accounting.shell.section_of(cmd.page || cmd.doctype);
		const col = COLUMNS.find((c) => s && (s[c.key] || []).includes(cmd));
		return [s && __(s.label), col && __(col.title)].filter(Boolean).join(" · ");
	};

	ua_accounting.shell.fav_icon = function (f) {
		const cmd = f.cmd && ua_accounting.shell.find_command(f.cmd);
		if (!cmd) return "file";
		if (cmd.page) return "chart";
		const s = ua_accounting.shell.section_of(cmd.doctype);
		const col = COLUMNS.find((c) => s && (s[c.key] || []).includes(cmd));
		return col ? col.icon : "file";
	};

	// ---------------------------------------------------------------- organizations

	ua_accounting.shell.orgs = [];

	ua_accounting.shell.current_org = function () {
		const id = ua_accounting.shell.store.raw("org");
		const orgs = ua_accounting.shell.orgs;
		return orgs.find((o) => o.name === id) || orgs.find((o) => o.edrpou) || orgs[0] || null;
	};

	ua_accounting.shell.org_mark = function (title) {
		const words = String(title || "")
			.replace(/[«»"']/g, "")
			.split(/\s+/)
			.filter((w) => w && !["ТОВ", "ПП", "ФОП", "ПрАТ", "АТ"].includes(w));
		return (words.slice(0, 2).map((w) => w[0]).join("") || "—").toUpperCase();
	};

	ua_accounting.shell.load_orgs = function () {
		if (!frappe.model.can_read("UA Organization")) return Promise.resolve([]);
		return frappe.db
			.get_list("UA Organization", { fields: ["name", "org_name", "edrpou"], limit: 50, order_by: "org_name asc" })
			.then((rows) => {
				ua_accounting.shell.orgs = rows || [];
				ua_accounting.shell.render_org();
				$(document).trigger("ua-org-changed");
				return rows;
			})
			.catch(() => []);
	};

	ua_accounting.shell.render_org = function () {
		const org = ua_accounting.shell.current_org();
		const $org = $("#ua-sidebar .ua-sb-org");
		if (!org) {
			$org.prop("hidden", true);
			return;
		}
		$org.prop("hidden", false).attr("data-ua-tip", org.org_name);
		$org.find(".ua-sb-org-mark").text(ua_accounting.shell.org_mark(org.org_name));
		$org.find(".ua-sb-org-name").text(org.org_name);
		$org.find(".ua-sb-org-meta").text(org.edrpou ? `${__("ЄДРПОУ")} ${org.edrpou}` : __("ЄДРПОУ не вказано"));
	};

	ua_accounting.shell.org_menu = function (trigger) {
		const current = ua_accounting.shell.current_org();
		const items = ua_accounting.shell.orgs
			.map(
				(o) =>
					`<button class="ua-menu-item${current && o.name === current.name ? " is-active" : ""}" data-org="${esc(
						o.name
					)}"><span class="ua-sb-org-mark">${esc(ua_accounting.shell.org_mark(o.org_name))}</span>` +
					`<span class="ua-two"><span>${esc(o.org_name)}</span><small>${esc(
						o.edrpou ? `${__("ЄДРПОУ")} ${o.edrpou}` : __("ЄДРПОУ не вказано")
					)}</small></span>${current && o.name === current.name ? icon("check", "ua-i-sm") : ""}</button>`
			)
			.join("");
		ua_accounting.ui.menu(
			trigger,
			`<div class="ua-menu-label">${esc(__("Організація"))}</div>${items}`,
			(item) => {
				const id = item.getAttribute("data-org");
				if (!id) return;
				ua_accounting.shell.store.raw("org", id);
				ua_accounting.shell.render_org();
				$(document).trigger("ua-org-changed");
			},
			{ cls: "ua-org-pop" }
		);
	};

	// ---------------------------------------------------------------- build the DOM

	ua_accounting.shell.user_role = function () {
		if (frappe.user.has_role("UA Accounting Manager")) return __("Головний бухгалтер");
		if (frappe.user.has_role("UA Accountant")) return __("Бухгалтер");
		if (frappe.user.has_role("System Manager")) return __("Адміністратор");
		return "";
	};

	ua_accounting.shell.initials = function (name) {
		return (
			String(name || "")
				.split(/\s+/)
				.filter(Boolean)
				.slice(0, 2)
				.map((w) => w[0])
				.join("")
				.toUpperCase() || "—"
		);
	};

	ua_accounting.shell.build = function () {
		if (document.getElementById("ua-sidebar")) return;
		ua_accounting.ui.inject_icons();
		const sections = ua_accounting.shell.visible_sections();
		ua_accounting.shell.sections = sections;
		const user = frappe.session.user_fullname || frappe.session.user;
		const dark = document.documentElement.getAttribute("data-theme") === "dark";

		const items = sections
			.map((s) =>
				s.page
					? `<a class="ua-sb-item" href="/desk/${esc(s.page)}" data-section="${s.id}" data-ua-tip="${esc(
							__(s.label)
					  )}" data-ua-tip-pos="right">${icon(s.icon)}<span class="ua-sb-text">${esc(__(s.label))}</span></a>`
					: `<button type="button" class="ua-sb-item" data-section="${s.id}" aria-haspopup="dialog" aria-expanded="false" ` +
					  `data-ua-tip="${esc(__(s.label))}" data-ua-tip-pos="right">${icon(s.icon)}<span class="ua-sb-text">${esc(
							__(s.label)
					  )}</span>${icon("chev-r", "ua-sb-arrow")}</button>`
			)
			.join("");

		const sidebar = $(`
		<aside id="ua-sidebar" class="ua-sidebar" aria-label="${esc(__("Меню"))}">
			<div class="ua-sb-brand"><span class="ua-logo" aria-hidden="true"></span>
				<a class="ua-sb-brand-name" href="/desk/ua-home">HiveBooks</a>
				<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm ua-sb-collapse" data-act="collapse"
					aria-label="${esc(__("Згорнути меню"))}" data-ua-tip="${esc(__("Згорнути меню"))}">${icon("panel")}</button>
			</div>
			<div class="ua-sb-scroll">
				<button type="button" class="ua-sb-org" data-act="org" data-ua-tip-pos="right" aria-haspopup="menu" hidden>
					<span class="ua-sb-org-mark"></span><span class="ua-sb-org-text"><span class="ua-sb-org-name"></span>
					<span class="ua-sb-org-meta"></span></span>${icon("updown", "ua-i-sm")}</button>
				<button type="button" class="ua-sb-search" data-act="search" data-ua-tip="${esc(__("Пошук · Ctrl K"))}" data-ua-tip-pos="right">
					${icon("search")}<span>${esc(__("Пошук і команди"))}</span><span class="ua-kbd">Ctrl K</span></button>
				<button type="button" class="ua-sb-item" data-act="favs" aria-haspopup="menu" data-ua-tip="${esc(
					__("Обране")
				)}" data-ua-tip-pos="right">${icon("star")}<span class="ua-sb-text">${esc(
			__("Обране")
		)}</span><span class="ua-sb-count"></span></button>
				<button type="button" class="ua-sb-item" data-act="hist" aria-haspopup="menu" data-ua-tip="${esc(
					__("Історія")
				)}" data-ua-tip-pos="right">${icon("history")}<span class="ua-sb-text">${esc(__("Історія"))}</span></button>
				<div class="ua-sb-label">${esc(__("Розділи"))}</div>
				<nav aria-label="${esc(__("Розділи"))}">${items}</nav>
			</div>
			<div class="ua-sb-footer">
				<button type="button" class="ua-sb-me" data-act="user" aria-haspopup="menu" data-ua-tip="${esc(user)}" data-ua-tip-pos="right">
					<span class="ua-avatar">${esc(ua_accounting.shell.initials(user))}</span>
					<span class="ua-sb-user"><b>${esc(user)}</b><span>${esc(ua_accounting.shell.user_role())}</span></span>
				</button>
				<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-act="theme"
					aria-label="${esc(__("Змінити тему"))}" data-ua-tip="${esc(__("Світла / темна тема"))}">${icon(
			dark ? "sun" : "moon"
		)}</button>
			</div>
		</aside>`);

		const today = frappe.datetime.str_to_user(frappe.datetime.get_today());
		const top = $(`
		<header id="ua-topbar" class="ua-topbar">
			<nav class="ua-crumbs" aria-label="${esc(__("Шлях"))}"></nav>
			<div class="ua-topbar-right">
				<span class="ua-workdate" data-ua-tip="${esc(__("Робоча дата для нових документів"))}">${icon("calendar")}${esc(
			today
		)}</span>
				<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-bell" data-act="bell" aria-haspopup="menu"
					aria-label="${esc(__("Сповіщення"))}" data-ua-tip="${esc(__("Сповіщення"))}">${icon(
			"bell"
		)}<span class="ua-dot-badge" hidden></span></button>
				<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-act="help" aria-haspopup="dialog"
					aria-label="${esc(__("Довідка"))}" data-ua-tip="${esc(__("Довідка"))}">${icon("help")}</button>
			</div>
		</header>`);

		const panel = $(
			`<div class="ua-fpanel-backdrop" data-act="panel-close"></div>` +
				`<aside class="ua-fpanel" id="ua-fpanel" role="dialog" aria-modal="false" aria-labelledby="ua-fp-title"></aside>`
		);

		$(document.body).append(sidebar, top, panel);
		if (ua_accounting.shell.store.raw("sidebar") === "collapsed") {
			document.documentElement.setAttribute("data-ua-sidebar", "collapsed");
		}
		ua_accounting.shell.render_fav_count();

		$(document).on("click.ua_shell", "#ua-sidebar [data-section]", function (e) {
			const id = $(this).attr("data-section");
			const s = sections.find((x) => x.id === id);
			if (s && s.page) {
				e.preventDefault();
				ua_accounting.shell.close_panel();
				frappe.set_route(s.page);
				return;
			}
			ua_accounting.shell.toggle_section(id);
		});
		$(document).on("click.ua_shell", "#ua-sidebar [data-act], #ua-topbar [data-act], .ua-fpanel-backdrop", function (e) {
			const act = $(this).attr("data-act");
			const el = this;
			if (act === "collapse") ua_accounting.shell.toggle_collapse();
			else if (act === "org") ua_accounting.shell.org_menu(el);
			else if (act === "search") ua_accounting.shell.open_search();
			else if (act === "favs") ua_accounting.shell.list_menu(el, "fav");
			else if (act === "hist") ua_accounting.shell.list_menu(el, "hist");
			else if (act === "user") ua_accounting.shell.user_menu(el);
			else if (act === "theme") ua_accounting.shell.toggle_theme();
			else if (act === "bell") ua_accounting.shell.bell_menu(el);
			else if (act === "help") ua_accounting.shell.open_help();
			else if (act === "panel-close") ua_accounting.shell.close_panel();
			else if (act === "crumb-section") {
				e.preventDefault();
				ua_accounting.shell.toggle_section($(el).attr("data-section"));
			}
		});
		$(document).on("click.ua_shell", "#ua-fpanel", ua_accounting.shell.on_panel_click);
		$(document).on("input.ua_shell", "#ua-fpanel [data-fp-search]", function () {
			ua_accounting.shell.filter_panel(this.value);
		});
		$(document).on("keydown.ua_shell", (e) => {
			if (e.key !== "Escape") return;
			if (ua_accounting.ui.menu_open()) {
				ua_accounting.ui.close_menu();
				return;
			}
			if (ua_accounting.shell.open_id) ua_accounting.shell.close_panel();
		});
	};

	ua_accounting.shell.toggle_collapse = function () {
		const root = document.documentElement;
		const collapsed = root.getAttribute("data-ua-sidebar") === "collapsed";
		if (collapsed) root.removeAttribute("data-ua-sidebar");
		else root.setAttribute("data-ua-sidebar", "collapsed");
		ua_accounting.shell.store.raw("sidebar", collapsed ? "open" : "collapsed");
		$(window).trigger("resize");
	};

	ua_accounting.shell.render_fav_count = function () {
		const n = ua_accounting.shell.favs().length;
		$("#ua-sidebar [data-act='favs'] .ua-sb-count").text(n || "");
	};

	// Обране / Історія as a menu next to the sidebar item
	ua_accounting.shell.list_menu = function (trigger, kind) {
		const list = ua_accounting.shell.store.get(kind).slice(0, 12);
		const title = kind === "fav" ? __("Обране") : __("Історія");
		const body = list.length
			? list
					.map(
						(h, i) =>
							`<button class="ua-menu-item" data-i="${i}">${icon(kind === "fav" ? ua_accounting.shell.fav_icon(h) : "history")}` +
							`<span class="ua-two"><span>${esc(h.label)}</span>${
								kind === "fav" && ua_accounting.shell.fav_meta(h)
									? `<small>${esc(ua_accounting.shell.fav_meta(h))}</small>`
									: ""
							}</span></button>`
					)
					.join("")
			: `<div class="ua-menu-empty">${esc(
					kind === "fav"
						? __("Додайте розділи в обране зірочкою в панелі функцій")
						: __("Тут з’являться сторінки, які ви відкривали")
			  )}</div>`;
		ua_accounting.ui.menu(
			trigger,
			`<div class="ua-menu-label">${esc(title)}</div>${body}`,
			(item) => {
				const h = list[+item.getAttribute("data-i")];
				if (!h) return;
				if (kind === "fav") ua_accounting.shell.open_fav(h);
				else frappe.set_route(h.route);
			},
			{ side: "right", cls: "ua-list-pop" }
		);
	};

	ua_accounting.shell.user_menu = function (trigger) {
		const dark = document.documentElement.getAttribute("data-theme") === "dark";
		ua_accounting.ui.menu(
			trigger,
			`<div class="ua-menu-label">${esc(frappe.session.user_fullname || frappe.session.user)}</div>` +
				`<button class="ua-menu-item" data-act="settings">${icon("user")}${esc(__("Мої налаштування"))}</button>` +
				`<button class="ua-menu-item" data-act="theme">${icon(dark ? "sun" : "moon")}${esc(
					dark ? __("Світла тема") : __("Темна тема")
				)}</button>` +
				'<div class="ua-menu-sep"></div>' +
				`<button class="ua-menu-item is-danger" data-act="logout">${icon("logout")}${esc(__("Вийти"))}</button>`,
			(item) => {
				const act = item.getAttribute("data-act");
				if (act === "settings") frappe.set_route("Form", "User", frappe.session.user);
				if (act === "theme") ua_accounting.shell.toggle_theme();
				if (act === "logout") frappe.app.logout();
			},
			{ side: "right" }
		);
	};

	// ---------------------------------------------------------------- function panel

	ua_accounting.shell.toggle_section = function (id) {
		const section = ua_accounting.shell.sections.find((s) => s.id === id);
		if (!section) return;
		if (section.page) {
			ua_accounting.shell.close_panel();
			frappe.set_route(section.page);
			return;
		}
		if (ua_accounting.shell.open_id === id) {
			ua_accounting.shell.close_panel();
			return;
		}
		ua_accounting.ui.close_menu();
		ua_accounting.shell.render_panel(section);
		ua_accounting.shell.open_id = id;
		const root = document.documentElement;
		root.classList.remove("ua-fpanel-open");
		void document.getElementById("ua-fpanel").offsetWidth;
		root.classList.add("ua-fpanel-open");
		$("#ua-sidebar .ua-sb-item[data-section]").each(function () {
			const on = $(this).attr("data-section") === id;
			$(this).toggleClass("is-open", on);
			if (this.tagName === "BUTTON") this.setAttribute("aria-expanded", on ? "true" : "false");
		});
		setTimeout(() => {
			const input = document.querySelector("#ua-fpanel [data-fp-search]");
			if (input) input.focus({ preventScroll: true });
		}, 40);
	};

	ua_accounting.shell.render_panel = function (section) {
		const route = frappe.get_route() || [];
		const current = route[0] === "List" || route[0] === "Tree" || route[0] === "Form" ? route[1] : route[0];
		let n = 0;
		const col = (c) => {
			const list = section[c.key] || [];
			if (!list.length) return "";
			const links = list
				.map((cmd, i) => {
					const key = ua_accounting.shell.fav_key_of_cmd(cmd);
					const on = ua_accounting.shell.is_fav(key);
					const cls =
						"ua-fp-link" +
						(c.key === "docs" && i === 0 ? " is-main" : "") +
						((cmd.page || cmd.doctype) === current ? " is-current" : "");
					return (
						`<a class="${cls}" href="#" data-cmd="${esc(ua_accounting.shell.cmd_id(cmd))}" style="--ua-n:${n++}">` +
						`<span class="ua-fp-text">${esc(__(cmd.label))}</span>` +
						`<button type="button" class="ua-fp-star${on ? " is-on" : ""}" data-fav="${esc(
							ua_accounting.shell.cmd_id(cmd)
						)}" aria-pressed="${on}" aria-label="${esc(on ? __("Прибрати з обраного") : __("Додати в обране"))}">${icon(
							"star",
							"ua-i-sm"
						)}</button></a>`
					);
				})
				.join("");
			return `<div class="ua-fp-col"><h3>${icon(c.icon)}${esc(__(c.title))}</h3>${links}</div>`;
		};
		const quick = (section.quick || [])
			.map(
				(cmd) =>
					`<button type="button" class="ua-btn ua-btn--sm" data-new="${esc(cmd.doctype)}">${icon("plus")}${esc(
						__(cmd.label)
					)}</button>`
			)
			.join("");
		$("#ua-fpanel").html(
			`<div class="ua-fp-head"><span class="ua-fp-icon">${icon(section.icon)}</span><div>` +
				`<div class="ua-fp-title" id="ua-fp-title">${esc(__(section.label))}</div><div class="ua-fp-sub">${esc(
					__(section.sub || "")
				)}</div></div>` +
				`<label class="ua-input ua-input--sm ua-fp-search">${icon("search", "ua-i-sm")}<input data-fp-search placeholder="${esc(
					__("Пошук у розділі «{0}»", [__(section.label)])
				)}" aria-label="${esc(__("Пошук у розділі"))}"></label>` +
				`<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-act="panel-close" aria-label="${esc(
					__("Закрити панель")
				)}" data-ua-tip="${esc(__("Закрити · Esc"))}">${icon("x")}</button></div>` +
				(quick ? `<div class="ua-fp-quick"><span class="ua-fp-quick-label">${esc(__("Створити:"))}</span>${quick}</div>` : "") +
				`<div class="ua-fp-body">${COLUMNS.map(col).join("")}</div>` +
				`<div class="ua-fp-foot">${icon("star", "ua-i-sm")}${esc(
					__("Наведіть на пункт і натисніть зірочку, щоб додати його в Обране")
				)}<span class="ua-row" style="margin-left:auto"><span class="ua-kbd">Esc</span>${esc(__("закрити"))}</span></div>`
		);
	};

	ua_accounting.shell.filter_panel = function (text) {
		const q = String(text || "")
			.trim()
			.toLowerCase();
		$("#ua-fpanel .ua-fp-link").each(function () {
			const t = $(this).find(".ua-fp-text").text().toLowerCase();
			$(this).toggle(!q || t.includes(q));
		});
		$("#ua-fpanel .ua-fp-col").each(function () {
			$(this).toggle($(this).find(".ua-fp-link:visible").length > 0 || !q);
		});
	};

	ua_accounting.shell.on_panel_click = function (e) {
		const star = e.target.closest("[data-fav]");
		if (star) {
			e.preventDefault();
			e.stopPropagation();
			const cmd = ua_accounting.shell.find_command(star.getAttribute("data-fav"));
			if (!cmd) return;
			const on = ua_accounting.shell.toggle_fav({
				key: ua_accounting.shell.fav_key_of_cmd(cmd),
				cmd: ua_accounting.shell.cmd_id(cmd),
				label: __(cmd.label),
			});
			star.classList.toggle("is-on", on);
			star.setAttribute("aria-pressed", on);
			star.setAttribute("aria-label", on ? __("Прибрати з обраного") : __("Додати в обране"));
			star.classList.add("pop");
			setTimeout(() => star.classList.remove("pop"), 200);
			return;
		}
		const nw = e.target.closest("[data-new]");
		if (nw) {
			ua_accounting.shell.close_panel();
			frappe.new_doc(nw.getAttribute("data-new"));
			return;
		}
		const link = e.target.closest("[data-cmd]");
		if (link) {
			e.preventDefault();
			const cmd = ua_accounting.shell.find_command(link.getAttribute("data-cmd"));
			ua_accounting.shell.close_panel();
			if (cmd) ua_accounting.shell.open(cmd);
		}
	};

	ua_accounting.shell.close_panel = function () {
		if (!ua_accounting.shell.open_id) return;
		ua_accounting.shell.open_id = null;
		document.documentElement.classList.remove("ua-fpanel-open");
		$("#ua-sidebar .ua-sb-item.is-open").removeClass("is-open").attr("aria-expanded", "false");
	};

	// ---------------------------------------------------------------- top bar: crumbs

	ua_accounting.shell.render_crumbs = function () {
		const route = frappe.get_route() || [];
		const parts = [];
		const kind = route[0];
		// a standard report: the route can start with the module (ua-documents/query-report/<name>)
		const report = route.indexOf("query-report") >= 0 ? route[route.indexOf("query-report") + 1] : null;
		const target = report
			? "query-report/" + report
			: kind === "List" || kind === "Form" || kind === "Tree"
			? route[1]
			: route[0];
		const section = ua_accounting.shell.section_of(target);
		if (section && section.id !== "home") {
			parts.push(
				`<a href="#" data-act="crumb-section" data-section="${esc(section.id)}">${esc(__(section.label))}</a>`
			);
		}
		if (kind === "Form" && route[1]) {
			parts.push(`<a href="/desk/${esc(frappe.router.slug(route[1]))}">${esc(__(route[1]))}</a>`);
			const frm = window.cur_frm && cur_frm.doctype === route[1] ? cur_frm : null;
			const label = frm
				? frm.is_new()
					? __("Новий документ")
					: ua_accounting.shell.doc_title(frm)
				: route[2] && !String(route[2]).startsWith("new-")
				? route[2]
				: __("Новий документ");
			if (!(frappe.get_meta(route[1]) || {}).issingle) parts.push(`<b>${esc(label)}</b>`);
		} else if ((kind === "List" || kind === "Tree") && route[1]) {
			parts.push(`<b>${esc(__(route[1]))}</b>`);
		} else if (kind === "ua-home") {
			parts.push(`<b>${esc(__("Головне"))}</b>`);
		} else {
			const cmd = Object.values(C).find((c) => c.page === (report ? target : kind));
			const title = cmd ? __(cmd.label) : report ? __(report) : ua_accounting.shell.current_label();
			if (title) parts.push(`<b>${esc(title)}</b>`);
		}
		$("#ua-topbar .ua-crumbs").html(parts.join(icon("chev-r")));
	};

	// documents show their number; catalogs show their title (never the hash name)
	ua_accounting.shell.doc_title = function (frm) {
		const meta = frappe.get_meta(frm.doctype);
		if (meta && meta.is_submittable) return frm.doc.name;
		if (meta && meta.issingle) return __(frm.doctype);
		const tf = meta && meta.title_field;
		return (tf && frm.doc[tf]) || frm.doc.name;
	};

	// ---------------------------------------------------------------- notifications (bell)

	ua_accounting.shell.refresh_bell = function () {
		frappe
			.xcall("frappe.client.get_count", {
				doctype: "Notification Log",
				filters: { for_user: frappe.session.user, read: 0 },
			})
			.then((count) => {
				$("#ua-topbar .ua-bell .ua-dot-badge").prop("hidden", !count);
				ua_accounting.shell.unread = count || 0;
			})
			.catch(() => {});
	};

	ua_accounting.shell.bell_menu = function (trigger) {
		const pop = ua_accounting.ui.menu(
			trigger,
			`<div class="ua-menu-label">${esc(__("Сповіщення"))}</div><div class="ua-bell-body">${ua_accounting.ui.skeleton_rows(
				3,
				[70]
			)}</div>`,
			(item) => {
				const name = item.getAttribute("data-name");
				const act = item.getAttribute("data-act");
				if (act === "read-all") {
					frappe
						.xcall("frappe.desk.doctype.notification_log.notification_log.mark_all_as_read")
						.then(ua_accounting.shell.refresh_bell);
					return;
				}
				const row = (pop.rows || []).find((r) => r.name === name);
				if (!row) return;
				frappe
					.xcall("frappe.desk.doctype.notification_log.notification_log.mark_as_read", { docname: row.name })
					.then(ua_accounting.shell.refresh_bell);
				if (row.document_type && row.document_name) frappe.set_route("Form", row.document_type, row.document_name);
			},
			{ align: "right", cls: "ua-bell-pop" }
		);
		if (!pop) return;
		const empty = () =>
			ua_accounting.ui.empty_html({ art: "bell", title: __("Сповіщень немає"), text: __("Нові події з’являться тут."), cls: "ua-empty--sm" });
		frappe
			.xcall("frappe.client.get_list", {
				doctype: "Notification Log",
				fields: ["name", "subject", "read", "creation", "document_type", "document_name"],
				filters: { for_user: frappe.session.user },
				order_by: "creation desc",
				limit_page_length: 10,
			})
			.then((rows) => {
				pop.rows = rows || [];
				const $b = $(pop).find(".ua-bell-body");
				if (!pop.rows.length) {
					$b.html(empty());
					return;
				}
				$b.html(
					pop.rows
						.map(
							(r) =>
								`<button class="ua-menu-item ua-note${r.read ? "" : " is-unread"}" data-name="${esc(r.name)}">` +
								`<span class="ua-two"><span>${esc(frappe.utils.html2text(r.subject || ""))}</span><small>${esc(
									frappe.datetime.prettyDate(r.creation)
								)}</small></span></button>`
						)
						.join("") +
						`<div class="ua-menu-sep"></div><button class="ua-menu-item" data-act="read-all">${icon("checks")}${esc(
							__("Позначити все прочитаним")
						)}</button>`
				);
			})
			.catch(() => $(pop).find(".ua-bell-body").html(empty()));
	};

	// ---------------------------------------------------------------- help: keyboard shortcuts

	ua_accounting.shell.open_help = function () {
		const keys = [
			["Ctrl K", __("Пошук і команди")],
			["Ctrl Enter", __("Провести і закрити")],
			["Ctrl S", __("Записати")],
			["Ins", __("Створити / додати рядок")],
			["/", __("Пошук у списку")],
			["Ctrl Shift ↑ ↓", __("Перемістити рядок таблиці")],
			["Esc", __("Закрити панель або вікно")],
		];
		ua_accounting.ui.dialog({
			title: __("Довідка"),
			width: 480,
			html:
				`<div class="ua-dialog-head"><div><div class="ua-dialog-title">${esc(__("Клавіші"))}</div>` +
				`<div class="ua-dialog-sub">${esc(__("Швидкі дії без миші"))}</div></div>` +
				`<button class="ua-btn ua-btn--ghost ua-btn--icon" data-close aria-label="${esc(__("Закрити"))}">${icon(
					"x"
				)}</button></div>` +
				`<div class="ua-dialog-body"><table class="ua-table ua-keys"><tbody>${keys
					.map(([k, t]) => `<tr><td>${k.split(" ").map((x) => `<span class="ua-kbd">${esc(x)}</span>`).join(" ")}</td><td>${esc(t)}</td></tr>`)
					.join("")}</tbody></table></div>` +
				`<div class="ua-dialog-foot"><span></span><div class="ua-right"><button class="ua-btn ua-btn--primary" data-close autofocus>${esc(
					__("Зрозуміло")
				)}</button></div></div>`,
		});
	};

	// ---------------------------------------------------------------- theme

	ua_accounting.shell.toggle_theme = function () {
		const next = document.documentElement.getAttribute("data-theme") === "dark" ? "Light" : "Dark";
		document.body.classList.add("theme-switching");
		document.documentElement.setAttribute("data-theme", next.toLowerCase());
		document.documentElement.setAttribute("data-theme-mode", next.toLowerCase());
		requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.remove("theme-switching")));
		$('#ua-sidebar [data-act="theme"]').html(icon(next === "Dark" ? "sun" : "moon"));
		// the user setting keeps the theme after a reload
		frappe.xcall("frappe.core.doctype.user.user.switch_theme", { theme: next }).catch(() => {});
	};

	// ---------------------------------------------------------------- Ctrl K: search and commands

	ua_accounting.shell.open_search = function () {
		ua_accounting.shell.close_panel();
		ua_accounting.ui.close_menu();
		if (document.querySelector(".ua-palette")) return;
		const d = ua_accounting.ui.dialog({
			title: __("Пошук і команди"),
			width: 600,
			html:
				`<div class="ua-palette"><div class="ua-palette-q"><label class="ua-input ua-input--lg">${icon("search")}` +
				`<input autofocus autocomplete="off" placeholder="${esc(
					__("Знайти документ, довідник, звіт або команду…")
				)}" aria-label="${esc(__("Пошук"))}"><span class="ua-kbd">Esc</span></label></div>` +
				`<div class="ua-dialog-body ua-palette-list"></div>` +
				`<div class="ua-dialog-foot ua-palette-foot"><span><span class="ua-kbd">↑</span> <span class="ua-kbd">↓</span> ${esc(
					__("вибір")
				)} <span class="ua-kbd">Enter</span> ${esc(__("відкрити"))}</span></div></div>`,
		});
		const input = d.box.querySelector("input");
		const list = d.box.querySelector(".ua-palette-list");
		let results = [];
		let seq = 0;

		const commands = [];
		ua_accounting.shell.sections.forEach((s) => {
			if (s.page) {
				commands.push({ t: __(s.label), s: __("Розділ"), ic: s.icon, run: () => frappe.set_route(s.page) });
				return;
			}
			commands.push({ t: __(s.label), s: __("Розділ"), ic: s.icon, run: () => ua_accounting.shell.toggle_section(s.id) });
			s.groups.forEach((g) =>
				g.items.forEach((c) => {
					if (commands.some((x) => x.cmd === c)) return;
					const col = COLUMNS.find((x) => x.key === g.key);
					commands.push({ t: __(c.label), s: __(s.label), ic: col ? col.icon : "file", cmd: c, run: () => ua_accounting.shell.open(c) });
				})
			);
			(s.quick || []).forEach((c) => {
				const t = __("Створити: {0}", [__(c.label)]);
				if (commands.some((x) => x.t === t)) return;
				commands.push({ t, s: __("Команда"), ic: "plus", run: () => frappe.new_doc(c.doctype) });
			});
		});

		const mark = (text, q) => {
			const i = q ? text.toLowerCase().indexOf(q) : -1;
			if (i < 0) return esc(text);
			return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length));
		};

		const draw = (q, docs, loading) => {
			const cmds = commands.filter((x) => !q || x.t.toLowerCase().includes(q)).slice(0, q ? 8 : 9);
			results = cmds.concat(docs || []);
			if (!results.length && !loading) {
				list.innerHTML = ua_accounting.ui.empty_html({
					art: "search",
					title: __("Нічого не знайдено"),
					text: __("Спробуйте інше слово або номер документа."),
					cls: "ua-empty--sm",
				});
				return;
			}
			const row = (x, i) =>
				`<button class="ua-menu-item${i === 0 ? " is-active" : ""}" data-i="${i}">${icon(x.ic)}<span class="ua-two"><span>${mark(
					x.t,
					q
				)}</span>${x.sub ? `<small>${esc(x.sub)}</small>` : ""}</span><span class="ua-meta">${esc(x.s)}</span></button>`;
			let html = "";
			if (cmds.length) {
				html += `<div class="ua-menu-label">${esc(q ? __("Команди") : __("Розділи і команди"))}</div>`;
				html += cmds.map(row).join("");
			}
			if (docs && docs.length) {
				html += `<div class="ua-menu-label">${esc(__("Документи"))}</div>`;
				html += docs.map((x, j) => row(x, cmds.length + j)).join("");
			}
			if (loading) html += ua_accounting.ui.skeleton_rows(2, [60]);
			list.innerHTML = html;
		};

		const search_docs = (q) => {
			const my = ++seq;
			if (q.length < 2) {
				draw(q, []);
				return;
			}
			draw(q, [], true);
			const doctypes = ua_accounting.ui.DOCUMENTS.filter((dt) => frappe.model.can_read(dt));
			Promise.all(
				doctypes.map((dt) =>
					frappe.db
						.get_list(dt, {
							fields: ["name", "posting_date"],
							filters: [[dt, "name", "like", `%${q}%`]],
							limit: 3,
							order_by: "posting_date desc",
						})
						.then((rows) => rows.map((r) => ({ dt, r })))
						.catch(() => [])
				)
			).then((all) => {
				if (my !== seq) return;
				const docs = [].concat(...all).slice(0, 8).map(({ dt, r }) => ({
					t: r.name,
					sub: r.posting_date ? frappe.datetime.str_to_user(r.posting_date) : "",
					s: __(dt),
					ic: "file",
					run: () => frappe.set_route("Form", dt, r.name),
				}));
				draw(q, docs);
			});
		};

		let timer = null;
		input.addEventListener("input", () => {
			const q = input.value.trim().toLowerCase();
			draw(q, []);
			clearTimeout(timer);
			timer = setTimeout(() => search_docs(input.value.trim()), 250);
		});
		input.addEventListener("keydown", (e) => {
			const all = [].slice.call(list.querySelectorAll(".ua-menu-item"));
			let i = all.findIndex((a) => a.classList.contains("is-active"));
			if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				e.preventDefault();
				if (!all.length) return;
				if (all[i]) all[i].classList.remove("is-active");
				i = (i + (e.key === "ArrowDown" ? 1 : -1) + all.length) % all.length;
				all[i].classList.add("is-active");
				all[i].scrollIntoView({ block: "nearest" });
			}
			if (e.key === "Enter" && all[i]) {
				e.preventDefault();
				all[i].click();
			}
		});
		list.addEventListener("click", (e) => {
			const item = e.target.closest(".ua-menu-item");
			if (!item) return;
			const x = results[+item.getAttribute("data-i")];
			d.close();
			if (x) x.run();
		});
		draw("", []);
	};

	// ---------------------------------------------------------------- start route, active section

	ua_accounting.shell.on_route = function () {
		const route = frappe.get_route() || [];
		const first = route[0];
		// Frappe's own start pages are replaced by the home page.
		// an empty route at startup is not the start page unless the URL says so
		const path = location.pathname.replace(/\/+$/, "");
		const is_start =
			(!first && ["/desk", "/app", ""].includes(path)) ||
			// System Manager may still open a concrete workspace
			(first === "Workspaces" && (route.length < 2 || !frappe.user.has_role("System Manager"))) ||
			(typeof first === "string" && first.toLowerCase() === "бухгалтерія") ||
			first === "ua-core";
		if (is_start) {
			frappe.set_route("ua-home");
			return;
		}
		ua_accounting.shell.close_panel();
		ua_accounting.ui.close_menu();
		ua_accounting.shell.mark_active();
		ua_accounting.shell.render_crumbs();
		ua_accounting.shell.track();
	};

	ua_accounting.shell.mark_active = function () {
		const route = frappe.get_route() || [];
		const target = route[0] === "List" || route[0] === "Form" || route[0] === "Tree" ? route[1] : route[0];
		const s = ua_accounting.shell.section_of(target);
		$("#ua-sidebar [data-section]").each(function () {
			const on = !!s && $(this).attr("data-section") === s.id;
			$(this).toggleClass("is-active", on);
			if (on) this.setAttribute("aria-current", "page");
			else this.removeAttribute("aria-current");
		});
	};

	ua_accounting.shell.is_ua_user = function () {
		return UA_ROLES.some((r) => frappe.user.has_role(r));
	};

	ua_accounting.shell.setup_keys = function () {
		// Ctrl K: our search. Frappe v16 binds Ctrl K to its awesome bar: that handler is replaced,
		// so one key press opens one dialog.
		frappe.ui.keys.handlers["ctrl+k"] = [];
		frappe.ui.keys.standard_shortcuts = (frappe.ui.keys.standard_shortcuts || []).filter((s) => s.shortcut !== "ctrl+k");
		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+k",
			action: (e) => {
				if (e) e.preventDefault();
				ua_accounting.shell.open_search();
				return false;
			},
			description: __("Пошук і команди"),
			ignore_inputs: true,
		});
	};

	$(document).on("startup", function () {
		if (!ua_accounting.shell.is_ua_user()) return;
		// a fresh site must show the setup wizard, not our shell
		if (frappe.boot.sysdefaults && !frappe.boot.sysdefaults.setup_complete) return;
		document.body.classList.add("ua-shell");
		ua_accounting.shell.build();
		ua_accounting.shell.setup_keys();
		frappe.router.on("change", ua_accounting.shell.on_route);
		ua_accounting.shell.on_route();
		ua_accounting.shell.load_orgs();
		ua_accounting.shell.refresh_bell();
		setInterval(ua_accounting.shell.refresh_bell, 60000);
		if (frappe.realtime) frappe.realtime.on("notification", ua_accounting.shell.refresh_bell);
	});

	// the form title changes after the route: update the last crumb
	$(document).on("form-refresh", () => ua_accounting.shell.render_crumbs && $("#ua-topbar").length && ua_accounting.shell.render_crumbs());
})();
