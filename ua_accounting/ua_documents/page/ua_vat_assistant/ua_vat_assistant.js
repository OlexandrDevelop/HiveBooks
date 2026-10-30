// VAT assistant (1C «Помічник ПДВ»): tax invoices to issue and to register, deadlines, comparison with ЄРПН.
// Data and actions: ua_accounting.api.vat_assistant (accounting/vat_assistant.py).
frappe.pages["ua-vat-assistant"].on_page_load = function (wrapper) {
	const API = "ua_accounting.api.vat_assistant.";
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Помічник ПДВ"), single_column: true });
	const query = Object.assign({}, frappe.utils.get_query_params(), frappe.route_options || {});
	frappe.route_options = null;
	const shell_org = ua_accounting.shell.current_org ? ua_accounting.shell.current_org() : null;
	const esc = frappe.utils.escape_html;
	const money = (v) => ua_accounting.ui.money(v || 0);
	const day = (iso) => (iso ? frappe.datetime.str_to_user(iso) : "");
	const field = (opts) => page.add_field(Object.assign({ change: () => run() }, opts));

	const today = frappe.datetime.get_today();
	const month_start = frappe.datetime.month_start();
	const organization = field({
		fieldname: "organization", label: __("Організація"), fieldtype: "Link", options: "UA Organization",
		default: query.organization || (shell_org && shell_org.name),
	});
	const date_from = field({ fieldname: "date_from", label: __("Період з"), fieldtype: "Date", default: query.date_from || month_start });
	const date_to = field({ fieldname: "date_to", label: __("Період по"), fieldtype: "Date", default: query.date_to || frappe.datetime.month_end() });
	const as_of = field({ fieldname: "as_of", label: __("На дату"), fieldtype: "Date", default: query.as_of || today });
	const $body = $('<div class="ua-va-body"></div>').appendTo(page.main);
	let data = null;
	let comparison = null;

	function run() {
		const org = organization.get_value();
		if (!org || !date_from.get_value() || !date_to.get_value() || !as_of.get_value()) return render();
		frappe
			.call({
				method: API + "get_status",
				args: { organization: org, date_from: date_from.get_value(), date_to: date_to.get_value(), as_of: as_of.get_value() },
			})
			.then((r) => {
				data = r.message;
				render();
			});
	}

	const empty = (cols) => `<tr><td colspan="${cols}" class="text-muted">${__("Немає даних")}</td></tr>`;

	function issue_rows() {
		return ((data && data.to_issue) || [])
			.map(
				(r, i) => `<tr><td>${esc(r.basis)}</td><td>${esc(r.counterparty_title || r.counterparty)}</td><td>${day(r.date)}</td>
				<td class="text-right ua-num">${money(r.base)}</td><td class="text-right ua-num">${money(r.vat)}</td>
				<td class="text-right ua-num">${money(r.total)}</td><td>${day(r.deadline)}</td>
				<td><button class="btn btn-xs btn-default" data-act="issue" data-i="${i}">${__("Створити податкову накладну")}</button></td></tr>`
			)
			.join("");
	}

	function register_rows() {
		return ((data && data.to_register) || [])
			.map(
				(r) => `<tr><td><a href="/desk/ua-tax-invoice/${encodeURIComponent(r.tax_invoice)}">${esc(r.tax_invoice)}</a></td>
				<td>${day(r.date)}</td><td>${esc(r.counterparty_title || r.counterparty)}</td>
				<td class="text-right ua-num">${money(r.vat)}</td><td>${esc(__(r.erpn_status))}</td><td>${day(r.deadline)}</td>
				<td>${
					r.overdue_days
						? `<span class="ua-badge ua-badge--cancelled">${__("Прострочено")}: ${r.overdue_days}</span>`
						: __("Залишилось днів: {0}", [r.days_left])
				}</td>
				<td class="text-right ua-num">${r.penalty ? `${money(r.penalty)} (${r.penalty_pct}%)` : ""}</td></tr>`
			)
			.join("");
	}

	function comparison_html() {
		if (!comparison) return "";
		const kinds = {
			missing_in_books: __("Є в ЄРПН, немає в обліку"),
			missing_in_erpn: __("Є в обліку, немає в ЄРПН"),
			amount_differs: __("Суми відрізняються"),
		};
		const sides = (s) => (s ? `${money(s.base)} / ${money(s.vat)}` : "—");
		const rows = comparison.mismatches
			.map((m) => `<tr><td>${esc(kinds[m.kind] || m.kind)}</td><td>${esc(m.number)}</td><td>${day(m.date)}</td><td>${sides(m.ours)}</td><td>${sides(m.theirs)}</td></tr>`)
			.join("");
		return `<p>${__("Збігається: {0}", [comparison.matched])}</p>
			<table class="table table-bordered ua-table"><thead><tr><th>${__("Розбіжність")}</th><th>${__("Номер")}</th><th>${__("Дата")}</th>
			<th>${__("В обліку: база / ПДВ")}</th><th>${__("В ЄРПН: база / ПДВ")}</th></tr></thead><tbody>${rows || empty(5)}</tbody></table>`;
	}

	function render() {
		const d = data || { consolidated: { base: 0, vat: 0, count: 0 }, deadlines: {} };
		$body.html(`
			<div class="ua-card"><h3>${__("Виписати податкові накладні")}</h3>
			<table class="table table-bordered ua-table"><thead><tr><th>${__("Документ")}</th><th>${__("Покупець")}</th><th>${__("Дата")}</th>
				<th class="text-right">${__("База")}</th><th class="text-right">${__("ПДВ")}</th><th class="text-right">${__("Разом")}</th>
				<th>${__("Виписати до")}</th><th></th></tr></thead><tbody>${issue_rows() || empty(8)}</tbody></table>
			<p>${__("Зведена податкова накладна наприкінці місяця: документів {0}, база {1}, ПДВ {2}", [
				d.consolidated.count, money(d.consolidated.base), money(d.consolidated.vat)])}</p></div>
			<div class="ua-card"><h3>${__("Зареєструвати в ЄРПН")}</h3>
			<table class="table table-bordered ua-table"><thead><tr><th>${__("Податкова накладна")}</th><th>${__("Дата")}</th><th>${__("Покупець")}</th>
				<th class="text-right">${__("ПДВ")}</th><th>${__("Статус ЄРПН")}</th><th>${__("Зареєструвати до")}</th><th>${__("Строк")}</th>
				<th class="text-right">${__("Штраф")}</th></tr></thead><tbody>${register_rows() || empty(8)}</tbody></table></div>
			<div class="ua-card"><h3>${__("Строки")}</h3>
			<p>${__("Декларація з ПДВ")}: <b>${day(d.deadlines.declaration)}</b></p>
			<p>${__("Сплата ПДВ")}: <b>${day(d.deadlines.payment)}</b></p></div>
			<div class="ua-card"><h3>${__("Звірка з ЄРПН")}</h3>
			<p class="text-muted">${__("Вставте реєстр з ЄРПН: рядок на документ, поля через «;» — номер; дата (РРРР-ММ-ДД); ІПН; база; ПДВ")}</p>
			<textarea class="form-control ua-va-register" rows="5"></textarea>
			<p><button class="btn btn-default btn-sm" data-act="compare">${__("Звірити")}</button></p>${comparison_html()}</div>`);
	}

	function parse_register(text) {
		return text
			.split("\n")
			.map((l) => l.trim())
			.filter(Boolean)
			.map((l) => {
				const p = l.split(";").map((x) => x.trim());
				return { number: p[0], date: p[1], counterparty_ipn: p[2], base: parseFloat((p[3] || "0").replace(",", ".")), vat: parseFloat((p[4] || "0").replace(",", ".")) };
			});
	}

	$body.on("click", "[data-act=issue]", function () {
		const row = data.to_issue[+this.getAttribute("data-i")];
		frappe.call({ method: "ua_accounting.api.tax_invoice.create_on_basis", args: { basis_doctype: row.basis_doctype, basis_name: row.basis, direction: "Видана" } }).then((r) => {
			frappe.set_route("Form", "UA Tax Invoice", r.message);
		});
	});
	$body.on("click", "[data-act=compare]", function () {
		frappe
			.call({
				method: API + "compare_with_erpn",
				args: {
					organization: organization.get_value(), direction: "Видана", rows: parse_register($body.find(".ua-va-register").val() || ""),
					date_from: date_from.get_value(), date_to: date_to.get_value(),
				},
			})
			.then((r) => {
				const text = $body.find(".ua-va-register").val();
				comparison = r.message;
				render();
				$body.find(".ua-va-register").val(text);
			});
	});
	run();
};
