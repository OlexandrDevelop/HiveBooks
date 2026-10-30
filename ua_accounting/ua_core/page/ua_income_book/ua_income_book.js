frappe.pages["ua-income-book"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: "Книга обліку доходів", single_column: true});
	const year = new Date().getFullYear();
	const org = page.add_field({fieldname: "organization", label: "Організація", fieldtype: "Link", options: "UA Organization",
		default: ua_accounting.shell && ua_accounting.shell.current_org && (ua_accounting.shell.current_org() || {}).name,
		change: run});
	const from = page.add_field({fieldname: "date_from", label: "З", fieldtype: "Date", default: `${year}-01-01`, change: run});
	const to = page.add_field({fieldname: "date_to", label: "По", fieldtype: "Date", default: `${year}-12-31`, change: run});
	const $body = $(wrapper).find(".layout-main-section");
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const money = (v) => format_currency(v, "UAH");

	function run() {
		const args = {organization: org.get_value(), date_from: from.get_value(), date_to: to.get_value()};
		if (!args.organization || !args.date_from || !args.date_to) return;
		frappe.xcall("ua_accounting.api.get_income_book", args).then((book) => {
			const rows = book.rows.map((r, i) => `<tr><td>${i + 1}</td><td>${frappe.datetime.str_to_user(r.posting_date)}</td>
				<td>${esc(r.document_description)}</td><td class="text-right">${money(r.income_amount)}</td></tr>`).join("");
			const quarters = book.quarters.map((q) => `<tr><td colspan="3">Разом за ${q.quarter} квартал</td>
				<td class="text-right">${money(q.income)}</td></tr>`).join("");
			$body.html(`<div class="ua-card"><h2>Книга обліку доходів</h2>
				<table class="table table-bordered"><thead><tr><th>№</th><th>Дата</th><th>Відомості про документ</th>
				<th class="text-right">Сума доходу</th></tr></thead><tbody>${rows}${quarters}
				<tr><td colspan="3"><b>Разом за період</b></td><td class="text-right"><b>${money(book.total_income)}</b></td></tr>
				</tbody></table></div>`);
		});
	}
	$body.html(`<div class="ua-card"><h2>Книга обліку доходів</h2><p>Оберіть організацію та період.</p></div>`);
	setTimeout(run, 300);
};
