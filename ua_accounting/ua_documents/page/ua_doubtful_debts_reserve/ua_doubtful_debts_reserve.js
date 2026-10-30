// Calculation of the reserve of doubtful debts: one row per settlement document of a customer.
frappe.pages["ua-doubtful-debts-reserve"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Розрахунок резерву сумнівних боргів"),
		single_column: true,
	});
	const query = frappe.utils.get_query_params();
	const organization = page.add_field({
		fieldname: "organization",
		label: __("Організація"),
		fieldtype: "Link",
		options: "UA Organization",
		default: query.organization,
		change: () => run(),
	});
	const date = page.add_field({
		fieldname: "date",
		label: __("Дата"),
		fieldtype: "Date",
		default: query.date || frappe.datetime.get_today(),
		change: () => run(),
	});
	const method = page.add_field({
		fieldname: "method",
		label: __("Метод резерву сумнівних боргів"),
		fieldtype: "Select",
		options: [
			"",
			"За класифікацією боргів",
			"За коефіцієнтом сумнівності",
			"За абсолютною сумою сумнівної заборгованості",
		].join("\n"),
		change: () => run(),
	});
	const $body = $('<div class="ua-reserve-body"></div>').appendTo(page.main);
	const num = (v) => format_number(v || 0, null, 2);
	const esc = frappe.utils.escape_html;

	function run() {
		const org = organization.get_value();
		const on = date.get_value();
		if (!org || !on) return;
		frappe
			.call({
				method: "ua_accounting.api.provisions.calculate_doubtful",
				args: { organization: org, date: on, method: method.get_value() || undefined },
			})
			.then((r) => render(r.message));
	}

	function render(res) {
		const rows = res.rows
			.map(
				(r) => `<tr>
				<td>${esc(r.counterparty_title || r.counterparty)}</td>
				<td>${esc(r.contract_title || r.contract)}</td>
				<td>${esc(r.settlement_doc)}</td>
				<td class="text-right">${num(r.debt)}</td>
				<td class="text-right">${r.overdue_days}</td>
				<td class="text-right">${num(r.percent)}</td>
				<td class="text-right">${num(r.reserve)}</td></tr>`
			)
			.join("");
		const debt = res.rows.reduce((a, r) => a + r.debt, 0);
		$body.html(`<table class="table table-bordered ua-num">
			<thead><tr>
				<th>${__("Контрагент")}</th><th>${__("Договір")}</th><th>${__("Документ розрахунків")}</th>
				<th class="text-right">${__("Заборгованість")}</th><th class="text-right">${__("Днів прострочення")}</th>
				<th class="text-right">${__("Відсоток")}</th><th class="text-right">${__("Резерв")}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
			<tfoot><tr><th colspan="3">${__("Усього")}</th><th class="text-right">${num(debt)}</th><th></th><th></th>
				<th class="text-right">${num(res.total)}</th></tr></tfoot></table>`);
	}

	run();
};
