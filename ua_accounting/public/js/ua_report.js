// Shared client of the accounting reports (OSV, OSV by account, account card).
// Look: design/mockups/report-osv.html — page head, settings card, report card with a table that
// has a two-level sticky head, rows that open with a chevron, a sticky total and a drill-down menu.
// Each report page only gives a config. The server returns one "table model" for every report
// (see ua_accounting/reporting/model.py).
frappe.provide("ua_accounting.reports");

const API = "ua_accounting.reporting.api.";

ua_accounting.reports.PAGES = {
	osv: "ua-osv",
	osv_account: "ua-osv-account",
	account_card: "ua-account-card",
};

// Options that only one report uses. type: check | levels (the "Субконто" switch of OSV)
ua_accounting.reports.CONFIG = {
	osv: {
		report: "osv",
		title: __("Оборотно-сальдова відомість"),
		accounts: "multi",
		auto_run: true,
		fields: [
			{ key: "by_subaccounts", type: "check", label: __("По субрахунках"), value: 1 },
			{ key: "show_quantity", type: "check", label: __("Кількість"), value: 0 },
			{ key: "show_currency", type: "check", label: __("Валютна сума"), value: 0 },
			{ key: "show_zero", type: "check", label: __("Нульові рядки"), value: 0 },
			{ key: "subconto_levels", type: "levels", value: "0" },
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
	tax_invoice_register: {
		report: "tax_invoice_register",
		title: __("Реєстр податкових накладних"),
		accounts: "none",
		auto_run: true,
		fields: [
			{
				key: "direction",
				type: "select",
				label: __("Напрям"),
				value: "",
				options: [["", __("Усі")], ["Видана", __("Видані")], ["Отримана", __("Отримані")]],
			},
			{
				key: "erpn_status",
				type: "select",
				label: __("Статус ЄРПН"),
				value: "",
				options: [
					["", __("Усі")],
					["Не зареєстровано", __("Не зареєстровано")],
					["Надіслано", __("Надіслано")],
					["Зареєстровано", __("Зареєстровано")],
					["Відхилено", __("Відхилено")],
				],
			},
			{ key: "counterparty", type: "link", label: __("Контрагент"), doctype: "UA Counterparty", value: "" },
		],
	},
	tax_differences: {
		report: "tax_differences",
		title: __("Розрахунок податкових різниць"),
		accounts: "none",
		auto_run: true,
		fields: [],
	},
	regulated_reports: {
		report: "regulated_reports",
		title: __("Регламентована звітність"),
		accounts: "none",
		auto_run: true,
		fields: [],
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
const icon = (name, cls) => ua_accounting.ui.icon(name, cls);

function fmt_number(value, precision) {
	if (value === null || value === undefined || value === "" || Math.abs(value) < 0.0000001) return "";
	return format_number(value, null, precision);
}

function step_of(unit) {
	return unit === "quarter" ? "quarters" : unit + "s";
}

function period_range(unit, shift, ref) {
	const m = moment(ref || undefined);
	const start = m.clone().startOf(unit).add(shift, step_of(unit));
	const end = start.clone().endOf(unit);
	return [start.format("YYYY-MM-DD"), end.format("YYYY-MM-DD")];
}

const QUICK = [
	{ label: __("Цей місяць"), unit: "month", shift: 0 },
	{ label: __("Минулий місяць"), unit: "month", shift: -1 },
	{ label: __("Цей квартал"), unit: "quarter", shift: 0 },
	{ label: __("Минулий квартал"), unit: "quarter", shift: -1 },
	{ label: __("Цей рік"), unit: "year", shift: 0 },
	{ label: __("Минулий рік"), unit: "year", shift: -1 },
];

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
			if (this.values.includes(v)) continue;
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

	// short text for a chip: "усі", one title or "N обрано"
	text() {
		if (!this.values.length) return __("усі");
		if (this.values.length === 1) return this.titles[this.values[0]] || this.values[0] || __("<не задано>");
		return __("{0} обрано", [this.values.length]);
	}

	render() {
		this.$chips.empty();
		this.values.forEach((v) => {
			const $chip = $(
				`<span class="ua-chip is-on"><span class="ua-chip-text"></span>` +
					`<button type="button" class="ua-chip-x" aria-label="${esc(__("Прибрати"))}">${icon("x")}</button></span>`
			);
			$chip.find(".ua-chip-text").text(this.titles[v] || v || __("<не задано>"));
			$chip.find(".ua-chip-x").on("click", (e) => {
				e.stopPropagation();
				this.remove(v);
			});
			this.$chips.append($chip);
		});
	}
};

// ------------------------------------------------------------------ print

// Plain HTML of a table model for printing.
ua_accounting.reports.table_html = function (model) {
	const head = model.header
		.map(
			(r) =>
				"<tr>" +
				r.map((c) => `<th colspan="${c.colspan || 1}" rowspan="${c.rowspan || 1}">${esc(c.label)}</th>`).join("") +
				"</tr>"
		)
		.join("");
	const body = model.rows
		.map((row) => {
			const cls = ["ua-row-" + row.kind, row.bold ? "ua-bold" : ""].join(" ");
			const tds = model.columns
				.map((col) => {
					const v = row.cells[col.key];
					let html = "";
					if (col.kind === "money") html = fmt_number(v, 2);
					else if (col.kind === "qty") html = fmt_number(v, 3);
					else if (col.kind === "lines") html = (v || []).map((x, n) => (n ? esc(x) : `<b>${esc(x)}</b>`)).join("<br>");
					else if (col.kind === "label") {
						return `<td style="padding-left:${(row.level || 0) * 16 + 4}px">${esc(v)}</td>`;
					} else html = esc(v);
					return `<td class="ua-a-${col.align || "left"}">${html}</td>`;
				})
				.join("");
			return `<tr class="${cls}">${tds}</tr>`;
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
		this.opt = {};
		this.sk = "0";
		this.run_id = 0;
		frappe.ui.make_app_page({ parent: wrapper, title: cfg.title, single_column: true });
		this.$root = $('<div class="ua-report"></div>').appendTo($(wrapper).find(".layout-main-section"));
		// controls that live in popovers wait here while the popover is closed
		this.$hold = $('<div class="ua-hold" hidden></div>').appendTo(this.$root);
		const [a, b] = period_range("month", 0);
		this.period = { from: a, to: b };
		this.make_head();
		this.make_settings();
		this.make_result();
		this.bind();
		$(wrapper).on("show", () => this.on_show());
		this.types_ready = frappe.xcall(API + "subconto_types").then((types) => (this.types = types));
		// the report follows the organization of the top bar
		const org = ua_accounting.shell && ua_accounting.shell.current_org && ua_accounting.shell.current_org();
		this.ready = org ? this.orgs.set([org.name]).then(() => this.update_chips()) : Promise.resolve();
		$(document).on("ua-org-changed", () => {
			const o = ua_accounting.shell.current_org();
			if (!o) return;
			this.orgs.set([o.name]).then(() => {
				this.update_chips();
				if ((this.model || this.started) && $(this.wrapper).is(":visible")) this.run();
			});
		});
	}

	// ---------- page head (mockup ".ph")
	make_head() {
		this.$root.append(`
			<div class="ua-ph">
				<h1 class="ua-ph-title"><span class="ua-rpt-title">${esc(this.cfg.title)}</span>
					<span class="ua-tag">${esc(__("Бухгалтерський облік"))}</span></h1>
				<div class="ua-ph-actions">
					<button type="button" class="ua-btn ua-btn--ghost" data-act="settings" aria-expanded="true">${icon("sliders")}${esc(
						__("Налаштування")
					)}${icon("chev-d", "ua-i-chev")}</button>
					<span class="ua-toolbar-sep"></span>
					<button type="button" class="ua-btn" data-act="print">${icon("printer")}${esc(__("Друк"))}</button>
					<button type="button" class="ua-btn" data-act="excel">${icon("sheet")}Excel</button>
					<button type="button" class="ua-btn ua-btn--icon" data-act="more" aria-haspopup="menu" aria-expanded="false"
						aria-label="${esc(__("Ще"))}" title="${esc(__("Ще"))}">${icon("more")}</button>
					<button type="button" class="ua-btn ua-btn--primary" data-act="run">${icon("refresh")}${esc(
						__("Сформувати")
					)}<span class="ua-kbd">Ctrl Enter</span></button>
				</div>
			</div>`);
	}

	// ---------- settings card
	make_settings() {
		const cfg = this.cfg;
		const $set = $(`<div class="ua-settings"><section class="ua-card" aria-label="${esc(__("Налаштування звіту"))}">
			<div class="ua-set-row ua-set-main">
				<div class="ua-period" role="group" aria-label="${esc(__("Період звіту"))}">
					<button type="button" class="ua-btn ua-btn--icon" data-act="prev" aria-label="${esc(__("Попередній період"))}"
						title="${esc(__("Попередній період"))}">${icon("chev-l")}</button>
					<button type="button" class="ua-btn ua-period-field" data-act="period" aria-haspopup="dialog" aria-expanded="false">
						${icon("calendar")}<span class="ua-period-text"></span>${icon("chev-d")}</button>
					<button type="button" class="ua-btn ua-btn--icon" data-act="next" aria-label="${esc(__("Наступний період"))}"
						title="${esc(__("Наступний період"))}">${icon("chev-r")}</button>
				</div>
				<div class="ua-seg ua-units" role="group" aria-label="${esc(__("Швидкий вибір періоду"))}">
					<button type="button" data-unit="month">${esc(__("Місяць"))}</button><button type="button" data-unit="quarter">${esc(
						__("Квартал")
					)}</button><button type="button" data-unit="year">${esc(__("Рік"))}</button>
				</div>
				<span class="ua-set-sep"></span>
				<button type="button" class="ua-chip" data-act="orgs" aria-haspopup="dialog" aria-expanded="false">${icon(
					"building"
				)}${esc(__("Організація"))}: <b class="ua-orgs-text"></b>${icon("chev-d")}</button>
			</div>
			<div class="ua-set-row ua-set-opts"><div class="ua-set-right"></div></div>
			<div class="ua-set-row ua-sub-rows" hidden></div>
		</section></div>`).appendTo(this.$root);
		this.$settings = $set;
		const $main = $set.find(".ua-set-main");
		const $opts = $set.find(".ua-set-opts");
		const $right = $opts.find(".ua-set-right");

		// organizations: chips in a popover
		this.$org_box = $('<div class="ua-pop-box"></div>').appendTo(this.$hold);
		this.orgs = new ua_accounting.reports.MultiLink(this.$org_box, {
			doctype: "UA Organization",
			placeholder: __("Знайти організацію…"),
			on_change: () => this.update_chips(),
		});

		// accounts: chips in a popover (OSV, card) or one account in the row (OSV by account)
		if (cfg.accounts === "multi") {
			$main.append(
				`<button type="button" class="ua-chip" data-act="accounts" aria-haspopup="dialog" aria-expanded="false">${icon(
					"list"
				)}${esc(__("Рахунки"))}: <b class="ua-acc-text"></b>${icon("chev-d")}</button>`
			);
			this.$acc_box = $('<div class="ua-pop-box"></div>').appendTo(this.$hold);
			this.accounts = new ua_accounting.reports.MultiLink(this.$acc_box, {
				doctype: "UA Account",
				placeholder: __("Знайти рахунок…"),
				on_change: () => this.update_chips(),
			});
		} else if (cfg.accounts !== "none") {
			const $acc = $('<div class="ua-set-account"></div>').appendTo($main);
			this.account = this.field($acc, {
				fieldtype: "Link",
				fieldname: "account",
				options: "UA Account",
				placeholder: __("Рахунок"),
			});
			this.account.$input.attr("aria-label", __("Рахунок"));
			this.account.$input.on("awesomplete-selectcomplete change", () => this.load_account_info(true));
		}

		// currency: one value in a popover; the chip stands next to "Валютна сума" (see update_chips)
		const $cur_chip = $(
			`<button type="button" class="ua-chip" data-act="currency" aria-haspopup="dialog" aria-expanded="false">${icon(
				"cash"
			)}${esc(__("Валюта"))}: <b class="ua-cur-text"></b>${icon("chev-d")}</button>`
		);
		this.$cur_box = $('<div class="ua-pop-box"></div>').appendTo(this.$hold);
		this.currency = this.field(this.$cur_box, {
			fieldtype: "Link",
			fieldname: "currency",
			options: "UA Currency",
			placeholder: __("Знайти валюту…"),
		});
		this.currency.$input.on("awesomplete-selectcomplete change", () => this.update_chips());

		// options of the report: toggles; the subconto switch goes to the right
		cfg.fields.forEach((f) => {
			this.opt[f.key] = f.value;
			if (f.type === "select") {
				$(
					`<label class="ua-set-label">${esc(f.label)} <select class="ua-input ua-input--sm" data-opt-select="${f.key}">${f.options
						.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`)
						.join("")}</select></label>`
				).insertBefore($right);
				return;
			}
			if (f.type === "link") {
				const $l = $(`<div class="ua-set-link"><span class="ua-set-label">${esc(f.label)}</span></div>`).insertBefore($right);
				this.links = this.links || {};
				this.links[f.key] = this.field($l, { fieldtype: "Link", fieldname: f.key, options: f.doctype, placeholder: f.label });
				return;
			}
			if (f.type !== "check") return;
			$(
				`<label class="ua-toggle" data-opt-wrap="${f.key}"><input type="checkbox" data-opt="${f.key}"${
					f.value ? " checked" : ""
				}><span class="ua-toggle-track"></span>${esc(f.label)}</label>`
			).insertBefore($right);
		});

		const $cur_toggle = $opts.find('[data-opt-wrap="show_currency"]');
		if ($cur_toggle.length) $cur_chip.insertAfter($cur_toggle);
		else $cur_chip.insertBefore($right);
		if (cfg.accounts !== "none") $right.append(
			`<button type="button" class="ua-chip ua-chip--dashed" data-act="add-sub">${icon("plus")}${esc(
				__("Відбір по субконто")
			)}</button>`
		);
		if (cfg.fields.some((f) => f.type === "levels")) {
			this.sk = "0";
			$right.append(
				`<span class="ua-set-sep"></span><span class="ua-set-label" id="ua-sk-${cfg.report}">${esc(__("Субконто"))}</span>` +
					`<div class="ua-seg ua-sk" role="radiogroup" aria-labelledby="ua-sk-${cfg.report}">` +
					[
						["0", __("Ні")],
						["1", __("1 рівень")],
						["2", __("2 рівні")],
						["3", __("3 рівні")],
					]
						.map(([v, l]) => `<button type="button" role="radio" data-sk="${v}">${esc(l)}</button>`)
						.join("") +
					"</div>"
			);
		}
		if (cfg.levels) {
			$(`<div class="ua-set-row ua-set-levels"></div>`).insertBefore($set.find(".ua-sub-rows")).append(
				`<span class="ua-set-label">${esc(__("Групування"))}</span>` +
					[1, 2, 3]
						.map(
							(n) =>
								`<select class="ua-input ua-input--sm ua-level" data-level="${n}" aria-label="${esc(
									__("Групування {0}", [n])
								)}"><option value="">—</option></select>`
						)
						.join("")
			);
			this.$levels = $set.find(".ua-level");
		}
		this.$sub_list = $set.find(".ua-sub-rows");
		this.update_period();
		this.update_chips();
		this.update_switches();
	}

	make_result() {
		this.$card = $(`<section class="ua-card ua-rpt-card" aria-label="${esc(__("Звіт"))}">
			<div class="ua-rpt-head"><div class="ua-rpt-meta"></div>
				<span class="ua-hint" hidden>${icon("info")}${esc(__("Клік по сумі — розшифровка"))}</span></div>
			<div class="ua-rpt-msg" hidden></div>
			<div class="ua-table-wrap ua-rpt-wrap"></div>
		</section>`).appendTo(this.$root);
		this.$wrap = this.$card.find(".ua-rpt-wrap");
		this.$wrap.on("scroll", () => this.$wrap.toggleClass("is-scrolled", this.$wrap[0].scrollTop > 0));
		if (this.cfg.auto_run) this.show_skeleton();
		else
			this.show_state({
				art: "sheet",
				title: __("Налаштуйте звіт"),
				text: this.account
					? __("Оберіть рахунок і натисніть «Сформувати».")
					: __("Оберіть період і відбір, потім натисніть «Сформувати»."),
			});
	}

	field(parent, df) {
		const $f = $('<div class="ua-f"></div>').appendTo(parent);
		const control = frappe.ui.form.make_control({ df, parent: $f, render_input: true });
		control.refresh();
		return control;
	}

	// ---------- events
	bind() {
		const $r = this.$root;
		$r.on("click", "[data-act]", (e) => {
			const el = e.currentTarget;
			const act = el.dataset.act;
			if (act === "run") this.run();
			else if (act === "print") this.print();
			else if (act === "excel") this.export_xlsx();
			else if (act === "more") this.more_menu(el);
			else if (act === "settings") this.toggle_settings(el);
			else if (act === "prev") this.shift_period(-1);
			else if (act === "next") this.shift_period(1);
			else if (act === "period") this.period_menu(el);
			else if (act === "orgs") this.chip_menu(el, __("Організації"), this.$org_box, () => this.orgs.set([]));
			else if (act === "accounts") this.chip_menu(el, __("Рахунки"), this.$acc_box, () => this.accounts.set([]));
			else if (act === "currency") this.chip_menu(el, __("Валюта"), this.$cur_box, () => this.currency.set_value(""));
			else if (act === "add-sub") this.add_subconto_row();
			else if (act === "retry") this.run();
			else if (act === "change-period") this.period_menu(this.$root.find('[data-act="period"]')[0]);
		});
		$r.on("click", "[data-unit]", (e) => {
			this.unit = e.currentTarget.dataset.unit;
			const [a, b] = period_range(this.unit, 0, this.period.from);
			this.set_period(a, b);
			this.run();
		});
		$r.on("click", "[data-sk]", (e) => {
			this.sk = e.currentTarget.dataset.sk;
			this.update_switches();
		});
		$r.on("change", "[data-opt]", (e) => {
			this.opt[e.currentTarget.dataset.opt] = e.currentTarget.checked ? 1 : 0;
			this.update_chips();
		});
		$r.on("click", "[data-tog]", (e) => this.toggle(e.currentTarget.dataset.tog));
		$r.on("click", ".ua-amt", (e) => this.amt_menu(e.currentTarget));
		$r.on("keydown", ".ua-amt", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				this.amt_menu(e.currentTarget);
			}
		});
		$(document).on("keydown", (e) => {
			if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey)) return;
			if (!$(this.wrapper).is(":visible") || $(".modal.show").length) return;
			e.preventDefault();
			ua_accounting.ui.close_menu();
			this.run();
		});
		$(window).on("resize", () => this.fit());
	}

	toggle_settings(btn) {
		const open = !this.$settings.hasClass("is-collapsed");
		this.$settings.toggleClass("is-collapsed", open);
		btn.setAttribute("aria-expanded", String(!open));
		const ms = parseFloat(getComputedStyle(this.$settings[0]).transitionDuration) * 1000 || 0;
		setTimeout(() => this.fit(), ms + 20);
	}

	more_menu(btn) {
		const html =
			`<button class="ua-menu-item" data-x="expand">${icon("chev-d")}${esc(__("Розгорнути все"))}</button>` +
			`<button class="ua-menu-item" data-x="collapse">${icon("chev-r")}${esc(__("Згорнути все"))}</button>`;
		ua_accounting.ui.menu(
			btn,
			html,
			(item) => {
				if (!this.model) return;
				if (item.dataset.x === "expand") this.collapsed = new Set();
				else this.collapsed = new Set(this.model.rows.filter((r) => this.kids[r.id]).map((r) => r.id));
				this.apply_visibility();
			},
			{ align: "right" }
		);
	}

	// a popover that holds a live control (chips of organizations, accounts or a currency)
	chip_menu(btn, title, $box, clear) {
		const html =
			`<div class="ua-menu-label">${esc(title)}</div><div class="ua-pop-slot"></div>` +
			`<div class="ua-pop-foot"><button type="button" class="ua-btn ua-btn--sm ua-btn--ghost" data-act="clear">${esc(
				__("Усі")
			)}</button><button type="button" class="ua-btn ua-btn--sm ua-btn--primary" data-act="done">${esc(
				__("Готово")
			)}</button></div>`;
		ua_accounting.ui.menu(
			btn,
			html,
			(item) => {
				if (item.dataset.act === "clear") {
					Promise.resolve(clear()).then(() => this.update_chips());
				} else if (item.dataset.act !== "done") return true;
			},
			{
				cls: "ua-chip-pop",
				role: "dialog",
				on_open: (el) => $(el).find(".ua-pop-slot").append($box),
				on_close: () => {
					this.$hold.append($box);
					this.update_chips();
				},
			}
		);
	}

	update_chips() {
		this.$root.find(".ua-orgs-text").text(this.orgs.text());
		this.$root.find('[data-act="orgs"]').toggleClass("is-on", this.orgs.values.length > 0);
		if (this.accounts) {
			this.$root.find(".ua-acc-text").text(this.accounts.text());
			this.$root.find('[data-act="accounts"]').toggleClass("is-on", this.accounts.values.length > 0);
		}
		const cur = this.currency.get_value();
		this.$root.find(".ua-cur-text").text(cur || __("усі"));
		if (this.cfg.accounts === "none") {
			this.$root.find('[data-act="currency"]').prop("hidden", true);
			return;
		}
		// the currency filter is shown with currency amounts (or when it is set): the row stays short
		const $wrap = this.$root.find('[data-opt-wrap="show_currency"]');
		const shown = !!cur || !$wrap.length || (!!this.opt.show_currency && $wrap.css("display") !== "none");
		this.$root.find('[data-act="currency"]').toggleClass("is-on", !!cur).prop("hidden", !shown);
	}

	update_switches() {
		this.$root.find("[data-sk]").each((i, b) => {
			const on = b.dataset.sk === this.sk;
			b.classList.toggle("is-on", on);
			b.setAttribute("aria-checked", String(on));
		});
		Object.keys(this.opt).forEach((k) => {
			const $i = this.$root.find(`[data-opt="${k}"]`);
			if ($i.length) $i.prop("checked", !!+this.opt[k]);
		});
	}

	// ---------- period
	update_period() {
		const f = frappe.datetime.str_to_user;
		this.$root.find(".ua-period-text").text(`${f(this.period.from)} – ${f(this.period.to)}`);
		this.$root.find("[data-unit]").each((i, b) => {
			const [a, z] = period_range(b.dataset.unit, 0, this.period.from);
			b.classList.toggle("is-on", a === this.period.from && z === this.period.to);
		});
	}

	set_period(from, to) {
		this.period = { from, to };
		this.update_period();
	}

	shift_period(step) {
		const ref = moment(this.period.from).add(step, step_of(this.unit));
		const [a, b] = period_range(this.unit, 0, ref);
		this.set_period(a, b);
		this.run();
	}

	period_menu(btn) {
		if (!this.$date_box) {
			this.$date_box = $('<div class="ua-pp-dates"></div>').appendTo(this.$hold);
			this.date_from = this.field(this.$date_box, { fieldtype: "Date", fieldname: "date_from", label: __("З") });
			this.date_to = this.field(this.$date_box, { fieldtype: "Date", fieldname: "date_to", label: __("По") });
		}
		const html =
			`<div class="ua-pp"><div class="ua-pp-quick"><div class="ua-menu-label">${esc(__("Швидкий вибір"))}</div>` +
			QUICK.map((q, i) => `<button type="button" class="ua-menu-item" data-q="${i}">${esc(q.label)}</button>`).join("") +
			`</div><div class="ua-pp-custom"><div class="ua-menu-label">${esc(__("Довільний період"))}</div>` +
			`<div class="ua-pop-slot"></div></div>` +
			`<div class="ua-pop-foot"><button type="button" class="ua-btn ua-btn--sm" data-act="cancel">${esc(
				__("Скасувати")
			)}</button><button type="button" class="ua-btn ua-btn--sm ua-btn--primary" data-act="ok">${esc(
				__("Застосувати")
			)}</button></div></div>`;
		ua_accounting.ui.menu(
			btn,
			html,
			(item) => {
				if (item.dataset.q !== undefined) {
					const q = QUICK[+item.dataset.q];
					this.unit = q.unit;
					const [a, b] = period_range(q.unit, q.shift);
					this.set_period(a, b);
					this.run();
				} else if (item.dataset.act === "ok") {
					const a = this.date_from.get_value();
					const b = this.date_to.get_value();
					if (!a || !b || a > b) {
						frappe.show_alert({ message: __("Вкажіть дати періоду: початок не пізніше кінця."), indicator: "red" });
						return true;
					}
					this.set_period(a, b);
					this.run();
				} else if (item.dataset.act !== "cancel") return true;
			},
			{
				cls: "ua-period-pop",
				role: "dialog",
				on_open: (el) => {
					$(el).find(".ua-pop-slot").append(this.$date_box);
					this.date_from.set_value(this.period.from);
					this.date_to.set_value(this.period.to);
				},
				on_close: () => this.$hold.append(this.$date_box),
			}
		);
	}

	// ---------- subconto filters
	async add_subconto_row(type, values) {
		await this.types_ready;
		this.$sub_list.prop("hidden", false);
		const $r = $('<div class="ua-sub-row"></div>').appendTo(this.$sub_list);
		const options = [""].concat(this.types.map((t) => t.name)).join("\n");
		const sel = this.field($r, { fieldtype: "Select", fieldname: "stype", options });
		sel.$input.attr("aria-label", __("Вид субконто"));
		// show titles: replace option labels
		sel.$input.find("option").each((i, o) => {
			const t = this.types.find((x) => x.name === o.value);
			if (t) $(o).text(t.title);
			else if (!o.value) $(o).attr("value", "").text(__("Вид субконто…"));
		});
		const $v = $('<div class="ua-f ua-f-wide"></div>').appendTo($r);
		const multi = new ua_accounting.reports.MultiLink($v, { doctype: null, placeholder: __("Значення…") });
		const row = { $r, sel, multi };
		const apply_type = () => {
			const t = this.types.find((x) => x.name === sel.get_value());
			multi.set_doctype(t && !t.is_dynamic ? t.reference_doctype : null);
		};
		sel.$input.on("change", apply_type);
		$(
			`<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" aria-label="${esc(
				__("Прибрати відбір")
			)}">${icon("x")}</button>`
		)
			.appendTo($r)
			.on("click", () => {
				$r.remove();
				this.sub_rows = this.sub_rows.filter((x) => x !== row);
				this.$sub_list.prop("hidden", !this.sub_rows.length);
				this.fit();
			});
		this.sub_rows.push(row);
		if (type) {
			await sel.set_value(type);
			apply_type();
			await multi.set(values || []);
		}
		this.fit();
		return row;
	}

	async load_account_info(reset_levels, keep) {
		const account = this.account.get_value();
		if (!account) return;
		const info = await frappe.xcall(API + "account_info", { account });
		this.info = info;
		const opts =
			'<option value="">—</option>' +
			info.subconto.map((s) => `<option value="${esc(s.type)}">${esc(s.title)}</option>`).join("");
		this.$levels.each((i, sel) => {
			const old = sel.value;
			sel.innerHTML = opts;
			sel.value = old;
		});
		if (reset_levels || !keep) {
			const auto = info.subconto.filter((s) => !s.turnover_only).slice(0, 2);
			this.$levels.each((i, sel) => (sel.value = auto[i] ? auto[i].type : ""));
		}
		this.$root.find('[data-opt-wrap="show_quantity"]').toggle(!!info.quantity_accounting);
		this.$root.find('[data-opt-wrap="show_currency"]').toggle(!!info.currency_accounting);
		this.update_chips();
	}

	get_filters() {
		const f = {
			date_from: this.period.from,
			date_to: this.period.to,
			organizations: this.orgs.values,
			currency: this.currency.get_value() || "",
			subconto: this.sub_rows
				.map((r) => ({ type: r.sel.get_value(), values: r.multi.values }))
				.filter((x) => x.type && x.values.length),
		};
		if (this.accounts) f.accounts = this.accounts.values;
		if (this.account) f.account = this.account.get_value();
		this.cfg.fields.forEach((fd) => {
			if (fd.type === "select") f[fd.key] = this.$root.find(`[data-opt-select="${fd.key}"]`).val() || "";
			else if (fd.type === "link") f[fd.key] = this.links[fd.key].get_value() || "";
			else f[fd.key] = fd.type === "levels" ? this.sk : this.opt[fd.key] ? 1 : 0;
		});
		if (this.$levels) f.levels = this.$levels.map((i, s) => s.value).get().filter(Boolean);
		return f;
	}

	async set_filters(f) {
		// the organization of the top bar may still be loading: let it finish first
		await this.ready;
		if (f.date_from && f.date_to) this.set_period(f.date_from, f.date_to);
		await this.orgs.set(f.organizations || (f.organization ? [f.organization] : []));
		// a Link sets its value after a check on the server: wait for it
		await this.currency.set_value(f.currency || "");
		if (this.accounts) await this.accounts.set(f.accounts || []);
		if (this.account && f.account) {
			await this.account.set_value(f.account);
			await this.load_account_info(!f.levels, !!f.levels);
		}
		for (const fd of this.cfg.fields) {
			if (f[fd.key] === undefined) continue;
			if (fd.type === "select") this.$root.find(`[data-opt-select="${fd.key}"]`).val(f[fd.key]);
			else if (fd.type === "link") await this.links[fd.key].set_value(f[fd.key]);
			else if (fd.type === "levels") this.sk = String(f[fd.key]);
			else this.opt[fd.key] = f[fd.key] ? 1 : 0;
		}
		if (this.$levels && f.levels) this.$levels.each((i, s) => (s.value = f.levels[i] || ""));
		this.$sub_list.empty().prop("hidden", true);
		this.sub_rows = [];
		for (const s of f.subconto || []) await this.add_subconto_row(s.type, s.values);
		this.update_chips();
		this.update_switches();
	}

	// ---------- run, states, draw
	on_show() {
		const ro = frappe.route_options;
		if (ro && ro.filters) {
			frappe.route_options = null;
			// the v16 router passes route options through the URL: objects come back as JSON text
			const f = typeof ro.filters === "string" ? JSON.parse(ro.filters) : ro.filters;
			this.set_filters(f).then(() => this.run());
		} else if (this.cfg.auto_run && !this.started) {
			this.started = true;
			this.ready.then(() => this.run());
		}
		this.fit();
	}

	run() {
		const filters = this.get_filters();
		if (this.account && !filters.account) {
			this.show_state({
				art: "sheet",
				title: __("Оберіть рахунок"),
				text: __("ОСВ по рахунку формується для одного рахунку. Оберіть його в налаштуваннях."),
			});
			this.account.$input.trigger("focus");
			return Promise.resolve();
		}
		this.started = true;
		const id = ++this.run_id;
		const $btn = this.$root.find('[data-act="run"]');
		$btn.addClass("is-loading").prop("disabled", true);
		this.show_skeleton();
		const done = () => id === this.run_id && $btn.removeClass("is-loading").prop("disabled", false);
		return new Promise((resolve) => {
			frappe.call({
				method: API + "run",
				args: { report: this.cfg.report, filters: JSON.stringify(filters) },
				callback: (r) => {
					if (id !== this.run_id) return resolve();
					done();
					this.model = r.message;
					this.generated = frappe.datetime.now_datetime();
					this.collapsed = null;
					this.draw();
					resolve();
				},
				error: () => {
					if (id !== this.run_id) return resolve();
					done();
					this.model = null;
					this.show_state({
						error: true,
						title: __("Не вдалося сформувати звіт"),
						text: __("Дані не змінено. Спробуйте ще раз; якщо помилка повториться, зверніться до адміністратора."),
						actions: [{ label: __("Повторити"), primary: true, icon: "refresh", act: "retry" }],
					});
					resolve();
				},
			});
		});
	}

	show_skeleton() {
		this.$card.find(".ua-rpt-head").prop("hidden", !this.model);
		let rows = "";
		for (let i = 0; i < 12; i++) {
			const w = 30 + ((i * 17) % 40);
			rows += `<tr class="ua-skel-tr"><td><span class="ua-skel" style="width:${w}%"></span></td>`;
			for (let j = 0; j < 6; j++) {
				rows += `<td><span class="ua-skel" style="width:${40 + ((i * 7 + j * 13) % 45)}%;margin-left:auto"></span></td>`;
			}
			rows += "</tr>";
		}
		this.$card.find(".ua-hint, .ua-rpt-msg").prop("hidden", true);
		this.$wrap.html(
			`<table class="ua-table ua-rpt-skel" aria-busy="true" aria-label="${esc(__("Завантаження"))}"><tbody>${rows}</tbody></table>`
		);
		this.fit();
	}

	show_state(o) {
		this.$card.find(".ua-rpt-head").prop("hidden", !this.model);
		this.$card.find(".ua-hint, .ua-rpt-msg").prop("hidden", true);
		this.$wrap.html(`<div class="ua-state-box">${ua_accounting.ui.empty_html(o)}</div>`);
		this.fit();
	}

	meta_html() {
		const m = this.model;
		const parts = (m.lines || []).map((l, i) => {
			const k = l.indexOf(": ");
			if (i === 0 && k > 0) return `<span>${esc(l.slice(0, k + 2))}<b>${esc(l.slice(k + 2))}</b></span>`;
			return `<span>${esc(l)}</span>`;
		});
		parts.push(
			`<span>${esc(__("Сформовано {0}", [frappe.datetime.str_to_user(this.generated).slice(0, 16)]))} · ${esc(
				frappe.session.user_fullname || ""
			)}</span>`
		);
		return parts.join('<span class="ua-dotsep">·</span>');
	}

	draw() {
		const m = this.model;
		this.$card.find(".ua-rpt-meta").html(this.meta_html());
		this.$card.find(".ua-rpt-head").prop("hidden", false);
		this.$card.find(".ua-rpt-msg").text(m.message || "").prop("hidden", !m.message);

		// rows that have children; the subconto values start closed, the accounts stay open
		this.kids = {};
		this.parent_of = {};
		m.rows.forEach((r) => {
			this.parent_of[r.id] = r.parent;
			if (r.parent) (this.kids[r.parent] = this.kids[r.parent] || []).push(r);
		});
		if (!this.collapsed) {
			const is_account = (r) => /^\d{2,4}\s/.test(r.cells.label || "");
			this.collapsed = new Set(
				m.rows.filter((r) => this.kids[r.id] && this.kids[r.id].some((c) => !is_account(c))).map((r) => r.id)
			);
		}
		const last = m.rows[m.rows.length - 1];
		this.foot = last && last.kind === "total" ? last : null;
		this.body_rows = this.foot ? m.rows.slice(0, -1) : m.rows;

		if (!this.body_rows.length) {
			const orgs = this.orgs.values.length ? this.orgs.text() : __("усіх організаціях");
			this.show_state({
				art: "inbox",
				title: __("За період немає даних"),
				text: __("За {0} по {1} немає залишків і оборотів. Змініть період або відбір.", [
					this.$root.find(".ua-period-text").text(),
					orgs,
				]),
				actions: [{ label: __("Змінити період"), icon: "calendar", act: "change-period" }],
			});
			return;
		}
		this.$card.find(".ua-hint").prop("hidden", !m.rows.some((r) => r.drill));
		this.$wrap.html(this.table_html()).removeClass("is-scrolled");
		this.$wrap[0].scrollTop = 0;
		this.apply_visibility(true);
		// the second head row sticks right under the first one
		const h = this.$wrap.find("thead tr").first().outerHeight() || 34;
		this.$wrap[0].style.setProperty("--ua-h1", h + "px");
		this.fit();
	}

	table_html() {
		const m = this.model;
		const cols = m.columns;
		// a group of the head (colspan > 1) starts with a line on its left
		const gs = new Set();
		const under = [];
		let pos = 0;
		(m.header[0] || []).forEach((c) => {
			const span = c.colspan || 1;
			if (pos > 0 && span > 1) gs.add(pos);
			if ((c.rowspan || 1) === 1) for (let k = 0; k < span; k++) under.push(pos + k);
			pos += span;
		});
		const al = (i) => (cols[i] && cols[i].align === "right" ? " ua-r" : cols[i] && cols[i].align === "center" ? " ua-c" : "");
		const g = (i) => (gs.has(i) ? " ua-gs" : "");
		let p = 0;
		const head1 = (m.header[0] || [])
			.map((c) => {
				const i = p;
				p += c.colspan || 1;
				const two = (c.rowspan || 1) > 1;
				const cls = two ? `ua-h-two${al(i)}${i === 0 ? " ua-acc-h" : ""}` : "ua-h-group";
				return `<th colspan="${c.colspan || 1}" rowspan="${c.rowspan || 1}" class="${cls}${g(i)}" scope="${
					two ? "col" : "colgroup"
				}">${esc(c.label)}</th>`;
			})
			.join("");
		const head2 = (m.header[1] || [])
			.map((c, k) => `<th class="ua-h-sub${al(under[k])}${g(under[k])}" scope="col">${esc(c.label)}</th>`)
			.join("");
		const numeric = cols.every((c) => ["label", "money", "qty"].includes(c.kind));
		const colgroup = cols
			.map((c) => {
				if (c.kind === "money" || c.kind === "qty") return '<col class="ua-c-num">';
				if (c.kind === "date") return '<col class="ua-c-date">';
				if (c.align === "center") return '<col class="ua-c-side">';
				return "<col>";
			})
			.join("");
		const body = this.body_rows.map((r, i) => this.row_html(r, i, gs, al)).join("");
		const foot = this.foot ? `<tfoot>${this.row_html(this.foot, -1, gs, al, true)}</tfoot>` : "";
		return (
			`<table class="ua-table ua-rpt ua-rpt--${this.cfg.report}${numeric ? " ua-rpt--fixed" : ""}${
				m.header.length > 1 ? " ua-rpt--two" : ""
			}" aria-label="${esc(m.title)}"><colgroup>${colgroup}</colgroup>` +
			`<thead><tr>${head1}</tr>${head2 ? `<tr>${head2}</tr>` : ""}</thead><tbody>${body}</tbody>${foot}</table>`
		);
	}

	row_html(r, i, gs, al, is_foot) {
		const cols = this.model.columns;
		const lvl = Math.min(r.level || 0, 3);
		const tds = cols
			.map((col, ci) => {
				const v = r.cells[col.key];
				const cls = `ua-${col.kind}${al(ci)}${gs.has(ci) ? " ua-gs" : ""}`;
				if (col.kind === "label") {
					const has = !!this.kids[r.id];
					const open = !this.collapsed.has(r.id);
					const tog = has
						? `<button type="button" class="ua-acc-tog" data-tog="${esc(r.id)}" aria-expanded="${open}" aria-label="${esc(
								open ? __("Згорнути") : __("Розгорнути")
						  )}">${icon("chev-r")}</button>`
						: '<span class="ua-acc-sp"></span>';
					const code = !is_foot && /^(\d{2,4})\s+(.+)$/.exec(v || "");
					const name = code
						? `<span class="ua-code">${esc(code[1])}</span><span class="ua-acc-name">${esc(code[2])}</span>`
						: `<span class="ua-acc-name">${esc(v)}</span>`;
					let extra = "";
					if (is_foot && this.balanced()) {
						extra = `<span class="ua-balanced" title="${esc(__("Дебет дорівнює кредиту"))}">${icon("check")}${esc(
							__("Сходиться")
						)}</span>`;
					}
					return `<td class="ua-acc-cell"><div class="ua-acc-in" style="--depth:${r.level || 0}">${tog}${name}${extra}</div></td>`;
				}
				let html = "";
				if (col.kind === "money" || col.kind === "qty") {
					html = fmt_number(v, col.kind === "money" ? 2 : 3);
					if (html && r.drill && !is_foot) html = `<span class="ua-amt" tabindex="0" role="button" data-i="${i}">${html}</span>`;
				} else if (col.kind === "lines") {
					html = (v || []).map((x, n) => (n ? `<span class="ua-cell-sub">${esc(x)}</span>` : `<b>${esc(x)}</b>`)).join("");
				} else if (col.kind === "doc" && r.links[col.key]) {
					const l = r.links[col.key];
					html = `<a href="${esc(frappe.utils.get_form_link(l.doctype, l.name))}">${esc(v)}</a>`;
				} else html = esc(v);
				return `<td class="${cls}">${html}</td>`;
			})
			.join("");
		const sub = r.kind === "item" && r.parent ? " ua-rsub" : "";
		const acc = /^\d{2,4}\s/.test(r.cells.label || "") ? " ua-is-acc" : "";
		return `<tr class="ua-lvl${lvl} ua-k-${esc(r.kind)}${r.bold ? " ua-bold" : ""}${sub}${acc}" data-id="${esc(r.id)}">${tds}</tr>`;
	}

	// debit = credit in every pair of the total row
	balanced() {
		const c = this.foot && this.foot.cells;
		if (!c) return false;
		const pairs = this.model.columns.filter((col) => /_dr$/.test(col.key) && c[col.key.replace(/_dr$/, "_cr")] !== undefined);
		return pairs.length > 0 && pairs.every((col) => Math.abs((c[col.key] || 0) - (c[col.key.replace(/_dr$/, "_cr")] || 0)) < 0.005);
	}

	// show or hide rows under closed parents; rows that open slide in (only a few: long lists open at once)
	apply_visibility(first) {
		const hidden = (r) => {
			let p = r.parent;
			while (p) {
				if (this.collapsed.has(p)) return true;
				p = this.parent_of[p];
			}
			return false;
		};
		const trs = this.$wrap.find("tbody tr");
		const shown = [];
		this.body_rows.forEach((r, i) => {
			const tr = trs[i];
			if (!tr) return;
			const h = hidden(r);
			if (!h && tr.hidden && !first) shown.push(tr);
			tr.hidden = h;
		});
		if (shown.length && shown.length <= 40) {
			shown.forEach((tr, k) => {
				tr.style.setProperty("--k", k);
				tr.classList.remove("ua-row-in");
				void tr.offsetWidth;
				tr.classList.add("ua-row-in");
			});
		}
		this.$wrap.find("[data-tog]").each((i, b) => {
			const open = !this.collapsed.has(b.dataset.tog);
			b.setAttribute("aria-expanded", String(open));
			b.setAttribute("aria-label", open ? __("Згорнути") : __("Розгорнути"));
		});
	}

	toggle(id) {
		if (this.collapsed.has(id)) this.collapsed.delete(id);
		else this.collapsed.add(id);
		this.apply_visibility();
	}

	// the table scrolls inside its card and fills the rest of the screen
	fit() {
		const wrap = this.$wrap && this.$wrap[0];
		if (!wrap || !$(wrap).is(":visible")) return;
		const room = window.innerHeight - wrap.getBoundingClientRect().top - 24;
		wrap.style.maxHeight = Math.max(room, 240) + "px";
	}

	// ---------- drill-down: OSV -> OSV by account -> card -> document
	amt_menu(el) {
		const r = this.body_rows[+el.dataset.i];
		const d = r && r.drill;
		if (!d) return;
		const items = [
			{ to: "account_card", icon: "file", label: __("Картка рахунку {0}", [d.account]) },
			{ to: "osv_account", icon: "sheet", label: __("ОСВ по рахунку {0}", [d.account]) },
		];
		const html =
			`<div class="ua-menu-label">${esc(__("Розшифровка · рахунок {0}", [d.account]))}</div>` +
			items.map((x) => `<button class="ua-menu-item" data-to="${x.to}">${icon(x.icon)}${esc(x.label)}</button>`).join("");
		el.classList.add("is-active");
		ua_accounting.ui.menu(el, html, (item) => this.drill(Object.assign({}, d, { to: item.dataset.to })), {
			cls: "ua-drill-pop",
			on_close: () => el.classList.remove("is-active"),
		});
	}

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
				ua_accounting.reports.table_html(m) +
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
