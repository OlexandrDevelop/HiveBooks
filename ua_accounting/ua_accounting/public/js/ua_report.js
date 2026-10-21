// Shared client of the accounting reports (OSV, OSV by account, account card).
// Each report page only gives a config; the filters, table, drill-down, print and
// Excel export live here. The server returns one "table model" for every report
// (see ua_accounting/reporting/model.py).
frappe.provide("ua_accounting.reports");

const API = "ua_accounting.reporting.api.";

ua_accounting.reports.PAGES = {
	osv: "ua-osv",
	osv_account: "ua-osv-account",
	account_card: "ua-account-card",
};

// Fields that only one report uses. type: check | select
ua_accounting.reports.CONFIG = {
	osv: {
		report: "osv",
		title: __("Оборотно-сальдова відомість"),
		accounts: "multi",
		fields: [
			{ key: "by_subaccounts", type: "check", label: __("По субрахунках"), value: 0 },
			{
				key: "subconto_levels",
				type: "select",
				label: __("Розгортати по субконто"),
				options: ["0", "1", "2", "3"],
				value: "0",
			},
			{ key: "show_quantity", type: "check", label: __("Кількість"), value: 0 },
			{ key: "show_currency", type: "check", label: __("Валютна сума"), value: 0 },
			{ key: "show_zero", type: "check", label: __("Нульові рядки"), value: 0 },
		],
	},
	osv_account: {
		report: "osv_account",
		title: __("ОСВ по рахунку"),
		accounts: "single",
		levels: true,
		fields: [
			{ key: "by_subaccounts", type: "check", label: __("По субрахунках"), value: 1 },
			{ key: "show_quantity", type: "check", label: __("Кількість"), value: 1 },
			{ key: "show_currency", type: "check", label: __("Валютна сума"), value: 1 },
			{ key: "show_zero", type: "check", label: __("Нульові рядки"), value: 0 },
		],
	},
	account_card: {
		report: "account_card",
		title: __("Картка рахунку"),
		accounts: "multi",
		fields: [
			{ key: "show_quantity", type: "check", label: __("Кількість"), value: 1 },
			{ key: "show_currency", type: "check", label: __("Валютна сума"), value: 1 },
		],
	},
};

// ------------------------------------------------------------------ helpers

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

function fmt_number(value, precision) {
	if (value === null || value === undefined || value === "" || Math.abs(value) < 0.0000001) return "";
	return format_number(value, null, precision);
}

function period_range(unit, shift, ref) {
	const m = moment(ref || undefined);
	const start = m.clone().startOf(unit).add(shift, unit === "quarter" ? "quarters" : unit + "s");
	const end = start.clone().endOf(unit);
	return [start.format("YYYY-MM-DD"), end.format("YYYY-MM-DD")];
}

// ------------------------------------------------------------------ chips for many values

// A Link field that collects values as chips. doctype=null: free text (Enter adds).
ua_accounting.reports.MultiLink = class MultiLink {
	constructor(parent, opts) {
		this.doctype = opts.doctype;
		this.on_change = opts.on_change || (() => {});
		this.values = [];
		this.titles = {};
		this.$wrap = $('<div class="ua-multi"></div>').appendTo(parent);
		this.$chips = $('<div class="ua-chips"></div>').appendTo(this.$wrap);
		this.label = opts.label;
		this.placeholder = opts.placeholder || __("Додати…");
		this.get_query = opts.get_query;
		this.$input_wrap = $('<div class="ua-multi-input"></div>').appendTo(this.$wrap);
		this.make_input();
	}

	make_input() {
		this.$input_wrap.empty();
		const df = {
			fieldtype: this.doctype ? "Link" : "Data",
			options: this.doctype || undefined,
			fieldname: "ua_" + frappe.utils.get_random(6),
			label: this.label,
			placeholder: this.placeholder,
		};
		if (this.get_query) df.get_query = this.get_query;
		this.control = frappe.ui.form.make_control({ df, parent: this.$input_wrap, render_input: true });
		this.control.refresh();
		const add = () => {
			const v = (this.control.get_value() || "").trim();
			if (v) {
				this.add([v]);
				this.control.set_value("");
			}
		};
		if (this.doctype) {
			this.control.$input.on("awesomplete-selectcomplete", add);
		} else {
			this.control.$input.on("keydown", (e) => {
				if (e.key === "Enter") {
					e.preventDefault();
					add();
				}
			});
		}
	}

	set_doctype(doctype) {
		// the subconto type changed: old values do not fit
		this.values = [];
		this.titles = {};
		this.doctype = doctype;
		this.make_input();
		this.render();
	}

	async add(values, silent) {
		const fresh = values.filter((v) => !this.values.includes(v));
		// "" is an explicit "value is not set" (comes from a drill-down)
		const lookup = fresh.filter((v) => v !== "");
		let titles = {};
		if (this.doctype && lookup.length) {
			titles = await frappe.xcall(API + "link_titles", {
				items: JSON.stringify(lookup.map((v) => [this.doctype, v])),
			});
		}
		for (const v of fresh) {
			if (this.doctype && v !== "") {
				const t = titles[this.doctype + "\n" + v];
				if (t === undefined) continue;
				this.titles[v] = t;
			}
			this.values.push(v);
		}
		this.render();
		if (!silent) this.on_change();
	}

	set(values) {
		this.values = [];
		this.titles = {};
		return this.add(values || [], true);
	}

	remove(value) {
		this.values = this.values.filter((v) => v !== value);
		this.render();
		this.on_change();
	}

	render() {
		this.$chips.empty();
		this.values.forEach((v) => {
			const $chip = $(
				`<span class="ua-chip"><span class="ua-chip-text"></span><a class="ua-chip-x">×</a></span>`
			);
			$chip.find(".ua-chip-text").text(this.titles[v] || v || __("<не задано>"));
			$chip.find(".ua-chip-x").on("click", () => this.remove(v));
			this.$chips.append($chip);
		});
	}
};

// ------------------------------------------------------------------ the table

// HTML of a table model. interactive=false is used for printing.
ua_accounting.reports.table_html = function (model, interactive) {
	const head = model.header
		.map(
			(r) =>
				"<tr>" +
				r
					.map(
						(c) =>
							`<th colspan="${c.colspan || 1}" rowspan="${c.rowspan || 1}">${esc(c.label)}</th>`
					)
					.join("") +
				"</tr>"
		)
		.join("");

	const has_children = {};
	model.rows.forEach((r) => {
		if (r.parent) has_children[r.parent] = true;
	});

	const body = model.rows
		.map((row, i) => {
			const cls = ["ua-row-" + row.kind, row.bold ? "ua-bold" : ""].join(" ");
			const tds = model.columns
				.map((col) => {
					let v = row.cells[col.key];
					let html = "";
					if (col.kind === "money") html = fmt_number(v, 2);
					else if (col.kind === "qty") html = fmt_number(v, 3);
					else if (col.kind === "lines") {
						html = (v || []).map((x, n) => (n ? esc(x) : `<b>${esc(x)}</b>`)).join("<br>");
					} else if (col.kind === "doc" && row.links[col.key] && interactive) {
						const l = row.links[col.key];
						html = `<a href="${frappe.utils.get_form_link(l.doctype, l.name)}">${esc(v)}</a>`;
					} else if (col.kind === "label") {
						const pad = (row.level || 0) * 16;
						let inner = esc(v);
						if (interactive && row.drill) {
							inner = `<a class="ua-drill" data-i="${i}">${inner}</a>`;
						}
						const caret =
							interactive && has_children[row.id]
								? `<span class="ua-caret" data-id="${esc(row.id)}">▾</span>`
								: '<span class="ua-caret-gap"></span>';
						return `<td class="ua-label" style="padding-left:${pad + 4}px">${caret}${inner}</td>`;
					} else html = esc(v);
					return `<td class="ua-${col.kind} ua-a-${col.align || "left"}">${html}</td>`;
				})
				.join("");
			return `<tr class="${cls}" data-id="${esc(row.id)}" data-parent="${esc(row.parent || "")}">${tds}</tr>`;
		})
		.join("");
	return `<table class="ua-rpt"><thead>${head}</thead><tbody>${body}</tbody></table>`;
};

ua_accounting.reports.PRINT_CSS = `
	body { font-family: Arial, sans-serif; font-size: 11px; margin: 12mm; }
	h1 { font-size: 16px; margin: 0 0 6px; }
	.ua-lines div { margin: 1px 0; }
	table.ua-rpt { border-collapse: collapse; width: 100%; margin-top: 10px; }
	.ua-rpt th, .ua-rpt td { border: 1px solid #777; padding: 2px 5px; vertical-align: top; }
	.ua-rpt th { background: #e8e8e8; text-align: center; }
	.ua-a-right { text-align: right; white-space: nowrap; }
	.ua-a-center { text-align: center; }
	.ua-bold td { font-weight: bold; }
	.ua-row-total td, .ua-row-open td, .ua-row-close td { background: #f3f3f3; }
	.ua-caret-gap { display: none; }
	@page { size: A4 landscape; margin: 10mm; }
`;

// ------------------------------------------------------------------ the page

ua_accounting.reports.ReportPage = class ReportPage {
	constructor(wrapper, cfg) {
		this.wrapper = wrapper;
		this.cfg = cfg;
		this.model = null;
		this.collapsed = new Set();
		this.sub_rows = [];
		this.types = [];
		this.unit = "month";
		this.page = frappe.ui.make_app_page({ parent: wrapper, title: cfg.title, single_column: true });
		this.$main = $(this.page.main).addClass("ua-report");
		this.make_toolbar();
		this.make_filters();
		this.$result = $('<div class="ua-result"></div>').appendTo(this.$main);
		$(wrapper).on("show", () => this.on_show());
		frappe.xcall(API + "subconto_types").then((types) => (this.types = types));
	}

	// ---------- toolbar
	make_toolbar() {
		this.page.set_primary_action(__("Сформувати"), () => this.run(), "refresh");
		this.page.add_button(__("Друк"), () => this.print(), { icon: "printer" });
		this.page.add_button(__("Excel"), () => this.export_xlsx(), { icon: "small-file" });
	}

	// ---------- filters
	field(parent, df) {
		const $f = $('<div class="ua-f"></div>').appendTo(parent);
		const control = frappe.ui.form.make_control({ df, parent: $f, render_input: true });
		control.refresh();
		return control;
	}

	make_filters() {
		const cfg = this.cfg;
		this.$filters = $('<div class="ua-filters"></div>').appendTo(this.$main);
		const $row1 = $('<div class="ua-frow"></div>').appendTo(this.$filters);

		// period with 1C-like quick picks
		const $period = $('<div class="ua-period"></div>').appendTo($row1);
		this.$prev = $('<button class="btn btn-xs btn-default">‹</button>').appendTo($period);
		this.date_from = this.field($period, { fieldtype: "Date", fieldname: "date_from", label: __("Період з") });
		this.date_to = this.field($period, { fieldtype: "Date", fieldname: "date_to", label: __("по") });
		this.$next = $('<button class="btn btn-xs btn-default">›</button>').appendTo($period);
		this.quick = this.field($period, {
			fieldtype: "Select",
			fieldname: "quick",
			label: __("Швидкий вибір"),
			options: [
				"",
				"Цей місяць",
				"Минулий місяць",
				"Цей квартал",
				"Минулий квартал",
				"Цей рік",
				"Минулий рік",
			].join("\n"),
		});
		this.quick.$input.on("change", () => this.pick_quick(this.quick.get_value()));
		this.$prev.on("click", () => this.shift_period(-1));
		this.$next.on("click", () => this.shift_period(1));
		this.pick_quick("Цей місяць");

		this.currency = this.field($row1, {
			fieldtype: "Link",
			fieldname: "currency",
			options: "UA Currency",
			label: __("Валюта"),
		});

		const $row2 = $('<div class="ua-frow"></div>').appendTo(this.$filters);
		const $org = $('<div class="ua-f ua-f-wide"><label class="control-label"></label></div>').appendTo($row2);
		$org.find("label").text(__("Організації (порожньо: усі)"));
		this.orgs = new ua_accounting.reports.MultiLink($org, { doctype: "UA Organization", label: __("Організація") });

		if (cfg.accounts === "multi") {
			const $acc = $('<div class="ua-f ua-f-wide"><label class="control-label"></label></div>').appendTo($row2);
			$acc.find("label").text(__("Рахунки (порожньо: усі)"));
			this.accounts = new ua_accounting.reports.MultiLink($acc, {
				doctype: "UA Account",
				label: __("Рахунок"),
			});
		} else {
			this.account = this.field($row2, {
				fieldtype: "Link",
				fieldname: "account",
				options: "UA Account",
				label: __("Рахунок"),
				reqd: 1,
			});
			this.account.$input.on("awesomplete-selectcomplete change", () => this.load_account_info(true));
		}

		// options of the report
		const $row3 = $('<div class="ua-frow ua-opts"></div>').appendTo(this.$filters);
		this.opts = {};
		cfg.fields.forEach((f) => {
			const df = { fieldname: f.key, label: f.label, default: f.value };
			if (f.type === "check") df.fieldtype = "Check";
			else {
				df.fieldtype = "Select";
				df.options = f.options.join("\n");
			}
			const c = this.field($row3, df);
			c.set_value(f.value);
			this.opts[f.key] = c;
		});

		if (cfg.levels) {
			this.levels = [1, 2, 3].map((n) =>
				this.field($row3, {
					fieldtype: "Select",
					fieldname: "level" + n,
					label: __("Групування {0}", [n]),
					options: "",
				})
			);
		}

		// any subconto
		const $sub = $('<div class="ua-frow ua-subconto"></div>').appendTo(this.$filters);
		this.$sub_list = $('<div class="ua-sub-list"></div>').appendTo($sub);
		$(`<button class="btn btn-xs btn-default">+ ${__("Відбір по субконто")}</button>`)
			.appendTo($sub)
			.on("click", () => this.add_subconto_row());
	}

	pick_quick(label) {
		const map = {
			"Цей місяць": ["month", 0],
			"Минулий місяць": ["month", -1],
			"Цей квартал": ["quarter", 0],
			"Минулий квартал": ["quarter", -1],
			"Цей рік": ["year", 0],
			"Минулий рік": ["year", -1],
		};
		if (!map[label]) return;
		const [unit, shift] = map[label];
		this.unit = unit;
		const [a, b] = period_range(unit, shift);
		this.date_from.set_value(a);
		this.date_to.set_value(b);
	}

	shift_period(step) {
		const from = this.date_from.get_value();
		if (!from) return;
		const ref = moment(from).add(step, this.unit === "quarter" ? "quarters" : this.unit + "s");
		const [a, b] = period_range(this.unit, 0, ref);
		this.date_from.set_value(a);
		this.date_to.set_value(b);
		this.run();
	}

	add_subconto_row(type, values) {
		const $r = $('<div class="ua-sub-row"></div>').appendTo(this.$sub_list);
		const options = [""].concat(this.types.map((t) => t.name)).join("\n");
		const sel = this.field($r, {
			fieldtype: "Select",
			fieldname: "stype",
			label: __("Субконто"),
			options,
		});
		// show titles: replace option labels
		sel.$input.find("option").each((i, o) => {
			const t = this.types.find((x) => x.name === o.value);
			if (t) $(o).text(t.title);
		});
		const $v = $('<div class="ua-f ua-f-wide"></div>').appendTo($r);
		const multi = new ua_accounting.reports.MultiLink($v, { doctype: null, label: __("Значення") });
		const row = { $r, sel, multi };
		const apply_type = () => {
			const t = this.types.find((x) => x.name === sel.get_value());
			multi.set_doctype(t && !t.is_dynamic ? t.reference_doctype : null);
		};
		sel.$input.on("change", apply_type);
		$('<a class="ua-sub-x">×</a>')
			.appendTo($r)
			.on("click", () => {
				$r.remove();
				this.sub_rows = this.sub_rows.filter((x) => x !== row);
			});
		this.sub_rows.push(row);
		if (type) {
			sel.set_value(type);
			apply_type();
			multi.set(values || []);
		}
		return row;
	}

	async load_account_info(reset_levels, keep) {
		const account = this.account.get_value();
		if (!account) return;
		const info = await frappe.xcall(API + "account_info", { account });
		this.info = info;
		const titles = {};
		info.subconto.forEach((s) => (titles[s.type] = s.title));
		this.levels.forEach((c) => {
			c.df.options = [""].concat(info.subconto.map((s) => s.type)).join("\n");
			c.refresh();
			c.$input.find("option").each((i, o) => titles[o.value] && $(o).text(titles[o.value]));
		});
		if (reset_levels || !keep) {
			const auto = info.subconto.filter((s) => !s.turnover_only).slice(0, 2);
			this.levels.forEach((c, i) => c.set_value(auto[i] ? auto[i].type : ""));
		}
		this.opts.show_quantity && this.opts.show_quantity.$wrapper.toggle(!!info.quantity_accounting);
		this.opts.show_currency && this.opts.show_currency.$wrapper.toggle(!!info.currency_accounting);
	}

	get_filters() {
		const f = {
			date_from: this.date_from.get_value(),
			date_to: this.date_to.get_value(),
			organizations: this.orgs.values,
			currency: this.currency.get_value() || "",
			subconto: this.sub_rows
				.map((r) => ({ type: r.sel.get_value(), values: r.multi.values }))
				.filter((x) => x.type && x.values.length),
		};
		if (this.accounts) f.accounts = this.accounts.values;
		if (this.account) f.account = this.account.get_value();
		Object.keys(this.opts).forEach((k) => {
			const c = this.opts[k];
			f[k] = c.df.fieldtype === "Check" ? (c.get_value() ? 1 : 0) : c.get_value();
		});
		if (this.levels) f.levels = this.levels.map((c) => c.get_value()).filter(Boolean);
		return f;
	}

	async set_filters(f) {
		if (f.date_from) this.date_from.set_value(f.date_from);
		if (f.date_to) this.date_to.set_value(f.date_to);
		await this.orgs.set(f.organizations || []);
		this.currency.set_value(f.currency || "");
		if (this.accounts) await this.accounts.set(f.accounts || []);
		if (this.account && f.account) {
			this.account.set_value(f.account);
			await this.load_account_info(!f.levels, !!f.levels);
		}
		Object.keys(this.opts).forEach((k) => {
			if (f[k] !== undefined) this.opts[k].set_value(f[k]);
		});
		if (this.levels && f.levels) this.levels.forEach((c, i) => c.set_value(f.levels[i] || ""));
		this.$sub_list.empty();
		this.sub_rows = [];
		(f.subconto || []).forEach((s) => this.add_subconto_row(s.type, s.values));
	}

	// ---------- run, draw
	on_show() {
		const ro = frappe.route_options;
		if (ro && ro.filters) {
			frappe.route_options = null;
			this.set_filters(ro.filters).then(() => this.run());
		}
	}

	run() {
		const filters = this.get_filters();
		if (!filters.date_from || !filters.date_to) {
			frappe.msgprint(__("Вкажіть період"));
			return;
		}
		if (this.account && !filters.account) {
			frappe.msgprint(__("Вкажіть рахунок"));
			return;
		}
		return frappe
			.call({
				method: API + "run",
				args: { report: this.cfg.report, filters: JSON.stringify(filters) },
				freeze: true,
				freeze_message: __("Формування звіту…"),
			})
			.then((r) => {
				this.model = r.message;
				this.collapsed = new Set();
				this.draw();
			});
	}

	draw() {
		const m = this.model;
		this.page.set_title(m.title);
		const lines = m.lines.map((l) => `<div>${esc(l)}</div>`).join("");
		const msg = m.message ? `<div class="ua-message">${esc(m.message)}</div>` : "";
		this.$result.html(
			`<div class="ua-report-head"><div class="ua-report-title">${esc(m.title)}</div>` +
				`<div class="ua-lines">${lines}</div></div>${msg}` +
				`<div class="ua-table-wrap">${ua_accounting.reports.table_html(m, true)}</div>`
		);
		this.$result.find(".ua-drill").on("click", (e) => {
			e.preventDefault();
			this.drill(m.rows[$(e.currentTarget).data("i")].drill);
		});
		this.$result.find(".ua-caret").on("click", (e) => this.toggle($(e.currentTarget).data("id")));
	}

	toggle(id) {
		if (this.collapsed.has(id)) this.collapsed.delete(id);
		else this.collapsed.add(id);
		const parent = {};
		this.model.rows.forEach((r) => (parent[r.id] = r.parent));
		const hidden = (r) => {
			let p = r.parent;
			while (p) {
				if (this.collapsed.has(p)) return true;
				p = parent[p];
			}
			return false;
		};
		const rows = this.$result.find("tbody tr");
		this.model.rows.forEach((r, i) => rows.eq(i).toggle(!hidden(r)));
		this.$result.find(".ua-caret").each((i, el) => {
			$(el).text(this.collapsed.has($(el).data("id")) ? "▸" : "▾");
		});
	}

	// ---------- drill-down: OSV -> OSV by account -> card -> document
	drill(d) {
		const f = this.get_filters();
		const target = {
			date_from: f.date_from,
			date_to: f.date_to,
			organizations: f.organizations,
			currency: d.currency || f.currency,
			show_quantity: f.show_quantity,
			show_currency: f.show_currency,
		};
		const by_type = {};
		(f.subconto || []).forEach((s) => (by_type[s.type] = s));
		(d.subconto || []).forEach((s) => (by_type[s.type] = s));
		target.subconto = Object.values(by_type);
		if (d.to === "account_card") target.accounts = [d.account];
		else target.account = d.account;
		frappe.route_options = { filters: target };
		frappe.set_route(ua_accounting.reports.PAGES[d.to]);
	}

	// ---------- print, Excel
	print() {
		if (!this.model) return this.run().then(() => this.model && this.print());
		const m = this.model;
		const w = window.open("", "_blank");
		if (!w) return frappe.msgprint(__("Браузер заблокував вікно друку"));
		w.document.write(
			`<html><head><title>${esc(m.title)}</title><style>${ua_accounting.reports.PRINT_CSS}</style></head><body>` +
				`<h1>${esc(m.title)}</h1><div class="ua-lines">${m.lines.map((l) => `<div>${esc(l)}</div>`).join("")}</div>` +
				ua_accounting.reports.table_html(m, false) +
				"</body></html>"
		);
		w.document.close();
		w.focus();
		w.print();
	}

	export_xlsx() {
		const filters = this.get_filters();
		const url =
			"/api/method/" + API + "export_xlsx?" + $.param({ report: this.cfg.report, filters: JSON.stringify(filters) });
		window.open(url);
	}
};
