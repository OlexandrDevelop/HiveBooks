// Manager monitor (1C «Монітор керівника»): money, debts, sales and profit.
// Data: ua_accounting.api.monitor.get_widgets (accounting/monitor.py).
frappe.pages["ua-manager-monitor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Монітор керівника"), single_column: true });
	const query = Object.assign({}, frappe.utils.get_query_params(), frappe.route_options || {});
	frappe.route_options = null;
	const shell_org = ua_accounting.shell.current_org ? ua_accounting.shell.current_org() : null;
	const esc = frappe.utils.escape_html;
	const money = (v) => ua_accounting.ui.money(v || 0);
	const field = (opts) => page.add_field(Object.assign({ change: () => run() }, opts));

	const organization = field({
		fieldname: "organization", label: __("Організація"), fieldtype: "Link", options: "UA Organization",
		default: query.organization || (shell_org && shell_org.name),
	});
	const date_from = field({ fieldname: "date_from", label: __("Період з"), fieldtype: "Date", default: query.date_from || frappe.datetime.month_start() });
	const date_to = field({ fieldname: "date_to", label: __("Період по"), fieldtype: "Date", default: query.date_to || frappe.datetime.get_today() });
	const $body = $('<div class="ua-mm-body"></div>').appendTo(page.main);
	let data = null;

	function run() {
		const org = organization.get_value();
		if (!org || !date_from.get_value() || !date_to.get_value()) return render();
		frappe
			.call({ method: "ua_accounting.api.monitor.get_widgets", args: { organization: org, date_from: date_from.get_value(), date_to: date_to.get_value() } })
			.then((r) => {
				data = r.message;
				render();
			});
	}

	const line = (label, value) => `<tr><td>${label}</td><td class="text-right ua-num">${money(value)}</td></tr>`;
	const card = (title, total, body) => `<div class="ua-card ua-mm-card"><h3>${title}</h3>
		<div class="ua-kpi-val ua-num">${money(total)}<span class="ua-cur">₴</span></div>${body}</div>`;

	function top(rows) {
		const titles = (data && data.titles) || {};
		return `<table class="table table-bordered ua-table"><tbody>${
			rows.map((r) => line(esc(titles[r.counterparty] || r.counterparty), r.amount)).join("") ||
			`<tr><td class="text-muted">${__("Немає даних")}</td></tr>`
		}</tbody></table>`;
	}

	function render() {
		const d = data || {
			money: {}, receivable: { top: [] }, payable: { top: [] }, sales: { by_month: [] }, profit: {},
		};
		const months = d.sales.by_month.map((m) => line(esc(m.month), m.amount)).join("");
		$body.html(`<div class="ua-mm-grid">
			${card(__("Гроші"), d.money.total, `<table class="table table-bordered ua-table"><tbody>${line(__("Каса"), d.money.cash)}${line(__("Банк"), d.money.bank)}</tbody></table>`)}
			${card(__("Дебіторська заборгованість"), d.receivable.total, top(d.receivable.top))}
			${card(__("Кредиторська заборгованість"), d.payable.total, top(d.payable.top))}
			${card(__("Продажі"), d.sales.total, `<table class="table table-bordered ua-table"><tbody>${months}</tbody></table>`)}
			${card(__("Прибуток"), d.profit.profit, `<table class="table table-bordered ua-table"><tbody>${line(__("Доходи"), d.profit.income)}${line(__("Витрати"), d.profit.expenses)}</tbody></table>`)}
		</div>`);
	}
	render();
	run();
};
