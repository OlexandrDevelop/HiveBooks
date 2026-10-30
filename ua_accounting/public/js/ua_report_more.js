// Pages of the extra accounting reports (T-443): subconto analysis, OSV by subconto, account turnovers,
// account analysis, general ledger, journal-order, chess sheet, entries report, subconto card, accounting check.
// One class for all: the server (ua_accounting.api.reports) returns a table model, the page draws it with the
// same look as the OSV pages (ua_report.css). Each page gives only a config: route, title, filter fields.
frappe.provide("ua_accounting.reports");

const MORE_API = "ua_accounting.api.reports.";
const mesc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const micon = (name, cls) => ua_accounting.ui.icon(name, cls);

// The page "ua-account-turnover" has the same URL as the list of the DocType "UA Account Turnover".
// The desk gives a short URL to the DocType, so the page wins here; the list stays at
// /desk/ua-account-turnover/view/list.
(function () {
	const router = frappe.router;
	if (!router || router.ua_pages_patched) return;
	router.ua_pages_patched = true;
	const orig = router.convert_to_standard_route;
	router.convert_to_standard_route = function (route) {
		if (route.length === 1 && route[0] === "ua-account-turnover") return Promise.resolve(route);
		return orig.call(this, route);
	};
})();

const ACCOUNT = { key: "account", label: __("Рахунок"), type: "link", options: "UA Account" };
const SUBCONTO_TYPE = { key: "subconto_type", label: __("Вид субконто"), type: "subconto_type" };

ua_accounting.reports.MORE = {
	subconto_analysis: {
		route: "ua-subconto-analysis",
		title: __("Аналіз субконто"),
		fields: [{ ...SUBCONTO_TYPE, reqd: 1 }, ACCOUNT],
	},
	osv_subconto: {
		route: "ua-osv-subconto",
		title: __("ОСВ по субконто"),
		fields: [{ ...ACCOUNT, reqd: 1 }, { key: "levels", label: __("Групування"), type: "levels", reqd: 1 }],
	},
	account_turnover: {
		route: "ua-account-turnover",
		title: __("Обороти рахунку"),
		fields: [{ ...ACCOUNT, reqd: 1 }],
		extra: { step: "month" },
	},
	account_analysis: { route: "ua-account-analysis", title: __("Аналіз рахунку"), fields: [{ ...ACCOUNT, reqd: 1 }] },
	general_ledger: { route: "ua-general-ledger", title: __("Головна книга"), fields: [] },
	journal_order: { route: "ua-journal-order", title: __("Журнал-ордер"), fields: [{ ...ACCOUNT, reqd: 1 }] },
	chess_sheet: { route: "ua-chess-sheet", title: __("Шахова відомість"), fields: [] },
	entries_report: {
		route: "ua-entries-report",
		title: __("Звіт по проводках"),
		fields: [
			{ key: "account_dr", label: __("Рахунок Дт"), type: "link", options: "UA Account" },
			{ key: "account_cr", label: __("Рахунок Кт"), type: "link", options: "UA Account" },
			{ key: "amount_from", label: __("Сума від"), type: "float" },
			{ key: "amount_to", label: __("Сума до"), type: "float" },
		],
	},
	subconto_card: {
		route: "ua-subconto-card",
		title: __("Картка субконто"),
		fields: [
			{ ...SUBCONTO_TYPE, reqd: 1 },
			{ key: "subconto", label: __("Значення"), type: "data" },
		],
	},
	accounting_check: {
		route: "ua-accounting-check",
		title: __("Експрес-перевірка ведення обліку"),
		fields: [],
		empty: __("Помилок не знайдено"),
	},
};

// the pages a drill-down can lead to (route -> title for the menu)
ua_accounting.reports.MORE_TITLES = {
	"ua-subconto-card": __("Картка субконто"),
	"ua-account-card": __("Картка рахунку"),
	"ua-entries-report": __("Звіт по проводках"),
};

ua_accounting.reports.MorePage = class MorePage {
	constructor(wrapper, cfg) {
		this.wrapper = wrapper;
		this.cfg = cfg;
		this.model = null;
		this.controls = {};
		this.run_id = 0;
		this.extra_subconto = [];
		frappe.ui.make_app_page({ parent: wrapper, title: cfg.title, single_column: true });
		this.$root = $('<div class="ua-report"></div>').appendTo($(wrapper).find(".layout-main-section"));
		this.make_head();
		this.make_settings();
		this.make_result();
		this.bind();
		$(wrapper).on("show", () => this.on_show());
		this.types_ready = frappe.xcall("ua_accounting.reporting.api.subconto_types").then((types) => {
			this.types = types;
			this.$root.find("select[data-type-select]").each((i, s) => this.fill_types(s));
		});
		$(document).on("ua-org-changed", () => {
			const o = this.shell_org();
			if (!o) return;
			this.org.set_value(o).then(() => {
				if (this.model && $(this.wrapper).is(":visible")) this.run();
			});
		});
	}

	shell_org() {
		const sh = ua_accounting.shell;
		const org = sh && sh.current_org && sh.current_org();
		return org ? org.name : "";
	}

	// ---------- page head
	make_head() {
		this.$root.append(`
			<div class="ua-ph">
				<h1 class="ua-ph-title"><span class="ua-rpt-title">${mesc(this.cfg.title)}</span>
					<span class="ua-tag">${mesc(__("Бухгалтерський облік"))}</span></h1>
				<div class="ua-ph-actions">
					<button type="button" class="ua-btn" data-act="print">${micon("printer")}${mesc(__("Друк"))}</button>
					<button type="button" class="ua-btn" data-act="excel">${micon("sheet")}Excel</button>
					<button type="button" class="ua-btn ua-btn--primary" data-act="run">${micon("refresh")}${mesc(
						__("Сформувати")
					)}<span class="ua-kbd">Ctrl Enter</span></button>
				</div>
			</div>`);
	}

	// ---------- settings: organization, period and the fields of the report
	make_settings() {
		const $set = $(`<div class="ua-settings"><section class="ua-card" aria-label="${mesc(__("Налаштування звіту"))}">
			<div class="ua-set-row ua-set-main"></div>
			<div class="ua-set-row ua-set-opts"></div>
		</section></div>`).appendTo(this.$root);
		const $main = $set.find(".ua-set-main");
		const $opts = $set.find(".ua-set-opts");
		this.org = this.control($main, { fieldtype: "Link", fieldname: "organization", options: "UA Organization", label: __("Організація") });
		const [from, to] = this.month_range();
		this.date_from = this.control($main, { fieldtype: "Date", fieldname: "date_from", label: __("Період з"), default: from });
		this.date_to = this.control($main, { fieldtype: "Date", fieldname: "date_to", label: __("по"), default: to });
		this.date_from.set_value(from);
		this.date_to.set_value(to);
		const org = this.shell_org();
		this.ready = org ? this.org.set_value(org) : Promise.resolve();

		for (const f of this.cfg.fields) {
			if (f.type === "subconto_type") {
				this.controls[f.key] = $(
					`<label class="ua-set-label">${mesc(f.label)} <select class="ua-input ua-input--sm" data-type-select="${f.key}"></select></label>`
				).appendTo($opts);
				this.fill_types(this.controls[f.key].find("select")[0]);
			} else if (f.type === "levels") {
				const $l = $(`<span class="ua-set-label">${mesc(f.label)}</span>`).appendTo($opts);
				this.levels = [1, 2, 3].map((n) =>
					$(`<select class="ua-input ua-input--sm" data-type-select="level${n}" data-blank="1" aria-label="${mesc(f.label)} ${n}"></select>`)
						.appendTo($opts)
						.each((i, s) => this.fill_types(s))
				);
				this.controls[f.key] = $l;
			} else {
				const df = {
					fieldname: f.key,
					label: f.label,
					fieldtype: { link: "Link", float: "Float", data: "Data" }[f.type],
					options: f.options,
				};
				this.controls[f.key] = this.control($opts, df);
			}
		}
	}

	month_range() {
		const m = moment();
		return [m.clone().startOf("month").format("YYYY-MM-DD"), m.clone().endOf("month").format("YYYY-MM-DD")];
	}

	control(parent, df) {
		const $f = $('<div class="ua-f ua-f--lbl"></div>').appendTo(parent);
		const control = frappe.ui.form.make_control({ df, parent: $f, render_input: true });
		control.refresh();
		return control;
	}

	fill_types(select) {
		if (!select) return;
		const blank = !this.cfg.fields.some((f) => f.reqd && f.type === "subconto_type") || select.dataset.blank;
		const cur = select.value;
		const options = [`<option value="">${blank ? "—" : ""}</option>`].concat(
			(this.types || []).map((t) => `<option value="${mesc(t.name)}">${mesc(t.title)}</option>`)
		);
		select.innerHTML = options.join("");
		select.value = cur;
	}

	// a subconto type given as the code or as the DocType it refers to
	type_value(v) {
		const t = (this.types || []).find((x) => x.name === v || x.reference_doctype === v);
		return t ? t.name : v || "";
	}

	make_result() {
		this.$card = $(`<section class="ua-card ua-rpt-card" aria-label="${mesc(__("Звіт"))}">
			<div class="ua-rpt-head"><div class="ua-rpt-meta"></div>
				<span class="ua-hint" hidden>${micon("info")}${mesc(__("Клік по рядку або сумі — розшифровка"))}</span></div>
			<div class="ua-rpt-msg" hidden></div>
			<div class="ua-table-wrap ua-rpt-wrap"></div>
		</section>`).appendTo(this.$root);
		this.$wrap = this.$card.find(".ua-rpt-wrap");
		this.$wrap.on("scroll", () => this.$wrap.toggleClass("is-scrolled", this.$wrap[0].scrollTop > 0));
		this.show_state({
			art: "sheet",
			title: __("Налаштуйте звіт"),
			text: __("Оберіть період і відбір, потім натисніть «Сформувати»."),
		});
	}

	bind() {
		this.$root.on("click", "[data-act]", (e) => {
			const act = e.currentTarget.dataset.act;
			if (act === "run" || act === "retry") this.run();
			else if (act === "print") this.print();
			else if (act === "excel") this.export_excel();
		});
		this.$wrap.on("click", "tr[data-id]", (e) => this.on_row_click(e));
		$(document).on("keydown", (e) => {
			if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey)) return;
			if (!$(this.wrapper).is(":visible") || $(".modal.show").length) return;
			e.preventDefault();
			this.run();
		});
		$(window).on("resize", () => this.fit());
	}

	// ---------- filters
	get_filters() {
		const f = {
			organizations: this.org.get_value() ? [this.org.get_value()] : [],
			date_from: this.date_from.get_value(),
			date_to: this.date_to.get_value(),
			...(this.cfg.extra || {}),
		};
		for (const fd of this.cfg.fields) {
			const c = this.controls[fd.key];
			if (fd.type === "subconto_type") f[fd.key] = c.find("select").val() || "";
			else if (fd.type === "levels") f.levels = this.levels.map(($s) => $s.val()).filter(Boolean);
			else f[fd.key] = c.get_value() || "";
		}
		this.drop_stale_keep(f);
		Object.assign(f, this.keep || {});
		if (this.cfg.report === "subconto_card" && f.subconto && this.extra_subconto.length) {
			f.subconto = this.extra_subconto.concat([{ type: f.subconto_type, value: f.subconto }]);
		}
		return f;
	}

	// the user edited a visible field after a drill-down: the hidden account scope no longer applies
	drop_stale_keep(f) {
		const snap = this.keep_snap;
		if (!snap || !this.keep || !(this.keep.accounts || this.keep.scope_side)) return;
		if (Object.keys(snap).some((k) => (f[k] || "") !== snap[k])) {
			delete this.keep.accounts;
			delete this.keep.scope_side;
			this.keep_snap = null;
		}
	}

	missing() {
		const f = this.get_filters();
		if (!f.organizations.length) return __("Оберіть організацію");
		if (!f.date_from || !f.date_to) return __("Вкажіть період");
		for (const fd of this.cfg.fields) {
			if (!fd.reqd) continue;
			if (fd.type === "levels" ? !f.levels.length : !f[fd.key]) return __("Заповніть поле «{0}»", [fd.label]);
		}
		return "";
	}

	async set_filters(f) {
		await this.ready;
		await this.types_ready;
		const org = (f.organizations && f.organizations[0]) || f.organization;
		if (org) await this.org.set_value(org);
		if (f.date_from) await this.date_from.set_value(f.date_from);
		if (f.date_to) await this.date_to.set_value(f.date_to);
		this.extra_subconto = [];
		// filters of a drill-down that the page has no field for travel along with every run
		this.keep = {};
		const own = new Set(this.cfg.fields.map((x) => x.key));
		for (const k of ["currency", "scope_side", "accounts", "subconto"]) {
			if (f[k] === undefined || f[k] === null || f[k] === "" || (Array.isArray(f[k]) && !f[k].length)) continue;
			if (k === "accounts" && own.has("account")) continue;
			if (k === "subconto" && own.has("subconto")) continue;
			this.keep[k] = f[k];
		}
		for (const fd of this.cfg.fields) {
			const c = this.controls[fd.key];
			let v = f[fd.key];
			if (fd.key === "account" && !v && f.accounts) v = f.accounts[0];
			if (fd.type === "levels") {
				(f.levels || []).forEach((t, i) => this.levels[i] && this.levels[i].val(this.type_value(t)));
			} else if (fd.type === "subconto_type") {
				const last = Array.isArray(f.subconto) && f.subconto.length ? f.subconto[f.subconto.length - 1] : null;
				c.find("select").val(this.type_value(v || (last && last.type)));
			} else if (fd.key === "subconto" && Array.isArray(v)) {
				// several values from a drill-down: the last one is shown, the others stay in the filter
				const last = v[v.length - 1];
				this.extra_subconto = v.slice(0, -1);
				await c.set_value(last.value);
			} else if (v !== undefined && v !== null) await c.set_value(v);
		}
		this.keep_snap = null;
		if (this.keep.accounts || this.keep.scope_side) {
			const snap = {};
			for (const fd of this.cfg.fields) {
				if (/^account/.test(fd.key) && fd.type !== "levels") snap[fd.key] = this.controls[fd.key].get_value() || "";
			}
			this.keep_snap = snap;
		}
	}

	on_show() {
		const ro = frappe.route_options;
		if (ro && ro.filters) {
			frappe.route_options = null;
			// the v16 router passes route options through the URL: objects come back as JSON text
			const f = typeof ro.filters === "string" ? JSON.parse(ro.filters) : ro.filters;
			this.set_filters(f).then(() => this.run());
		} else if (!this.started && !this.cfg.fields.some((x) => x.reqd)) {
			this.started = true;
			this.ready.then(() => this.run());
		}
		this.fit();
	}

	// ---------- run and draw
	run() {
		const miss = this.missing();
		if (miss) {
			this.model = null;
			this.show_state({ art: "sheet", title: miss, text: __("Заповніть налаштування і натисніть «Сформувати».") });
			return Promise.resolve();
		}
		this.started = true;
		const id = ++this.run_id;
		const $btn = this.$root.find('[data-act="run"]');
		$btn.addClass("is-loading").prop("disabled", true);
		return new Promise((resolve) => {
			frappe.call({
				method: MORE_API + "run",
				args: { report: this.cfg.report, filters: JSON.stringify(this.get_filters()) },
				callback: (r) => {
					if (id !== this.run_id) return resolve();
					$btn.removeClass("is-loading").prop("disabled", false);
					this.model = r.message.table;
					this.generated = frappe.datetime.now_datetime();
					this.draw();
					resolve();
				},
				error: () => {
					if (id !== this.run_id) return resolve();
					$btn.removeClass("is-loading").prop("disabled", false);
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

	show_state(o) {
		this.$card.find(".ua-rpt-head").prop("hidden", !this.model);
		this.$card.find(".ua-hint, .ua-rpt-msg").prop("hidden", true);
		this.$wrap.html(`<div class="ua-state-box">${ua_accounting.ui.empty_html(o)}</div>`);
		this.fit();
	}

	meta_html() {
		const parts = (this.model.lines || []).map((l, i) => {
			const k = l.indexOf(": ");
			if (i === 0 && k > 0) return `<span>${mesc(l.slice(0, k + 2))}<b>${mesc(l.slice(k + 2))}</b></span>`;
			return `<span>${mesc(l)}</span>`;
		});
		parts.push(
			`<span>${mesc(__("Сформовано {0}", [frappe.datetime.str_to_user(this.generated).slice(0, 16)]))} · ${mesc(
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
		const last = m.rows[m.rows.length - 1];
		this.foot = last && last.kind === "total" ? last : null;
		this.body_rows = this.foot ? m.rows.slice(0, -1) : m.rows;
		this.by_id = {};
		m.rows.forEach((r) => (this.by_id[r.id] = r));
		if (!this.body_rows.length) {
			this.show_state({
				art: "inbox",
				title: this.cfg.empty || __("За період немає даних"),
				text: this.cfg.empty ? "" : __("За обраний період і відбір немає залишків і оборотів. Змініть період або відбір."),
			});
			return;
		}
		this.$card.find(".ua-hint").prop("hidden", !m.rows.some((r) => r.drill || r.cell_drill));
		this.$wrap.html(this.table_html()).removeClass("is-scrolled");
		this.$wrap[0].scrollTop = 0;
		this.fit();
	}

	table_html() {
		const m = this.model;
		const cols = m.columns;
		const al = (c) => (c.align === "right" ? " ua-r" : c.align === "center" ? " ua-c" : "");
		const grouped = m.header.length > 1;
		let pos = 0;
		const head1 = m.header[0]
			.map((c) => {
				const i = pos;
				pos += c.colspan || 1;
				const two = (c.rowspan || 1) > 1 || !grouped;
				return `<th colspan="${c.colspan || 1}" rowspan="${c.rowspan || 1}" class="${two ? "ua-h-two" : "ua-h-group"}${al(
					cols[i]
				)}" scope="${two ? "col" : "colgroup"}">${mesc(c.label)}</th>`;
			})
			.join("");
		let k = 0;
		const under = [];
		pos = 0;
		m.header[0].forEach((c) => {
			if ((c.rowspan || 1) === 1) for (let j = 0; j < (c.colspan || 1); j++) under.push(pos + j);
			pos += c.colspan || 1;
		});
		const head2 = (m.header[1] || [])
			.map((c) => `<th class="ua-h-sub${al(cols[under[k++]])}" scope="col">${mesc(c.label)}</th>`)
			.join("");
		const body = this.body_rows.map((r) => this.row_html(r)).join("");
		const foot = this.foot ? `<tfoot>${this.row_html(this.foot, true)}</tfoot>` : "";
		return (
			`<table class="ua-table ua-rpt ua-rpt--more ua-rpt--${this.cfg.report}" aria-label="${mesc(m.title)}">` +
			`<thead><tr>${head1}</tr>${head2 ? `<tr>${head2}</tr>` : ""}</thead><tbody>${body}</tbody>${foot}</table>`
		);
	}

	cell_html(col, r, is_foot) {
		const v = r.cells[col.key];
		if (col.kind === "money" || col.kind === "qty") {
			const text =
				v === null || v === undefined || v === "" || Math.abs(v) < 0.0000001
					? ""
					: format_number(v, null, col.kind === "money" ? 2 : 3);
			return text;
		}
		if (col.kind === "lines") return (v || []).map((x) => mesc(x)).join("<br>");
		if (col.kind === "doc" && r.links && r.links[col.key]) {
			const l = r.links[col.key];
			return `<a href="${mesc(frappe.utils.get_form_link(l.doctype, l.name))}">${mesc(v)}</a>`;
		}
		if (col.kind === "label") {
			const code = !is_foot && /^(\d{2,4})\s+(.+)$/.exec(v || "");
			return code
				? `<span class="ua-code">${mesc(code[1])}</span><span class="ua-acc-name">${mesc(code[2])}</span>`
				: `<span class="ua-acc-name">${mesc(v)}</span>`;
		}
		return mesc(v);
	}

	row_html(r, is_foot) {
		const tds = this.model.columns
			.map((col) => {
				const html = this.cell_html(col, r, is_foot);
				if (col.kind === "label") {
					return `<td class="ua-acc-cell" data-key="${mesc(col.key)}"><div class="ua-acc-in" style="--depth:${r.level || 0}">${html}</div></td>`;
				}
				const cls = `ua-${col.kind}${col.align === "right" ? " ua-r" : col.align === "center" ? " ua-c" : ""}`;
				return `<td class="${cls}" data-key="${mesc(col.key)}">${html}</td>`;
			})
			.join("");
		const can = !is_foot && (r.drill || r.cell_drill) ? " ua-drillable" : "";
		const bold = r.bold ? " ua-bold" : "";
		return `<tr class="ua-lvl${Math.min(r.level || 0, 3)} ua-k-${mesc(r.kind)}${bold}${can}" data-id="${mesc(r.id)}">${tds}</tr>`;
	}

	fit() {
		const wrap = this.$wrap && this.$wrap[0];
		if (!wrap || !$(wrap).is(":visible")) return;
		const room = window.innerHeight - wrap.getBoundingClientRect().top - 24;
		wrap.style.maxHeight = Math.max(room, 240) + "px";
	}

	// ---------- drill-down
	on_row_click(e) {
		if ($(e.target).closest("a").length) return;
		const tr = e.currentTarget;
		const r = this.by_id[tr.dataset.id];
		if (!r || tr.closest("tfoot")) return;
		const td = $(e.target).closest("td")[0] || tr;
		const d = (r.cell_drill && r.cell_drill[td.dataset.key]) || r.drill;
		if (!d) return;
		const title = ua_accounting.reports.MORE_TITLES[d.report] || d.report;
		const html =
			`<div class="ua-menu-label">${mesc(__("Розшифровка"))}</div>` +
			`<button class="ua-menu-item" data-to="${mesc(d.report)}">${micon("file")}${mesc(__("Відкрити: {0}", [title]))}</button>`;
		td.classList.add("is-active");
		ua_accounting.ui.menu(td, html, () => this.drill(d), {
			cls: "ua-drill-pop",
			on_close: () => td.classList.remove("is-active"),
		});
	}

	drill(d) {
		frappe.route_options = { filters: d.filters };
		frappe.set_route(d.report);
	}

	// ---------- print, Excel
	call(method) {
		return frappe.xcall(MORE_API + method, { report: this.cfg.report, filters: JSON.stringify(this.get_filters()) });
	}

	async print() {
		const miss = this.missing();
		if (miss) return frappe.msgprint(miss);
		const w = window.open("", "_blank");
		if (!w) return frappe.msgprint(__("Браузер заблокував вікно друку"));
		const res = await this.call("print_html");
		w.document.write(res.html);
		w.document.close();
		w.focus();
		w.print();
	}

	async export_excel() {
		const miss = this.missing();
		if (miss) return frappe.msgprint(miss);
		const res = await this.call("export_excel");
		const bytes = Uint8Array.from(atob(res.content), (c) => c.charCodeAt(0));
		const blob = new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = res.filename;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	}
};

// the page scripts call this
ua_accounting.reports.open_more = function (wrapper, code) {
	const cfg = Object.assign({ report: code }, ua_accounting.reports.MORE[code]);
	wrapper.ua_report = new ua_accounting.reports.MorePage(wrapper, cfg);
};
