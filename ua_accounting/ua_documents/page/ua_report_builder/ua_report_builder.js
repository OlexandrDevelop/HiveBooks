// Universal report (a light analog of 1C СКД): columns, grouping, filters, sorting, conditional formatting, saved variants.
// Data: ua_accounting.api.report_builder (reporting/builder.py).
frappe.pages["ua-report-builder"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Універсальний звіт"), single_column: true });
	$(wrapper).find(".layout-main-section").append('<div class="ua-rb"></div>');
};

frappe.pages["ua-report-builder"].on_page_show = function (wrapper) {
	const ui = ua_accounting.ui;
	const esc = ui.esc;
	const API = "ua_accounting.api.report_builder.";
	const $root = $(wrapper).find(".ua-rb");
	const OPS = [
		["=", "дорівнює"], ["!=", "не дорівнює"], [">", "більше"], [">=", "не менше"], ["<", "менше"], ["<=", "не більше"],
		["in", "в списку"], ["not in", "не в списку"], ["like", "містить (%)"], ["between", "між"],
		["is set", "заповнено"], ["is not set", "не заповнено"],
	];
	const PARTS = [["", "—"], ["month", "Місяць"], ["year", "Рік"]];
	const DIRS = [["asc", "Зростання"], ["desc", "Спадання"]];
	const NUMERIC = ["Currency", "Float", "Int", "Percent"];

	const query = Object.assign({}, frappe.utils.get_query_params ? frappe.utils.get_query_params() : {}, frappe.route_options || {});
	frappe.route_options = null;
	const today = frappe.datetime.get_today();
	const parse = (text) => {
		try {
			return typeof text === "string" ? JSON.parse(text) : text || null;
		} catch (e) {
			return null;
		}
	};
	const current = ua_accounting.shell.current_org ? ua_accounting.shell.current_org() : null;
	const org = current && current.name;
	const st = {
		source: query.source || "ledger",
		variant: query.variant || "",
		sources: [],
		fields: [],
		settings: {},
		filters: Object.assign({ date_from: today.slice(0, 4) + "-01-01", date_to: today }, org ? { organizations: [org] } : {}, parse(query.filters) || {}),
		result: null,
		busy: false,
	};
	const BLOCKS = ["columns", "group_by", "filters", "sort", "format"];
	const field_of = (name) => st.fields.find((f) => f.fieldname === name) || { fieldname: name, label: name, fieldtype: "Data" };

	const call = (method, args) => frappe.call({ method: API + method, args }).then((r) => r.message);

	// ---------------------------------------------------------------- result
	const cell = (col, value) => {
		if (value === null || value === undefined || value === "") return "";
		if (NUMERIC.includes(col.fieldtype) && col.fieldtype !== "Int") return ui.money(value, { digits: col.fieldtype === "Float" ? 3 : 2 });
		if (col.fieldtype === "Date" && /^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(8, 10) + "." + value.slice(5, 7) + "." + value.slice(0, 4);
		return String(value);
	};
	const style_of = (s) => (s ? ` style="${s.color ? "color:" + esc(s.color) + ";" : ""}${s.bold ? "font-weight:600;" : ""}"` : "");

	const render_result = () => {
		const r = st.result;
		if (!r) return `<div class="ua-card ua-rb-card">${ui.skeleton_rows(6)}</div>`;
		if (!r.rows.length) return ui.empty_html({ title: __("Немає даних"), text: __("За обраними умовами записів не знайдено.") });
		const cols = r.columns;
		let html = `<div class="ua-card ua-rb-card"><div class="ua-table-wrap"><table class="ua-table"><thead><tr>${cols
			.map((c) => `<th${NUMERIC.includes(c.fieldtype) ? ' class="ua-r"' : ""}>${esc(c.label)}</th>`)
			.join("")}</tr></thead><tbody>`;
		r.rows.forEach((row) => {
			const level = row._level;
			html += `<tr${level ? ' class="ua-rb-group"' : ""}>`;
			cols.forEach((c, i) => {
				const num = NUMERIC.includes(c.fieldtype) && c.fieldtype !== "Int";
				const pad = level && i === level - 1 ? ` style="padding-left:${level * 12}px"` : "";
				const fmt = style_of((row._format || {})[c.fieldname]);
				html += `<td class="${num ? "ua-r ua-num" : ""}"${fmt || pad}>${esc(cell(c, row[c.fieldname]))}</td>`;
			});
			html += "</tr>";
		});
		let first = true;
		html += '</tbody><tfoot><tr class="ua-rb-total">';
		cols.forEach((c) => {
			const v = r.totals[c.fieldname];
			if (v === undefined) {
				html += `<td>${first ? esc(__("Разом")) : ""}</td>`;
				first = false;
			} else html += `<td class="ua-r ua-num">${esc(cell(c, v))}</td>`;
		});
		return html + `</tr></tfoot></table></div></div><div class="ua-rb-count">${esc(__("Записів"))}: ${r.count}</div>`;
	};

	const summary = () =>
		BLOCKS.map((b) => {
			const n = (st.settings[b] || []).length;
			return n ? `<span class="ua-chip">${esc(block_title(b))}: ${n}</span>` : "";
		}).join("");

	const block_title = (b) => ({ columns: "Колонки", group_by: "Групування", filters: "Відбір", sort: "Сортування", format: "Умовне оформлення" }[b]);

	const render = () => {
		const f = st.filters;
		$root.html(
			`<div class="ua-card ua-rb-head">
				<div class="ua-rb-pick">
					<label>${esc(__("Джерело"))}<select class="ua-rb-source">${st.sources
						.map((s) => `<option value="${esc(s.value)}"${s.value === st.source ? " selected" : ""}>${esc(s.label)}</option>`)
						.join("")}</select></label>
					<label>${esc(__("З"))}<input type="date" class="ua-rb-from" value="${esc(f.date_from || "")}"></label>
					<label>${esc(__("По"))}<input type="date" class="ua-rb-to" value="${esc(f.date_to || "")}"></label>
					${st.variant ? `<span class="ua-badge ua-badge--posted">${esc(st.variant)}</span>` : ""}
				</div>
				<div class="ua-rb-actions">
					<button type="button" class="ua-btn ua-btn--primary" data-act="run">${esc(__("Сформувати"))}</button>
					<button type="button" class="ua-btn ua-btn--ghost" data-act="excel">${esc(__("Excel"))}</button>
					<button type="button" class="ua-btn ua-btn--ghost" data-act="pdf">${esc(__("PDF"))}</button>
				</div>
			</div>
			<div class="ua-card ua-rb-bar">
				${BLOCKS.map((b) => `<button type="button" class="ua-btn ua-btn--secondary ua-btn--sm" data-block="${b}">${esc(__(block_title(b)))}</button>`).join("")}
				<span class="ua-rb-sep"></span>
				<button type="button" class="ua-btn ua-btn--secondary ua-btn--sm" data-act="save">${esc(__("Зберегти варіант"))}</button>
				<button type="button" class="ua-btn ua-btn--secondary ua-btn--sm" data-act="variants">${esc(__("Варіанти"))}</button>
				<span class="ua-rb-summary">${summary()}</span>
			</div>
			<div class="ua-rb-result">${render_result()}</div>`
		);
	};

	const run = () => {
		st.result = null;
		render();
		return call("run", { source: st.source, settings: st.settings, filters: st.filters, report: "universal" }).then(
			(res) => {
				st.result = res;
				render();
			},
			() => {
				st.result = { columns: [], rows: [], totals: {}, count: 0 };
				render();
			}
		);
	};

	// ---------------------------------------------------------------- editors of the blocks
	const select = (name, options, value) =>
		`<select class="ua-rb-in" data-k="${name}">${options
			.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(__(l))}</option>`)
			.join("")}</select>`;
	const field_select = (value) => select("field", st.fields.map((f) => [f.fieldname, f.label]), value);

	const DEF = {
		columns: {
			blank: () => ({ field: st.fields[0].fieldname, label: "" }),
			from: (x) => (typeof x === "string" ? { field: x, label: "" } : { field: x.field, label: x.label || "" }),
			html: (x) => field_select(x.field) + `<input class="ua-rb-in" data-k="label" placeholder="${esc(__("Заголовок"))}" value="${esc(x.label)}">`,
			to: (x) => (x.label ? { field: x.field, label: x.label } : x.field),
		},
		group_by: {
			blank: () => ({ field: st.fields[0].fieldname, part: "" }),
			from: (x) => ({ field: String(x).split(":")[0], part: String(x).split(":")[1] || "" }),
			html: (x) => field_select(x.field) + select("part", PARTS, x.part),
			to: (x) => (x.part ? `${x.field}:${x.part}` : x.field),
		},
		filters: {
			blank: () => ({ field: st.fields[0].fieldname, op: "=", value: "" }),
			from: (x) => ({ field: x.field, op: x.op, value: Array.isArray(x.value) ? x.value.join(", ") : x.value === undefined || x.value === null ? "" : x.value }),
			html: (x) => field_select(x.field) + select("op", OPS, x.op) + `<input class="ua-rb-in" data-k="value" placeholder="${esc(__("Значення"))}" value="${esc(x.value)}">`,
			to: (x) => ({ field: x.field, op: x.op, value: typed(x) }),
		},
		sort: {
			blank: () => ({ field: st.fields[0].fieldname, dir: "asc" }),
			from: (x) => ({ field: x.field, dir: x.dir || "asc" }),
			html: (x) => field_select(x.field) + select("dir", DIRS, x.dir),
			to: (x) => x,
		},
		format: {
			blank: () => ({ field: st.fields[0].fieldname, op: ">=", value: "", color: "#c00000", bold: false }),
			from: (x) => ({ field: x.field, op: x.op, value: Array.isArray(x.value) ? x.value.join(", ") : x.value === undefined || x.value === null ? "" : x.value, color: (x.style || {}).color || "", bold: !!(x.style || {}).bold }),
			html: (x) =>
				field_select(x.field) + select("op", OPS, x.op) + `<input class="ua-rb-in" data-k="value" value="${esc(x.value)}">` +
				`<input class="ua-rb-in ua-rb-color" type="color" data-k="color" value="${esc(x.color || "#c00000")}">` +
				`<label class="ua-rb-bold"><input type="checkbox" data-k="bold"${x.bold ? " checked" : ""}> ${esc(__("Жирний"))}</label>`,
			to: (x) => {
				const style = {};
				if (x.color) style.color = x.color;
				if (x.bold) style.bold = true;
				return { field: x.field, op: x.op, value: typed(x), style };
			},
		},
	};

	// a text of the editor as a value of the rule: number for numeric fields, list for in / between
	const typed = (x) => {
		if (x.op === "is set" || x.op === "is not set") return null;
		const numeric = NUMERIC.includes(field_of(x.field).fieldtype);
		const one = (t) => (numeric && t !== "" && !isNaN(Number(t)) ? Number(t) : t);
		if (["in", "not in", "between"].includes(x.op)) return String(x.value).split(",").map((t) => one(t.trim())).filter((t) => t !== "");
		return one(String(x.value).trim());
	};

	const edit_block = (block) => {
		const def = DEF[block];
		const title = __(block_title(block));
		const items = (st.settings[block] || []).map(def.from);
		const row_html = (x) => `<div class="ua-rb-row">${def.html(x)}<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-del aria-label="${esc(__("Видалити"))}">×</button></div>`;
		const d = ui.dialog({
			title,
			wide: true,
			html:
				`<div class="ua-dialog-head"><div><div class="ua-dialog-title">${esc(title)}</div></div>` +
				`<button class="ua-btn ua-btn--ghost ua-btn--icon" data-close aria-label="${esc(__("Закрити"))}">×</button></div>` +
				`<div class="ua-dialog-body"><div class="ua-rb-rows">${items.map(row_html).join("")}</div>` +
				`<button type="button" class="ua-btn ua-btn--ghost ua-btn--sm" data-add>${esc(__("Додати рядок"))}</button></div>` +
				`<div class="ua-dialog-foot"><span></span><div class="ua-right"><button class="ua-btn" data-close>${esc(__("Скасувати"))}</button>` +
				`<button class="ua-btn ua-btn--primary" data-apply>${esc(__("Застосувати"))}</button></div></div>`,
		});
		const $d = $(d.el);
		$d.on("click", "[data-add]", () => $d.find(".ua-rb-rows").append(row_html(def.blank())));
		$d.on("click", "[data-del]", function () {
			$(this).closest(".ua-rb-row").remove();
		});
		$d.on("click", "[data-apply]", () => {
			const out = [];
			$d.find(".ua-rb-row").each(function () {
				const x = {};
				$(this).find("[data-k]").each(function () {
					x[this.dataset.k] = this.type === "checkbox" ? this.checked : $(this).val();
				});
				out.push(def.to(x));
			});
			st.settings[block] = out;
			d.close();
			run();
		});
	};

	// ---------------------------------------------------------------- variants

	// pick: the docname of a variant (menu) or its name (address, default variant)
	const load_variant = (pick) =>
		call("list_variants", { source: st.source }).then((list) => {
			const v = list.find((x) => x.name === pick) || list.find((x) => x.variant_name === pick);
			if (!v) return run();
			return frappe.db.get_value("UA Report Variant", v.name, "settings").then((r) => {
				st.settings = parse(r.message && r.message.settings) || {};
				st.variant = v.variant_name;
				return run();
			});
		});

	const save_dialog = () => {
		const d = ui.dialog({
			title: __("Зберегти варіант"),
			html:
				`<div class="ua-dialog-head"><div><div class="ua-dialog-title">${esc(__("Зберегти варіант"))}</div></div>` +
				`<button class="ua-btn ua-btn--ghost ua-btn--icon" data-close aria-label="${esc(__("Закрити"))}">×</button></div>` +
				`<div class="ua-dialog-body"><div class="ua-field"><label class="ua-field-label" for="ua-rb-name">${esc(__("Назва варіанту"))}</label>` +
				`<div class="ua-input"><input id="ua-rb-name" value="${esc(st.variant)}" autofocus></div></div>` +
				`<label class="ua-rb-check"><input type="checkbox" id="ua-rb-shared"> ${esc(__("Загальний (для всіх)"))}</label>` +
				`<label class="ua-rb-check"><input type="checkbox" id="ua-rb-default"> ${esc(__("Основний"))}</label></div>` +
				`<div class="ua-dialog-foot"><span></span><div class="ua-right"><button class="ua-btn" data-close>${esc(__("Скасувати"))}</button>` +
				`<button class="ua-btn ua-btn--primary" data-save>${esc(__("Зберегти"))}</button></div></div>`,
		});
		$(d.el).on("click", "[data-save]", () => {
			const name = $(d.el).find("#ua-rb-name").val().trim();
			if (!name) return frappe.show_alert({ message: __("Вкажіть назву варіанту"), indicator: "orange" });
			call("save_variant", {
				variant_name: name,
				source: st.source,
				settings: st.settings,
				is_shared: $(d.el).find("#ua-rb-shared").prop("checked") ? 1 : 0,
				is_default: $(d.el).find("#ua-rb-default").prop("checked") ? 1 : 0,
			}).then(() => {
				st.variant = name;
				d.close();
				render();
				frappe.show_alert({ message: __("Варіант збережено"), indicator: "green" });
			});
		});
	};

	const variants_menu = (trigger) =>
		call("list_variants", { source: st.source }).then((list) => {
			const item = (v) =>
				`<div class="ua-rb-variant"><button type="button" class="ua-menu-item" data-pick="${esc(v.name)}" data-vname="${esc(v.variant_name)}">${esc(v.variant_name)}${v.is_shared ? ` · ${esc(__("загальний"))}` : ""}${v.is_default ? " ★" : ""}</button>` +
				(v.is_mine ? `<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-del-variant="${esc(v.name)}" aria-label="${esc(__("Видалити"))}">×</button>` : "") +
				"</div>";
			const html = list.length ? list.map(item).join("") : `<div class="ua-rb-none">${esc(__("Збережених варіантів немає"))}</div>`;
			ui.menu(
				trigger,
				html,
				(el, e) => {
					const del = e.target.closest("[data-del-variant]");
					if (del) {
						call("delete_variant", { name: del.dataset.delVariant }).then(() => frappe.show_alert({ message: __("Варіант видалено"), indicator: "green" }));
						return;
					}
					load_variant(el.dataset.pick);
				},
				{ cls: "ua-rb-pop" }
			);
		});

	// ---------------------------------------------------------------- files
	const download = (method, type) => {
		call(method, { source: st.source, settings: st.settings, filters: st.filters, report: "universal" }).then((res) => {
			const bytes = Uint8Array.from(atob(res.content), (c) => c.charCodeAt(0));
			const url = URL.createObjectURL(new Blob([bytes], { type }));
			const a = document.createElement("a");
			a.href = url;
			a.download = res.filename;
			document.body.appendChild(a);
			a.click();
			a.remove();
			setTimeout(() => URL.revokeObjectURL(url), 5000);
		});
	};

	// ---------------------------------------------------------------- events
	const load_fields = () =>
		call("get_fields", { source: st.source }).then((fields) => {
			st.fields = fields;
		});

	$root.off(".rb");
	$root.on("change.rb", ".ua-rb-source", function () {
		st.source = this.value;
		st.settings = {};
		st.variant = "";
		load_fields().then(run);
	});
	$root.on("change.rb", ".ua-rb-from, .ua-rb-to", () => {
		st.filters.date_from = $root.find(".ua-rb-from").val();
		st.filters.date_to = $root.find(".ua-rb-to").val();
	});
	$root.on("click.rb", "[data-block]", function () {
		if (st.fields.length) edit_block(this.dataset.block);
	});
	$root.on("click.rb", "[data-act]", function () {
		const act = this.dataset.act;
		if (act === "run") run();
		else if (act === "excel") download("export_excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
		else if (act === "pdf") download("export_pdf", "application/pdf");
		else if (act === "save") save_dialog();
		else if (act === "variants") variants_menu(this);
	});

	render();
	Promise.all([call("sources"), load_fields()]).then(([sources]) => {
		st.sources = sources;
		if (st.variant) return load_variant(st.variant);
		// the default variant of the user, when there is one
		return call("list_variants", { source: st.source }).then((list) => {
			const def = list.find((v) => v.is_mine && v.is_default);
			return def ? load_variant(def.name) : run();
		});
	});
};
