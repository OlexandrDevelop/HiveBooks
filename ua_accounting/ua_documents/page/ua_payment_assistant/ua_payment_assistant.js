// Payment assistant (1C «Помічник оплати»): supplier invoices and taxes that are due, and payment orders from them.
// Data and actions: ua_accounting.api.payment_assistant (accounting/payment_assistant.py).
frappe.pages["ua-payment-assistant"].on_page_load = function (wrapper) {
	const API = "ua_accounting.api.payment_assistant.";
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Помічник оплати"), single_column: true });
	const query = Object.assign({}, frappe.utils.get_query_params(), frappe.route_options || {});
	frappe.route_options = null;
	const shell_org = ua_accounting.shell.current_org ? ua_accounting.shell.current_org() : null;
	const esc = frappe.utils.escape_html;
	const money = (v) => ua_accounting.ui.money(v || 0);
	const field = (opts) => page.add_field(Object.assign({ change: () => run() }, opts));

	const organization = field({
		fieldname: "organization", label: __("Організація"), fieldtype: "Link", options: "UA Organization",
		default: query.organization || (shell_org && shell_org.name),
		change: () => {
			bank_account.set_value("");
			default_bank().then(run);
		},
	});
	const bank_account = field({
		fieldname: "bank_account", label: __("Банківський рахунок"), fieldtype: "Link", options: "UA Bank Account",
		default: query.bank_account,
		get_query: () => ({ filters: { organization: organization.get_value() } }),
	});
	const date = field({ fieldname: "date", label: __("Дата"), fieldtype: "Date", default: query.date || frappe.datetime.get_today() });
	const horizon = field({
		fieldname: "horizon_days", label: __("Горизонт, днів"), fieldtype: "Int", default: query.horizon_days || 0,
	});
	const $body = $('<div class="ua-pa-body"></div>').appendTo(page.main);
	let data = { suppliers: [], taxes: [], total: 0 };

	const default_bank = () => {
		const org = organization.get_value();
		if (!org || bank_account.get_value()) return Promise.resolve();
		return frappe.db.get_value("UA Bank Account", { organization: org, is_default: 1 }, "name").then((r) => {
			if (r.message && r.message.name) bank_account.set_value(r.message.name);
		});
	};

	function run() {
		const org = organization.get_value();
		const on = date.get_value();
		if (!org || !on) return render();
		frappe
			.call({ method: API + "get_proposals", args: { organization: org, date: on, horizon_days: horizon.get_value() || 0 } })
			.then((r) => {
				data = r.message;
				render();
			});
	}

	function supplier_rows() {
		return data.suppliers
			.map(
				(r, i) => `<tr>
				<td><input type="checkbox" class="ua-pa-pick" data-kind="supplier" data-i="${i}" checked></td>
				<td>${esc(r.counterparty_title || r.counterparty)}${r.no_iban ? ` <span class="ua-badge ua-badge--cancelled">${__("Немає IBAN")}</span>` : ""}</td>
				<td>${esc(r.doc)}</td>
				<td>${esc(frappe.datetime.str_to_user(r.doc_date))}</td>
				<td>${esc(frappe.datetime.str_to_user(r.due_date))}</td>
				<td class="text-right">${r.overdue_days ? `<span class="ua-badge ua-badge--cancelled">${__("Прострочено")}: ${r.overdue_days}</span>` : ""}</td>
				<td class="text-right"><input type="number" step="0.01" min="0" class="ua-pa-amount" data-kind="supplier" data-i="${i}" value="${r.amount_due}"></td>
				<td class="text-right ua-num">${money(r.vat_amount)}</td></tr>`
			)
			.join("");
	}

	function tax_rows() {
		return data.taxes
			.map(
				(r, i) => `<tr>
				<td><input type="checkbox" class="ua-pa-pick" data-kind="tax" data-i="${i}" checked></td>
				<td>${esc(r.title)}${r.no_account ? ` <span class="ua-badge ua-badge--cancelled">${__("Немає рахунку для сплати")}</span>` : ""}</td>
				<td>${esc(r.budget_code)}</td>
				<td>${esc(frappe.datetime.str_to_user(r.due_date))}</td>
				<td class="text-right">${r.overdue_days ? `<span class="ua-badge ua-badge--cancelled">${__("Прострочено")}: ${r.overdue_days}</span>` : ""}</td>
				<td class="text-right"><input type="number" step="0.01" min="0" class="ua-pa-amount" data-kind="tax" data-i="${i}" value="${r.amount}"></td></tr>`
			)
			.join("");
	}

	function render() {
		const empty = (cols) => `<tr><td colspan="${cols}" class="text-muted">${__("Немає даних")}</td></tr>`;
		$body.html(`
			<div class="ua-card"><h3>${__("Постачальники")}</h3>
			<table class="table table-bordered ua-table"><thead><tr><th></th><th>${__("Постачальник")}</th><th>${__("Документ")}</th>
				<th>${__("Дата документа")}</th><th>${__("Оплатити до")}</th><th class="text-right">${__("Прострочення")}</th>
				<th class="text-right">${__("Сума до сплати")}</th><th class="text-right">${__("У т.ч. ПДВ")}</th></tr></thead>
			<tbody>${supplier_rows() || empty(8)}</tbody></table></div>
			<div class="ua-card"><h3>${__("Податки")}</h3>
			<table class="table table-bordered ua-table"><thead><tr><th></th><th>${__("Податок")}</th><th>${__("КБК")}</th>
				<th>${__("Строк сплати")}</th><th class="text-right">${__("Прострочення")}</th>
				<th class="text-right">${__("Сума до сплати")}</th></tr></thead>
			<tbody>${tax_rows() || empty(6)}</tbody></table></div>
			<p class="ua-pa-total"><b>${__("Разом до сплати")}: <span class="ua-num">${money(data.total)}</span></b></p>`);
	}

	function chosen() {
		const items = [];
		$body.find(".ua-pa-pick:checked").each(function () {
			const kind = this.getAttribute("data-kind");
			const i = +this.getAttribute("data-i");
			const row = (kind === "tax" ? data.taxes : data.suppliers)[i];
			const amount = parseFloat($body.find(`.ua-pa-amount[data-kind=${kind}][data-i=${i}]`).val());
			items.push(Object.assign({}, row, { kind, amount }));
		});
		return items;
	}

	function create() {
		const items = chosen();
		if (!items.length) return frappe.msgprint(__("Оберіть рядки для оплати"));
		if (!bank_account.get_value()) return frappe.msgprint(__("Вкажіть банківський рахунок"));
		frappe.confirm(__("Створити платіжні доручення: {0}?", [items.length]), () => {
			frappe
				.call({
					method: API + "create_orders",
					args: {
						organization: organization.get_value(), bank_account: bank_account.get_value(), items,
						date: date.get_value(),
					},
				})
				.then((r) => {
					const res = r.message;
					const skipped = res.skipped.map((s) => `<li>${esc(s.reason)}</li>`).join("");
					frappe.msgprint({
						title: __("Помічник оплати"),
						message: `${__("Створено платіжних доручень: {0}", [res.created.length])}` + (skipped ? `<ul>${skipped}</ul>` : ""),
					});
					run();
				});
		});
	}

	page.set_primary_action(__("Створити платіжні доручення"), create);
	default_bank().then(run);
};
