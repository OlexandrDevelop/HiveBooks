// Lists of UA doctypes (design/mockups/list-documents.html, catalog-items.html).
// Frappe's ListView stays the engine (data, paging, selection, filters, realtime); we draw:
//   page head (title + count + text), view tabs, filter chips, our table rows and header,
//   footer "Показано X–Y з N" with Frappe page sizes, bulk bar, loading / empty / error states.
// All frappe.listview_settings of the app are registered here, in one place.
// A doctype list script (<doctype>_list.js) that sets frappe.listview_settings for the same doctype
// must merge with these (Object.assign) or call ua_accounting.list.setup itself.
frappe.provide("ua_accounting.list");

(function () {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const icon = (n, c) => ua_accounting.ui.icon(n, c);
	const L = ua_accounting.list;

	// ---------------------------------------------------------------- columns
	// col: {key, label, kind, field, sub, width, align}. kind: date | docno | link2 | link | money | text | owner | status | title
	const TRADE = [
		{ key: "posting_date", label: "Дата", kind: "date", sort: "posting_date", width: 100 },
		{ key: "name", label: "Номер", kind: "docno", sort: "name", width: 148 },
		{ key: "counterparty", label: "Контрагент · Договір", kind: "link2", field: "counterparty", sub: "contract", grow: 1 },
		{ key: "warehouse", label: "Склад", kind: "link", field: "warehouse", width: 136 },
		{ key: "total_amount", label: "Сума", kind: "money", field: "total_amount", sort: "total_amount", width: 116, align: "r" },
		{ key: "currency", label: "Валюта", kind: "text", field: "currency", width: 64 },
		{ key: "owner", label: "Відповідальний", kind: "owner", width: 150 },
		{ key: "status", label: "Статус", kind: "status", width: 144 },
	];
	const CASH = [
		{ key: "posting_date", label: "Дата", kind: "date", sort: "posting_date", width: 100 },
		{ key: "name", label: "Номер", kind: "docno", sort: "name", width: 148 },
		{ key: "counterparty", label: "Контрагент · Договір", kind: "link2", field: "counterparty", sub: "contract", grow: 1 },
		{ key: "place", label: "Каса / рахунок", kind: "link", field: "cash_desk", alt: "bank_account", width: 150 },
		{ key: "amount", label: "Сума", kind: "money", field: "amount", sort: "amount", width: 116, align: "r" },
		{ key: "currency", label: "Валюта", kind: "text", field: "currency", width: 64 },
		{ key: "owner", label: "Відповідальний", kind: "owner", width: 150 },
		{ key: "status", label: "Статус", kind: "status", width: 144 },
	];
	const OPERATION = [
		{ key: "posting_date", label: "Дата", kind: "date", sort: "posting_date", width: 100 },
		{ key: "name", label: "Номер", kind: "docno", sort: "name", width: 148 },
		{ key: "content", label: "Зміст", kind: "text", field: "content", grow: 1 },
		{ key: "owner", label: "Відповідальний", kind: "owner", width: 150 },
		{ key: "status", label: "Статус", kind: "status", width: 144 },
	];
	const TAX = [
		{ key: "posting_date", label: "Дата", kind: "date", sort: "posting_date", width: 100 },
		{ key: "name", label: "Номер", kind: "docno", sort: "name", width: 148 },
		{ key: "counterparty", label: "Контрагент · Договір", kind: "link2", field: "counterparty", sub: "contract", grow: 1 },
		{ key: "direction", label: "Напрям", kind: "text", field: "direction", width: 100 },
		{ key: "total_vat", label: "ПДВ", kind: "money", field: "total_vat", sort: "total_vat", width: 116, align: "r" },
		{ key: "erpn_status", label: "Статус ЄРПН", kind: "text", field: "erpn_status", width: 140 },
		{ key: "owner", label: "Відповідальний", kind: "owner", width: 150 },
		{ key: "status", label: "Статус", kind: "status", width: 144 },
	];
	const TAX_ADJ = TAX.map((c) => (c.key === "total_vat" ? { ...c, key: "total_delta_vat", field: "total_delta_vat", sort: "total_delta_vat" } : c));
	const ALLOCATION = [
		{ key: "posting_date", label: "Дата", kind: "date", sort: "posting_date", width: 100 },
		{ key: "name", label: "Номер", kind: "docno", sort: "name", width: 148 },
		{ key: "credit_total", label: "Податковий кредит", kind: "money", field: "credit_total", width: 136, align: "r" },
		{ key: "disallowed_credit", label: "Не дозволено", kind: "money", field: "disallowed_credit", width: 136, align: "r" },
		{ key: "owner", label: "Відповідальний", kind: "owner", grow: 1 },
		{ key: "status", label: "Статус", kind: "status", width: 144 },
	];
	L.COLUMNS = {
		"UA Tax Invoice": TAX,
		"UA Tax Adjustment": TAX_ADJ,
		"UA VAT Allocation": ALLOCATION,
		"UA Sales Invoice": TRADE,
		"UA Purchase Receipt": TRADE,
		"UA Customer Order": TRADE,
		"UA Supplier Order": TRADE,
		"UA Cash Receipt": CASH,
		"UA Cash Payment": CASH,
		"UA Journal Operation": OPERATION,
	};

	L.TEXT = {
		"UA Tax Invoice": "Видані та отримані податкові накладні зі статусом реєстрації в ЄРПН.",
		"UA Tax Adjustment": "Розрахунки коригування до податкових накладних.",
		"UA VAT Allocation": "Розподіл податкового кредиту між оподатковуваними і неоподатковуваними операціями.",
		"UA Sales Invoice": "Відвантаження товарів і послуг покупцям.",
		"UA Purchase Receipt": "Отримання товарів і послуг від постачальників.",
		"UA Customer Order": "Замовлення покупців до відвантаження.",
		"UA Supplier Order": "Замовлення товарів у постачальників.",
		"UA Cash Receipt": "Оплати від покупців та інші надходження в касу і на рахунки.",
		"UA Cash Payment": "Оплати постачальникам та інші витрати з каси і рахунків.",
		"UA Journal Operation": "Ручні бухгалтерські проводки.",
	};

	// catalogs (design/mockups/catalog-items.html): the same table, other columns
	L.CATALOG_COLUMNS = {
		"UA Item": [
			{ key: "title", label: "Найменування", kind: "title", sort: "item_name", sub: "article", sub_label: "Арт.", grow: 1 },
			{ key: "item_type", label: "Вид", kind: "text", field: "item_type", width: 140 },
			{ key: "uom", label: "Од.", kind: "link", field: "uom", width: 110 },
			{ key: "vat_rate", label: "ПДВ", kind: "link", field: "vat_rate", width: 110 },
		],
		"UA Counterparty": [
			{ key: "title", label: "Найменування", kind: "title", sort: "counterparty_name", sub: "edrpou", sub_label: "ЄДРПОУ", grow: 1 },
			{ key: "kind", label: "Вид", kind: "text", field: "kind", width: 150 },
			{ key: "vat_payer", label: "Платник ПДВ", kind: "check", field: "vat_payer", width: 120 },
			{ key: "phone", label: "Телефон", kind: "text", field: "phone", width: 160 },
		],
	};

	L.is_doc_list = (lv) => !!(lv && lv.ua && lv.view_name === "List");
	L.is_document = (doctype) => !!L.COLUMNS[doctype];

	// columns of a catalog without its own list: the title, then the fields of the list view
	L.generic_columns = function (doctype) {
		const meta = frappe.get_meta(doctype);
		const tf = (meta && meta.title_field) || "name";
		const cols = [{ key: "title", label: "Найменування", kind: "title", sort: tf, grow: 1 }];
		((meta && meta.fields) || [])
			.filter((df) => df.in_list_view && df.fieldname !== tf && df.fieldname !== "is_group" && !df.hidden)
			.slice(0, 4)
			.forEach((df) => {
				const kind =
					df.fieldtype === "Link"
						? "link"
						: df.fieldtype === "Check"
						? "check"
						: ["Currency", "Float"].includes(df.fieldtype)
						? "number"
						: df.fieldtype === "Date"
						? "date"
						: "text";
				cols.push({ key: df.fieldname, label: df.label, kind, field: df.fieldname, width: kind === "check" ? 110 : 170, align: kind === "number" ? "r" : "" });
			});
		return cols;
	};

	L.spec = function (doctype) {
		return L.COLUMNS[doctype] || L.CATALOG_COLUMNS[doctype] || L.generic_columns(doctype);
	};

	L.columns = function (lv) {
		const cols = L.spec(lv.doctype);
		return cols.filter((c) => !c.field || frappe.meta.has_field(lv.doctype, c.field));
	};

	L.title_of = function (lv, doc, field) {
		const tf = lv.link_field_title_fields && lv.link_field_title_fields[field];
		return (tf && doc[`${field}_${tf}`]) || doc[field] || "";
	};

	L.BADGE = {
		0: ["ua-badge--unposted", "Не проведено"],
		1: ["ua-badge--posted", "Проведено"],
		2: ["ua-badge--cancelled", "Скасовано"],
	};

	L.badge = function (docstatus) {
		const b = L.BADGE[docstatus] || L.BADGE[0];
		return `<span class="ua-badge ${b[0]}">${esc(__(b[1]))}</span>`;
	};

	L.cell = function (lv, col, doc) {
		const v = col.field ? doc[col.field] : doc[col.key];
		switch (col.kind) {
			case "date":
				return `<span class="ua-num">${esc(v ? frappe.datetime.str_to_user(v) : "")}</span>`;
			case "docno":
				return `<a class="ua-docno" href="${esc(lv.get_form_link(doc))}" data-name="${esc(doc.name)}">${esc(doc.name)}</a>`;
			case "title": {
				const tf = frappe.get_meta(lv.doctype).title_field || "name";
				const sub = col.sub && doc[col.sub] ? `${__(col.sub_label || "")} ${doc[col.sub]}`.trim() : "";
				return (
					`<a class="ua-docno ua-title-cell${doc.is_group ? " is-group" : ""}" href="${esc(lv.get_form_link(doc))}">` +
					`${doc.is_group ? icon("folder", "ua-i-sm") : ""}<span>${esc(doc[tf] || doc.name)}</span></a>` +
					(sub ? `<span class="ua-cell-sub">${esc(sub)}</span>` : "")
				);
			}
			case "check":
				return v ? `<span class="ua-badge ua-badge--plain">${esc(__("Так"))}</span>` : "";
			case "number":
				return `<span class="ua-num">${v ? esc(format_number(v, null, 2)) : ""}</span>`;
			case "link2": {
				const main = L.title_of(lv, doc, col.field);
				const sub = col.sub ? L.title_of(lv, doc, col.sub) : "";
				return `<span class="ua-cell-main">${esc(main)}</span>${sub ? `<span class="ua-cell-sub">${esc(sub)}</span>` : ""}`;
			}
			case "link": {
				const t = L.title_of(lv, doc, col.field) || (col.alt ? L.title_of(lv, doc, col.alt) : "");
				// a link to a DocType shows its Ukrainian name («Каси», not "UA Cash Desk")
				const df = frappe.meta.get_docfield(lv.doctype, col.field);
				return esc(df && df.options === "DocType" ? __(t) : t);
			}
			case "money":
				return `<span class="ua-num ua-cell-main">${v ? esc(format_number(v, null, 2)) : ""}</span>`;
			case "owner": {
				// frappe.user.full_name says "Ви" for the current user: the list shows the real name
				const info = frappe.user_info(doc.owner) || {};
				const name = info.fullname || doc.owner;
				return `<span class="ua-who"><span class="ua-avatar ua-avatar--sm">${esc(
					ua_accounting.shell.initials(name)
				)}</span><span class="ua-who-name" title="${esc(name)}">${esc(name)}</span></span>`;
			}
			case "status":
				return L.badge(doc.docstatus);
			default:
				return esc(v || "");
		}
	};

	L.col_style = function (col) {
		if (col.grow) return "flex:1 1 0;min-width:180px";
		return `flex:0 0 ${col.width || 120}px`;
	};

	L.header_html = function (lv) {
		const cols = L.columns(lv);
		const sort_by = lv.sort_by;
		const order = lv.sort_order;
		const cells = cols
			.map((c) => {
				const sorted = c.sort && c.sort === sort_by;
				const label = c.kind === "money" ? `${__(c.label)}, ₴` : __(c.label);
				const arrow = sorted ? icon(order === "asc" ? "arrow-up" : "arrow-down") : "";
				return (
					`<div class="ua-th${c.align === "r" ? " ua-r" : ""}${c.sort ? " is-sortable" : ""}" style="${L.col_style(c)}"` +
					(c.sort
						? ` data-ua-sort="${c.sort}" role="button" tabindex="0" aria-sort="${
								sorted ? (order === "asc" ? "ascending" : "descending") : "none"
						  }"`
						: "") +
					`><span class="ua-th-in">${esc(label)}${arrow}</span></div>`
				);
			})
			.join("");
		// the structure keeps Frappe's select-all checkboxes (.list-header-subject / .checkbox-actions)
		return `
		<div class="list-row-container ua-lhead">
			<header class="level list-row-head">
				<div class="level-left list-header-subject">
					<label class="ua-check ua-w-check"><input class="list-header-checkbox list-check-all" type="checkbox" aria-label="${esc(
						__("Обрати всі")
					)}"><span class="ua-check-box"><svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span></label>
					${cells}
				</div>
				<div class="level-left checkbox-actions"><input class="list-header-checkbox list-check-all" type="checkbox" tabindex="-1" aria-hidden="true"></div>
				<div class="level-right"><span class="list-count"></span></div>
			</header>
		</div>`;
	};

	L.row_html = function (lv, doc, opts) {
		const cols = L.columns(lv);
		const posted =
			L.is_document(lv.doctype) && doc.docstatus === 1 && ua_accounting.docs && ua_accounting.docs.POSTING.includes(lv.doctype);
		const cells = cols
			.map(
				(c) =>
					`<div class="ua-td${c.align === "r" ? " ua-r" : ""} ua-td-${c.kind}" style="${L.col_style(c)}">${L.cell(
						lv,
						c,
						doc
					)}</div>`
			)
			.join("");
		const actions =
			`<div class="ua-td-act"><div class="ua-row-actions">` +
			(posted
				? `<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-ua-row="dtkt" aria-label="${esc(
						__("Дт/Кт")
				  )}" data-ua-tip="${esc(__("Дт/Кт"))}">${icon("dtkt")}</button>`
				: "") +
			`<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-ua-row="menu" aria-haspopup="menu" aria-label="${esc(
				__("Ще дії")
			)}">${icon("more")}</button></div></div>`;
		const virtual_attr = opts && opts.virtual ? ' data-virtual-row="1"' : "";
		return `
		<div class="list-row-container ua-lrow${doc.docstatus === 2 ? " is-cancelled" : ""}${doc.marked_for_deletion ? " is-marked" : ""}" tabindex="1"${virtual_attr}>
			<div class="level list-row">
				<div class="level-left">
					<label class="ua-check ua-w-check"><input class="list-row-checkbox" type="checkbox" data-doctype="${esc(
						lv.doctype
					)}" data-name="${esc(encodeURIComponent(doc.name))}" aria-label="${esc(
			__("Обрати {0}", [doc.name])
		)}"><span class="ua-check-box"><svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span></label>
					<span class="list-subject ua-hidden-link"><a href="${esc(lv.get_form_link(doc))}" tabindex="-1" aria-hidden="true"></a></span>
					${cells}${actions}
				</div>
			</div>
		</div>`;
	};

	// ---------------------------------------------------------------- ListView hooks (only our document lists)

	(function patch() {
		const LV = frappe.views && frappe.views.ListView;
		if (!LV || LV.prototype.ua_patched) return;
		LV.prototype.ua_patched = true;
		const P = LV.prototype;
		const wrap = (name, fn) => {
			const original = P[name];
			P[name] = function () {
				if (!L.is_doc_list(this)) return original.apply(this, arguments);
				return fn.call(this, original, ...arguments);
			};
		};
		wrap("get_header_html", function () {
			if (!this.columns) return;
			return L.header_html(this);
		});
		wrap("get_list_row_html", function (original, doc, opts) {
			return L.row_html(this, doc, opts);
		});
		// our columns have fixed widths: no Frappe width sync
		wrap("apply_column_widths", function () {});
		wrap("setup_column_resize", function () {});
		wrap("render_count", function () {
			L.update_counts(this);
		});
		wrap("get_no_result_message", function () {
			return "";
		});
		// skeleton rows instead of Frappe's blocks
		wrap("show_skeleton", function () {
			L.show_state(this, "loading");
		});
		wrap("hide_skeleton", function () {
			this.parent.page.container.find(".list-skeleton").hide();
			this.parent.page.container.find(".layout-main").show();
		});
		wrap("toggle_result_area", function (original) {
			const r = original.apply(this, Array.prototype.slice.call(arguments, 1));
			L.show_state(this, this.data.length ? "data" : "empty");
			return r;
		});
		wrap("refresh", function (original) {
			const args = Array.prototype.slice.call(arguments, 1);
			if (!this.data || !this.data.length) L.show_state(this, "loading");
			this.$result && this.$result.closest(".frappe-list").addClass("is-busy");
			return original
				.apply(this, args)
				.then((r) => {
					this.$result && this.$result.closest(".frappe-list").removeClass("is-busy");
					// Frappe shows its skeleton again on some paths with no rows: end the loading state here
					L.show_state(this, this.data && this.data.length ? "data" : "empty");
					// the count can come before the rows: write "Показано X–Y з N" again with the rows
					L.update_counts(this);
					L.after_refresh(this);
					return r;
				})
				.catch((e) => {
					this.$result && this.$result.closest(".frappe-list").removeClass("is-busy");
					L.show_state(this, "error");
					console.warn("ua_list", e);
				});
		});
		// the bulk bar replaces Frappe's "Дії" menu: "Створити" stays in the head
		wrap("toggle_actions_menu_button", function () {
			this.page.hide_actions_menu && this.page.hide_actions_menu();
			this.page.btn_primary && this.page.btn_primary.toggle(!!this.can_create);
		});
		wrap("on_row_checked", function (original) {
			const r = original.apply(this, Array.prototype.slice.call(arguments, 1));
			L.update_bulk(this);
			return r;
		});
	})();

	// The list button is "Створити" for UA doctypes (Frappe says "Додати ...").
	(function () {
		if (!frappe.views || !frappe.views.ListView) return;
		const original = frappe.views.ListView.prototype.set_primary_action;
		frappe.views.ListView.prototype.set_primary_action = function () {
			const result = original.apply(this, arguments);
			if (ua_accounting.ui.is_ua_doctype(this.doctype) && this.can_create && !frappe.boot.read_only) {
				this.page.set_primary_action(__("Створити"), () => this.make_new_doc(), "plus");
				const $btn = this.page.btn_primary;
				if ($btn && !$btn.find(".ua-kbd").length) $btn.append('<span class="ua-kbd">Ins</span>');
			}
			return result;
		};
	})();

	// ---------------------------------------------------------------- page parts

	L.build = function (lv) {
		const $page = lv.$page;
		if ($page.find(".ua-list-top").length) return;
		$page.addClass("ua-doc-list");
		const $main = $page.find(".layout-main-section").first();

		// page head: title + count + text (Frappe's own title sits in the hidden breadcrumbs)
		const $title = $page.find(".page-head .page-title");
		$title.find(".ua-ph-block").remove();
		$title.prepend(
			`<div class="ua-ph-block"><h1 class="ua-ph-title">${esc(__(lv.doctype))} <span class="ua-tag ua-num ua-total"></span></h1>` +
				(L.TEXT[lv.doctype] ? `<p class="ua-ph-sub">${esc(__(L.TEXT[lv.doctype]))}</p>` : "") +
				"</div>"
		);

		const is_doc = L.is_document(lv.doctype);
		const $top = $(`
		<div class="ua-list-top${is_doc ? "" : " ua-list-top--catalog"}">
			<div class="ua-views-row"${is_doc ? "" : " hidden"}>
				<div class="ua-tabs ua-views" role="tablist">
					<button class="ua-tab" role="tab" data-view="all">${esc(__("Усі"))} <span class="ua-count"></span></button>
					<button class="ua-tab" role="tab" data-view="unposted">${esc(__("Не проведені"))} <span class="ua-count"></span></button>
					<button class="ua-tab" role="tab" data-view="mine">${esc(__("Мої"))} <span class="ua-count"></span></button>
				</div>
			</div>
			<div class="ua-filters">
				<label class="ua-input ua-search">${icon("search")}<input class="ua-q" placeholder="${esc(
					is_doc ? __("Номер документа") : __("Назва або код")
				)}" aria-label="${esc(__("Пошук"))}"><span class="ua-kbd">/</span></label>
				${
					ua_accounting.ui.TREE_DOCTYPES[lv.doctype]
						? `<div class="ua-seg" role="tablist" aria-label="${esc(__("Вигляд"))}"><button role="tab" data-mode="tree">${icon(
								"tree",
								"ua-i-sm"
						  )} ${esc(__("Ієрархічно"))}</button><button role="tab" data-mode="flat">${icon("list", "ua-i-sm")} ${esc(
								__("Списком")
						  )}</button></div><span class="ua-toolbar-sep"></span>`
						: ""
				}
				<div class="ua-chips"></div>
			</div>
		</div>`);
		$main.prepend($top);
		if (!is_doc) {
			const tf = frappe.get_meta(lv.doctype).title_field;
			$title.find(".ua-ph-sub").remove();
			$title.find(".ua-ph-block").append('<p class="ua-ph-sub ua-cat-sub"></p>');
			$title.find(".ua-total").remove();
			L.title_field_search = tf;
			if (ua_accounting.ui.TREE_DOCTYPES[lv.doctype] && lv.can_create) {
				const $actions = $page.find(".page-head .standard-actions");
				$actions.find(".ua-new-group").remove();
				$(
					`<button type="button" class="ua-btn ua-btn--secondary ua-new-group">${icon("folder-plus")}${esc(__("Створити групу"))}</button>`
				)
					.insertBefore($actions.find(".primary-action"))
					.on("click", () => L.new_group(lv, ua_accounting.ui.TREE_DOCTYPES[lv.doctype]));
			}
			$top.on("click", ".ua-seg [data-mode]", function () {
				L.set_mode(lv, $(this).attr("data-mode"));
			});
		}

		// the card around the table; the footer carries the paging and the bulk bar
		const $list = $page.find(".frappe-list").first().addClass("ua-card ua-list-card");
		const $paging = $list.find(".list-paging-area").addClass("ua-foot");
		$paging.prepend(
			`<span class="ua-foot-info"></span>` +
				`<div class="ua-bulk" role="toolbar" aria-label="${esc(__("Дії з обраними"))}">` +
				`<span class="ua-bulk-count"></span>` +
				`<button class="ua-btn ua-btn--sm" data-bulk="submit">${icon("checks")}${esc(__("Провести"))}</button>` +
				`<button class="ua-btn ua-btn--sm" data-bulk="cancel">${icon("undo")}${esc(__("Скасувати проведення"))}</button>` +
				`<button class="ua-btn ua-btn--sm" data-bulk="print">${icon("printer")}${esc(__("Друк"))}</button>` +
				`<button class="ua-btn ua-btn--sm" data-bulk="delete">${icon("trash")}${esc(__("Позначити на вилучення"))}</button>` +
				`<span class="ua-sep"></span>` +
				`<button class="ua-btn ua-btn--sm ua-btn--icon" data-bulk="clear" aria-label="${esc(__("Зняти виділення"))}">${icon(
					"x"
				)}</button></div>`
		);
		$list.append('<div class="ua-state" hidden></div>');
		// a click on the checkbox label must not open the form (Frappe opens it on a row click)
		lv.$result.on("click", ".ua-check, .ua-row-actions", (e) => e.stopPropagation());

		// events
		$top.on("click", ".ua-tab", function () {
			L.set_view(lv, $(this).attr("data-view"));
		});
		let timer = null;
		$top.on("input", ".ua-q", function () {
			clearTimeout(timer);
			const q = this.value.trim();
			// documents: the number; catalogs: the title
			const field = is_doc ? "name" : frappe.get_meta(lv.doctype).title_field || "name";
			timer = setTimeout(() => L.set_filter(lv, field, q ? [lv.doctype, field, "like", `%${q}%`] : null), 350);
		});
		$top.on("click", "[data-chip]", function (e) {
			if (e.target.closest(".ua-chip-x")) return;
			L.chip_menu(lv, this, $(this).attr("data-chip"));
		});
		$top.on("click", ".ua-chip-x", function (e) {
			e.stopPropagation();
			const field = $(this).closest("[data-field]").attr("data-field");
			L.set_filter(lv, field, null);
		});
		$top.on("click", "[data-act='reset']", () => {
			$top.find(".ua-q").val("");
			lv.filter_area.clear();
		});
		$top.on("click", "[data-act='more-filter']", () => {
			const $btn = $page.find(".filter-selector .filter-button, .filter-selector button").first();
			$btn.trigger("click");
		});
		$list.on("click", "[data-ua-sort]", function () {
			const f = $(this).attr("data-ua-sort");
			const order = lv.sort_by === f && lv.sort_order === "desc" ? "asc" : "desc";
			L.sort(lv, f, order);
		});
		$list.on("click", "[data-ua-row]", function (e) {
			e.stopPropagation();
			const $c = $(this).closest(".list-row-container");
			const name = decodeURIComponent($c.find(".list-row-checkbox").attr("data-name") || "");
			const act = $(this).attr("data-ua-row");
			if (act === "dtkt") L.open_dtkt(lv.doctype, name);
			else L.row_menu(lv, this, name);
		});
		$paging.on("click", "[data-bulk]", function () {
			L.bulk(lv, $(this).attr("data-bulk"));
		});
		$list.on("click", "[data-state-act]", function () {
			const act = $(this).attr("data-state-act");
			if (act === "retry") lv.refresh();
			if (act === "create") lv.make_new_doc();
			if (act === "period") L.chip_menu(lv, $top.find("[data-chip='period']")[0], "period");
			if (act === "reset") {
				$top.find(".ua-q").val("");
				lv.filter_area.clear();
			}
			if (act === "group") L.new_group(lv, ua_accounting.ui.TREE_DOCTYPES[lv.doctype]);
		});

		// keys: "/" search, Ins create
		$(document)
			.off("keydown.ua_list")
			.on("keydown.ua_list", (e) => {
				const cur = frappe.get_route();
				if (!cur || cur[0] !== "List" || !cur[1]) return;
				const in_input = $(document.activeElement).is("input, textarea, select, [contenteditable=true]");
				if (in_input || $(".modal.show").length || document.querySelector(".ua-dialog-backdrop")) return;
				const view = frappe.views.list_view[cur[1]];
				if (!view || !view.ua || !view.$page.is(":visible")) return;
				if (e.key === "/") {
					e.preventDefault();
					view.$page.find(".ua-q").focus();
				} else if (e.key === "Insert" && view.can_create) {
					e.preventDefault();
					view.make_new_doc();
				}
			});
	};

	// ---------------------------------------------------------------- filters

	L.filters_of = function (lv, field) {
		return (lv.filter_area ? lv.filter_area.get() : []).filter((f) => f[1] === field);
	};

	// Frappe writes the operator as "Between" after a reload
	L.is_between = (f) => !!f && String(f[2]).toLowerCase() === "between" && Array.isArray(f[3]);

	L.set_filter = async function (lv, field, f) {
		let guard = 6;
		while (guard-- && L.filters_of(lv, field).length) await lv.filter_area.remove(field);
		if (f) await lv.filter_area.add([f]);
	};

	L.sort = function (lv, field, order) {
		lv.sort_by = field;
		lv.sort_order = order;
		if (lv.sort_selector) {
			lv.sort_selector.sort_by = field;
			lv.sort_selector.sort_order = order;
			if (lv.sort_selector.set_value) lv.sort_selector.set_value(field, order);
		}
		lv.refresh(true);
	};

	L.VIEWS = {
		all: [],
		unposted: [["docstatus", "=", 0]],
		mine: [["owner", "=", () => frappe.session.user]],
	};

	L.view_of = function (lv) {
		const fs = lv.filter_area ? lv.filter_area.get() : [];
		if (fs.some((f) => f[1] === "owner" && f[3] === frappe.session.user)) return "mine";
		if (fs.some((f) => f[1] === "docstatus" && String(f[3]) === "0")) return "unposted";
		return "all";
	};

	L.set_view = async function (lv, view) {
		for (const f of ["docstatus", "owner"]) {
			let guard = 4;
			while (guard-- && L.filters_of(lv, f).length) await lv.filter_area.remove(f);
		}
		const add = (L.VIEWS[view] || []).map(([field, op, v]) => [lv.doctype, field, op, typeof v === "function" ? v() : v]);
		if (add.length) await lv.filter_area.add(add);
	};

	const MONTHS = ["січень", "лютий", "березень", "квітень", "травень", "червень", "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"];

	L.period_label = function (from, to) {
		const a = moment(from);
		const b = moment(to);
		if (a.isSame(a.clone().startOf("month"), "day") && b.isSame(a.clone().endOf("month"), "day")) {
			return `${__(MONTHS[a.month()])} ${a.year()}`;
		}
		if (a.isSame(b, "day")) return frappe.datetime.str_to_user(from);
		return `${frappe.datetime.str_to_user(from)} – ${frappe.datetime.str_to_user(to)}`;
	};

	L.render_chips = function (lv) {
		const $chips = lv.$page.find(".ua-chips");
		if (!$chips.length) return;
		const fs = lv.filter_area ? lv.filter_area.get() : [];
		const get = (field) => fs.find((f) => f[1] === field);
		const meta_has = (f) => frappe.meta.has_field(lv.doctype, f);
		const chips = [];
		const on = (field, label, value, menu) =>
			`<span class="ua-chip is-on" data-field="${field}" data-chip="${menu}" role="button" tabindex="0">${esc(label)}: <b>${esc(
				value
			)}</b><button class="ua-chip-x" aria-label="${esc(__("Прибрати фільтр"))}">${icon("x")}</button></span>`;
		const off = (menu, label, ic) =>
			`<button class="ua-chip ua-chip--dashed" data-chip="${menu}" aria-haspopup="menu">${icon(ic || "plus")}${esc(label)}</button>`;

		const pd = get("posting_date");
		if (meta_has("posting_date")) {
			if (pd && L.is_between(pd) && Array.isArray(pd[3])) {
				chips.push(
					`<span class="ua-chip is-on" data-field="posting_date" data-chip="period" role="button" tabindex="0">${icon(
						"calendar"
					)}${esc(__("Період"))}: <b>${esc(L.period_label(pd[3][0], pd[3][1]))}</b><button class="ua-chip-x" aria-label="${esc(
						__("Прибрати фільтр")
					)}">${icon("x")}</button></span>`
				);
			} else if (pd) {
				chips.push(on("posting_date", __("Дата"), frappe.datetime.str_to_user(pd[3]), "period"));
			} else {
				chips.push(off("period", __("Період"), "calendar"));
			}
		}
		[
			["organization", __("Організація"), "UA Organization"],
			["counterparty", __("Контрагент"), "UA Counterparty"],
		].forEach(([field, label]) => {
			if (!meta_has(field)) return;
			const f = get(field);
			if (f && f[2] === "=") {
				const title = L.link_title(lv, field, f[3]);
				chips.push(on(field, label, title, field));
			} else chips.push(off(field, label));
		});
		const is_doc = L.is_document(lv.doctype);
		if (is_doc) {
			const ds = get("docstatus");
			if (ds && ds[2] === "=") chips.push(on("docstatus", __("Статус"), __(L.BADGE[ds[3]] ? L.BADGE[ds[3]][1] : ds[3]), "docstatus"));
			else chips.push(off("docstatus", __("Статус")));
		}
		// catalogs: one chip per short choice field ("Вид")
		L.select_fields(lv).forEach((df) => {
			const f = get(df.fieldname);
			if (f && f[2] === "=") chips.push(on(df.fieldname, __(df.label), __(f[3]), "select:" + df.fieldname));
			else chips.push(off("select:" + df.fieldname, __(df.label)));
		});
		chips.push(`<button class="ua-chip ua-chip--dashed" data-act="more-filter">${icon("filter")}${esc(__("Ще фільтр"))}</button>`);
		const tf = frappe.get_meta(lv.doctype).title_field || "name";
		const parent_field = ua_accounting.ui.TREE_DOCTYPES[lv.doctype];
		const known = ["posting_date", "organization", "counterparty", "docstatus", "owner", "name", tf, parent_field].concat(
			L.select_fields(lv).map((df) => df.fieldname)
		);
		const other = fs.filter((f) => !known.includes(f[1]));
		if (other.length) chips.push(`<span class="ua-chip is-on ua-chip--count">${esc(__("Інші відбори: {0}", [other.length]))}</span>`);
		if (fs.length) chips.push(`<button class="ua-btn ua-btn--ghost ua-btn--sm" data-act="reset">${esc(__("Скинути"))}</button>`);
		$chips.html(chips.join(""));
		const q = get(is_doc ? "name" : tf);
		const $q = lv.$page.find(".ua-q");
		if (!$q.is(":focus")) $q.val(q && q[2] === "like" ? String(q[3]).replace(/^%|%$/g, "") : "");
	};

	// titles of link values in the chips (one call per value, cached)
	L._titles = {};
	L.link_title = function (lv, field, value) {
		const df = frappe.meta.get_docfield(lv.doctype, field);
		const dt = df && df.options;
		const key = `${dt}\n${value}`;
		if (L._titles[key] !== undefined) return L._titles[key];
		const cached = frappe.utils.get_link_title && frappe.utils.get_link_title(dt, value);
		if (cached) return (L._titles[key] = cached);
		L._titles[key] = "…";
		frappe
			.xcall("ua_accounting.reporting.api.link_titles", { items: JSON.stringify([[dt, value]]) })
			.then((t) => {
				L._titles[key] = (t && t[key]) || value;
				L.render_chips(lv);
			})
			.catch(() => (L._titles[key] = value));
		return L._titles[key];
	};

	L.select_fields = function (lv) {
		if (L.is_document(lv.doctype)) return [];
		const meta = frappe.get_meta(lv.doctype);
		return ((meta && meta.fields) || []).filter(
			(df) => df.fieldtype === "Select" && (df.in_list_view || df.in_standard_filter) && !df.hidden && df.options
		);
	};

	L.chip_menu = function (lv, trigger, kind) {
		if (!trigger) return;
		if (kind === "period") return L.period_menu(lv, trigger);
		if (kind.startsWith("select:")) {
			const field = kind.slice(7);
			const df = frappe.meta.get_docfield(lv.doctype, field);
			const opts = String((df && df.options) || "")
				.split("\n")
				.filter(Boolean);
			ua_accounting.ui.menu(
				trigger,
				`<div class="ua-menu-label">${esc(__(df.label))}</div>` +
					opts.map((o) => `<button class="ua-menu-item" data-v="${esc(o)}">${esc(__(o))}</button>`).join(""),
				(item) => {
					const v = item.getAttribute("data-v");
					if (v !== null) L.set_filter(lv, field, [lv.doctype, field, "=", v]);
				}
			);
			return;
		}
		if (kind === "docstatus") {
			const items = [1, 0, 2]
				.map((s) => `<button class="ua-menu-item" data-v="${s}">${L.badge(s)}</button>`)
				.join("");
			ua_accounting.ui.menu(trigger, `<div class="ua-menu-label">${esc(__("Статус"))}</div>${items}`, (item) => {
				const v = item.getAttribute("data-v");
				if (v !== null) L.set_filter(lv, "docstatus", [lv.doctype, "docstatus", "=", +v]);
			});
			return;
		}
		// link value: search as you type
		const df = frappe.meta.get_docfield(lv.doctype, kind);
		if (!df) return;
		const pop = ua_accounting.ui.menu(
			trigger,
			`<div class="ua-pop-search"><label class="ua-input ua-input--sm">${icon("search", "ua-i-sm")}<input placeholder="${esc(
				__("Знайти: {0}", [__(df.label)])
			)}"></label></div><div class="ua-pop-list">${ua_accounting.ui.skeleton_rows(3, [70])}</div>`,
			(item) => {
				const v = item.getAttribute("data-v");
				if (!v) return true;
				L._titles[`${df.options}\n${v}`] = item.getAttribute("data-t");
				L.set_filter(lv, kind, [lv.doctype, kind, "=", v]);
			},
			{ cls: "ua-filter-pop" }
		);
		if (!pop) return;
		const $list = $(pop).find(".ua-pop-list");
		const load = (txt) =>
			frappe
				.xcall("frappe.desk.search.search_link", { doctype: df.options, txt: txt || "", page_length: 8 })
				.then((rows) => {
					rows = rows || [];
					$list.html(
						rows.length
							? rows
									.map((r) => {
										const t = r.label || r.value;
										const d = r.description && r.description !== t ? r.description : "";
										return `<button class="ua-menu-item" data-v="${esc(r.value)}" data-t="${esc(t)}"><span class="ua-two">${esc(
											t
										)}${d ? `<small>${esc(frappe.utils.html2text(d))}</small>` : ""}</span></button>`;
									})
									.join("")
							: `<div class="ua-menu-empty">${esc(__("Нічого не знайдено"))}</div>`
					);
				})
				.catch(() => $list.html(`<div class="ua-menu-empty">${esc(__("Не вдалося завантажити"))}</div>`));
		let t = null;
		$(pop)
			.find("input")
			.on("input", function () {
				clearTimeout(t);
				const v = this.value;
				t = setTimeout(() => load(v), 250);
			});
		load("");
	};

	L.period_menu = function (lv, trigger) {
		const today = moment(frappe.datetime.get_today());
		const r = (a, b) => [a.format("YYYY-MM-DD"), b.format("YYYY-MM-DD")];
		const picks = [
			[__("Сьогодні"), r(today, today)],
			[__("Цей тиждень"), r(today.clone().startOf("isoWeek"), today.clone().endOf("isoWeek"))],
			[__("Цей місяць"), r(today.clone().startOf("month"), today.clone().endOf("month"))],
			[__("Минулий місяць"), r(today.clone().subtract(1, "month").startOf("month"), today.clone().subtract(1, "month").endOf("month"))],
			[__("Цей квартал"), r(today.clone().startOf("quarter"), today.clone().endOf("quarter"))],
			[__("Цей рік"), r(today.clone().startOf("year"), today.clone().endOf("year"))],
		];
		const cur = L.filters_of(lv, "posting_date")[0];
		const cur_v = cur && L.is_between(cur) ? cur[3] : null;
		const pop = ua_accounting.ui.menu(
			trigger,
			`<div class="ua-period-pop"><div class="ua-menu-label">${esc(__("Швидкий вибір"))}</div><div class="ua-grid">` +
				picks
					.map(
						([label, v], i) =>
							`<button class="ua-chip${cur_v && cur_v[0] === v[0] && cur_v[1] === v[1] ? " is-on" : ""}" data-pick="${i}">${esc(
								label
							)}</button>`
					)
					.join("") +
				`</div><div class="ua-range"><label class="ua-input ua-input--sm"><input data-d="from" aria-label="${esc(__("З"))}" placeholder="${esc(
					__("дд.мм.рррр")
				)}" value="${esc(cur_v ? frappe.datetime.str_to_user(cur_v[0]) : "")}"></label><span class="ua-subtle">–</span>` +
				`<label class="ua-input ua-input--sm"><input data-d="to" aria-label="${esc(__("По"))}" placeholder="${esc(
					__("дд.мм.рррр")
				)}" value="${esc(cur_v ? frappe.datetime.str_to_user(cur_v[1]) : "")}"></label></div>` +
				`<div class="ua-period-foot"><button class="ua-btn ua-btn--sm ua-btn--primary" data-act="apply">${esc(
					__("Застосувати")
				)}</button></div></div>`,
			(item) => {
				const i = item.getAttribute("data-pick");
				if (i !== null) {
					const v = picks[+i][1];
					L.set_filter(lv, "posting_date", [lv.doctype, "posting_date", "between", v]);
					return;
				}
				if (item.getAttribute("data-act") === "apply") {
					const from = frappe.datetime.user_to_str($(pop).find("[data-d=from]").val(), false, true);
					const to = frappe.datetime.user_to_str($(pop).find("[data-d=to]").val(), false, true);
					if (!from || !to || from === "Invalid date" || to === "Invalid date") {
						ua_accounting.ui.toast({ type: "error", title: __("Вкажіть дати періоду"), text: __("Формат: дд.мм.рррр") });
						return true;
					}
					L.set_filter(lv, "posting_date", [lv.doctype, "posting_date", "between", [from, to]]);
					return;
				}
				return true;
			},
			{ cls: "ua-period-menu" }
		);
	};

	// ---------------------------------------------------------------- counts, footer, bulk

	L.count = function (doctype, filters) {
		return frappe.db.count(doctype, { filters: filters || [] }).catch(() => null);
	};

	L.update_counts = function (lv) {
		const fs = (lv.filter_area ? lv.filter_area.get() : []).map((f) => f.slice(0, 4));
		const shown = (lv.data || []).length;
		L.count(lv.doctype, fs).then((n) => {
			lv.total_count = n;
			const $info = lv.$page.find(".ua-foot-info");
			if (n === null) {
				$info.html("");
				return;
			}
			$info.html(
				shown
					? `<span>${esc(__("Показано"))} <b class="ua-num">1–${esc(format_number(shown, null, 0))}</b> ${esc(__("з"))} <b class="ua-num">${esc(
							format_number(n, null, 0)
					  )}</b></span>`
					: ""
			);
		});
		if (!L.is_document(lv.doctype)) {
			const has_group = frappe.meta.has_field(lv.doctype, "is_group");
			Promise.all([
				L.count(lv.doctype, has_group ? [[lv.doctype, "is_group", "=", 0]] : []),
				has_group ? L.count(lv.doctype, [[lv.doctype, "is_group", "=", 1]]) : Promise.resolve(0),
			]).then(([items, groups]) => {
				const parts = [];
				if (items !== null) parts.push(__("Позицій: {0}", [format_number(items, null, 0)]));
				if (groups) parts.push(__("груп: {0}", [format_number(groups, null, 0)]));
				lv.$page.find(".ua-cat-sub").text(parts.join(" · "));
			});
			return;
		}
		// tab counts do not depend on the other filters
		const base = [];
		const $tabs = lv.$page.find(".ua-views");
		Promise.all([
			L.count(lv.doctype, base),
			L.count(lv.doctype, [[lv.doctype, "docstatus", "=", 0]]),
			L.count(lv.doctype, [[lv.doctype, "owner", "=", frappe.session.user]]),
		]).then(([all, unposted, mine]) => {
			const fmt = (v) => (v === null ? "" : format_number(v, null, 0));
			$tabs.find("[data-view=all] .ua-count").text(fmt(all));
			$tabs.find("[data-view=unposted] .ua-count").text(fmt(unposted));
			$tabs.find("[data-view=mine] .ua-count").text(fmt(mine));
			lv.$page.find(".page-head .ua-total").text(fmt(all));
			ua_accounting.ui.place_ink($tabs[0]);
		});
	};

	L.after_refresh = function (lv) {
		const view = L.view_of(lv);
		const $tabs = lv.$page.find(".ua-views");
		$tabs.find(".ua-tab").each(function () {
			const on = $(this).attr("data-view") === view;
			$(this).toggleClass("is-on", on).attr("aria-selected", on);
		});
		if ($tabs[0]) ua_accounting.ui.place_ink($tabs[0]);
		L.render_chips(lv);
		L.update_bulk(lv);
		// a group filter restored from the saved settings selects its folder in the tree
		const parent_field = ua_accounting.ui.TREE_DOCTYPES[lv.doctype];
		if (parent_field && lv.ua_mode === "tree") {
			const f = L.filters_of(lv, parent_field)[0];
			const g = f ? f[3] : "";
			if (g !== (ua_accounting.ui.current_group || "")) {
				ua_accounting.ui.current_group = g;
				ua_accounting.ui.render_group_tree(lv, parent_field);
			}
		}
	};

	L.show_state = function (lv, state) {
		const $list = lv.$page && lv.$page.find(".frappe-list").first();
		if (!$list || !$list.length) return;
		const $state = $list.find(".ua-state");
		const $wrap = $list.find(".result-container");
		const $paging = $list.find(".list-paging-area");
		$list.attr("data-state", state);
		if (state === "data") {
			$state.prop("hidden", true).empty();
			$wrap.show();
			return;
		}
		$list.find(".no-result").hide();
		if (state === "loading") {
			$wrap.hide();
			$state.prop("hidden", false).html(ua_accounting.ui.skeleton_rows(10, [10, 12, 30, 14, 12, 6, 14, 10]));
			return;
		}
		$wrap.hide();
		$paging.show();
		const fs = lv.filter_area ? lv.filter_area.get() : [];
		const pd = fs.find((f) => f[1] === "posting_date" && L.is_between(f));
		let html;
		if (state === "error") {
			html = ua_accounting.ui.empty_html({
				error: true,
				title: __("Не вдалося завантажити список"),
				text: __("Перевірте з’єднання з сервером і спробуйте ще раз."),
				actions: [{ label: __("Повторити"), act: "retry", icon: "refresh" }],
			});
		} else if (!L.is_document(lv.doctype)) {
			const tf = frappe.get_meta(lv.doctype).title_field || "name";
			const searching = fs.some((f) => f[1] === tf || f[1] === "name");
			const group = ua_accounting.ui.current_group_title;
			const parent_field = ua_accounting.ui.TREE_DOCTYPES[lv.doctype];
			const actions = [];
			if (searching) actions.push({ label: __("Скинути пошук"), act: "reset", icon: "x" });
			if (lv.can_create) {
				actions.push({ label: __("Створити елемент"), act: "create", icon: "plus", primary: true });
				if (parent_field) actions.push({ label: __("Створити групу"), act: "group", icon: "folder-plus" });
			}
			html = ua_accounting.ui.empty_html({
				art: searching ? "search" : "folder-open",
				title: searching ? __("Нічого не знайдено") : group ? __("У групі «{0}» немає елементів", [group]) : __("Елементів ще немає"),
				text: searching ? __("Спробуйте іншу назву або код.") : __("Створіть перший елемент довідника «{0}».", [__(lv.doctype)]),
				actions,
			});
		} else if (fs.length) {
			const actions = [];
			if (pd) actions.push({ label: __("Змінити період"), act: "period", icon: "calendar" });
			else actions.push({ label: __("Скинути відбори"), act: "reset", icon: "x" });
			if (lv.can_create) actions.push({ label: __("Створити"), act: "create", icon: "plus", primary: true });
			html = ua_accounting.ui.empty_html({
				title: pd
					? __("За {0} документів немає", [L.period_label(pd[3][0], pd[3][1])])
					: __("Нічого не знайдено"),
				text: __("Змініть відбори або створіть новий документ «{0}».", [__(lv.doctype)]),
				actions,
			});
		} else {
			html = ua_accounting.ui.empty_html({
				title: __("Документів ще немає"),
				text: __("Створіть перший документ «{0}».", [__(lv.doctype)]),
				actions: lv.can_create ? [{ label: __("Створити"), act: "create", icon: "plus", primary: true }] : [],
			});
		}
		$state.prop("hidden", false).html(html.replace(/data-act=/g, "data-state-act="));
	};

	L.selected = function (lv) {
		return lv.get_checked_items ? lv.get_checked_items() : [];
	};

	L.update_bulk = function (lv) {
		const $foot = lv.$page.find(".ua-foot");
		const rows = L.selected(lv);
		const n = rows.length;
		$foot.toggleClass("has-sel", n > 0);
		$foot.find(".ua-bulk").toggleClass("is-on", n > 0);
		if (!n) return;
		const amount_col = L.columns(lv).find((c) => c.kind === "money");
		const sum = amount_col ? rows.reduce((s, r) => s + (flt(r[amount_col.field]) || 0), 0) : 0;
		$foot
			.find(".ua-bulk-count")
			.html(
				`${esc(__("Обрано"))} ${n}${sum ? ` <span>· ${esc(ua_accounting.ui.money(sum, { cur: true }))}</span>` : ""}`
			);
		const has = (s) => L.is_document(lv.doctype) && rows.some((r) => r.docstatus === s);
		$foot.find("[data-bulk=submit]").prop("hidden", !has(0));
		$foot.find("[data-bulk=cancel]").prop("hidden", !has(1));
		$foot.find("[data-bulk=delete]").prop(
			"hidden",
			!frappe.meta.has_field(lv.doctype, "marked_for_deletion") || !rows.some((r) => r.docstatus !== 1)
		);
	};

	L.bulk = function (lv, act) {
		const rows = L.selected(lv);
		const names = rows.map((r) => r.name);
		if (act === "clear") {
			lv.clear_checked_items();
			L.update_bulk(lv);
			return;
		}
		if (!names.length) return;
		const done = (title) => {
			lv.clear_checked_items();
			lv.refresh();
			ua_accounting.ui.toast({ title, text: __("Документів: {0}", [names.length]) });
		};
		if (act === "print") {
			L.print_dialog(lv, names);
			return;
		}
		if (act === "submit" || act === "cancel") {
			const list = rows.filter((r) => r.docstatus === (act === "submit" ? 0 : 1)).map((r) => r.name);
			const q = act === "submit" ? __("Провести документи: {0}?", [list.length]) : __("Скасувати проведення документів: {0}?", [list.length]);
			frappe.confirm(q, () =>
				frappe
					.xcall("frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs", {
						doctype: lv.doctype,
						action: act,
						docnames: list,
					})
					.then((res) => L.bulk_result(lv, act, list.length, res))
			);
			return;
		}
		if (act === "delete") {
			const list = rows.filter((r) => r.docstatus !== 1).map((r) => r.name);
			const q = L.is_document(lv.doctype)
				? __("Позначити на вилучення документи: {0}?", [list.length])
				: __("Позначити на вилучення елементи: {0}?", [list.length]);
			// 1C style: only a mark, nothing is deleted
			frappe.confirm(q, () => L.set_mark(lv, list, 1).then(() => done(__("Позначено на вилучення"))));
		}
	};

	// batch print: pick the print form, then one PDF of all selected documents
	L.print_dialog = function (lv, names) {
		frappe
			.xcall("frappe.client.get_list", {
				doctype: "Print Format",
				filters: { doc_type: lv.doctype, disabled: 0 },
				fields: ["name"],
				order_by: "name asc",
				limit_page_length: 100,
			})
			.then((rows) => {
				const formats = rows.map((r) => r.name);
				const options = formats.length ? formats : ["Standard"];
				const preferred = frappe.get_meta(lv.doctype).default_print_format;
				const dialog = new frappe.ui.Dialog({
					title: __("Друк документів"),
					fields: [
						{
							fieldtype: "Select",
							fieldname: "print_format",
							label: __("Форма друку"),
							options: options.join("\n"),
							default: options.includes(preferred) ? preferred : options[0],
							reqd: 1,
						},
						{
							fieldtype: "HTML",
							fieldname: "info",
							options: `<p class="text-muted">${esc(__("Документів: {0}. Буде створено один файл PDF.", [names.length]))}</p>`,
						},
					],
					primary_action_label: __("Друк PDF"),
					primary_action: (values) => {
						const url =
							"/api/method/frappe.utils.print_format.download_multi_pdf?" +
							$.param({
								doctype: lv.doctype,
								name: JSON.stringify(names),
								format: values.print_format,
								no_letterhead: 1,
							});
						window.open(url);
						dialog.hide();
					},
				});
				dialog.show();
			});
	};

	L.set_mark = (lv, names, mark) =>
		frappe.xcall("ua_accounting.desk.mark_for_deletion", { doctype: lv.doctype, names: JSON.stringify(names), mark });

	// real result of a bulk post / cancel: Frappe returns the failed documents, or queues a job above 20
	L.bulk_result = function (lv, act, total, res) {
		lv.clear_checked_items();
		lv.refresh();
		const toast = ua_accounting.ui.toast;
		const failed = Array.isArray(res) ? res : [];
		const verb = act === "submit" ? __("Проведено") : __("Проведення скасовано");
		// the sync path always returns a list (empty when all passed); no list means a queued job
		if (!Array.isArray(res)) {
			toast({ title: __("Поставлено в чергу"), text: __("Документів: {0}", [total]), type: "info" });
		} else if (!failed.length) {
			toast({ title: verb, text: __("{0} з {1}", [total, total]) });
		} else {
			const errors = failed
				.slice(0, 5)
				.map((f) => (typeof f === "string" ? f : `${f.doc || f.name || ""} ${f.message || f.error || ""}`.trim()))
				.map((s) => frappe.utils.html2text(s))
				.join("; ");
			toast({
				title: `${verb}: ${total - failed.length} ${__("з")} ${total}`,
				text: `${__("Помилки")}: ${errors}`,
				type: "error",
				duration: 9000,
			});
		}
	};

	L.row_menu = function (lv, trigger, name) {
		const doc = (lv.data || []).find((d) => d.name === name);
		const posted = doc && doc.docstatus === 1 && ua_accounting.docs.POSTING.includes(lv.doctype);
		// real delete: managers only, never a posted document
		const can_delete =
			doc && doc.docstatus !== 1 && frappe.model.can_delete(lv.doctype) && frappe.user.has_role("UA Accounting Manager");
		ua_accounting.ui.menu(
			trigger,
			`<button class="ua-menu-item" data-a="open">${icon("external")}${esc(__("Відкрити"))}<span class="ua-kbd">Enter</span></button>` +
				(posted ? `<button class="ua-menu-item" data-a="dtkt">${icon("dtkt")}${esc(__("Дт/Кт"))}</button>` : "") +
				(lv.can_create ? `<button class="ua-menu-item" data-a="copy">${icon("copy")}${esc(__("Скопіювати"))}</button>` : "") +
				(doc && doc.marked_for_deletion
					? `<button class="ua-menu-item" data-a="unmark">${icon("undo")}${esc(__("Зняти позначку вилучення"))}</button>`
					: "") +
				(can_delete ? `<button class="ua-menu-item" data-a="delete">${icon("trash")}${esc(__("Видалити"))}</button>` : ""),
			(item) => {
				const a = item.getAttribute("data-a");
				if (a === "unmark") L.set_mark(lv, [name], 0).then(() => lv.refresh());
				if (a === "delete") {
					frappe.confirm(__("Видалити назавжди {0}? Цю дію не можна скасувати.", [esc(name)]), () =>
						frappe
							.xcall("frappe.client.delete", { doctype: lv.doctype, name })
							.then(() => {
								ua_accounting.ui.toast({ title: __("Видалено"), text: name });
								lv.refresh();
							})
					);
				}
				if (a === "open") frappe.set_route("Form", lv.doctype, name);
				if (a === "dtkt") L.open_dtkt(lv.doctype, name);
				if (a === "copy") {
					frappe.model.with_doc(lv.doctype, name).then((d) => {
						const copy = frappe.model.copy_doc(d);
						frappe.set_route("Form", copy.doctype, copy.name);
					});
				}
			},
			{ align: "right" }
		);
	};

	L.open_dtkt = function (doctype, name) {
		frappe.model.with_doc(doctype, name).then((doc) => ua_accounting.docs.show_entries({ doctype, doc }));
	};

	// ---------------------------------------------------------------- catalogs: tree or flat list

	L.set_mode = function (lv, mode, first) {
		const parent_field = ua_accounting.ui.TREE_DOCTYPES[lv.doctype];
		if (!parent_field) return;
		lv.ua_mode = mode;
		lv.$page.find(".ua-seg [data-mode]").each(function () {
			const on = $(this).attr("data-mode") === mode;
			$(this).toggleClass("is-on", on).attr("aria-selected", on);
		});
		lv.$page.toggleClass("ua-cat-tree", mode === "tree");
		if (mode === "tree") {
			ua_accounting.ui.render_group_tree(lv, parent_field);
		} else {
			lv.$page.find(".ua-tree-card").remove();
			lv.$page.find(".ua-fpath").remove();
			if (!first && L.filters_of(lv, parent_field).length) {
				ua_accounting.ui.current_group = "";
				ua_accounting.ui.current_group_title = "";
				L.set_filter(lv, parent_field, null);
			}
		}
	};

	// ---------------------------------------------------------------- settings of every UA list

	L.new_group = function (listview, parent_field) {
		const options = { is_group: 1 };
		if (ua_accounting.ui.current_group) options[parent_field] = ua_accounting.ui.current_group;
		frappe.new_doc(listview.doctype, options);
	};

	L.setup = function (listview) {
		const doctype = listview.doctype;
		const parent_field = ua_accounting.ui.TREE_DOCTYPES[doctype];
		ua_accounting.ui.current_group = "";
		const kind = ua_accounting.ui.kind(doctype);
		if (document.body.classList.contains("ua-shell") && (L.is_document(doctype) || kind === "catalog")) {
			listview.ua = true;
			L.build(listview);
			if (!listview.ua_sorted && (listview.sort_by === "modified" || listview.sort_by === "creation")) {
				listview.ua_sorted = true;
				// documents: newest first; catalogs: by title
				if (L.is_document(doctype)) L.sort(listview, "posting_date", "desc");
				else L.sort(listview, frappe.get_meta(doctype).title_field || "name", "asc");
			}
			if (parent_field) L.set_mode(listview, listview.ua_mode || "tree", true);
			return;
		}
		if (parent_field) {
			ua_accounting.ui.render_group_tree(listview, parent_field);
			if (listview.can_create) {
				listview.page.add_inner_button(__("Створити групу"), () => L.new_group(listview, parent_field));
			}
		}
		// catalogs with a title: the ID is internal, so no ID column and no ID filter
		listview.$page.toggleClass("ua-hide-id", L.has_title(doctype));
		// search on the right: the standard filter of the title field (else the first one)
		setTimeout(() => {
			const title_field = frappe.get_meta(doctype).title_field;
			const $inputs = listview.$page.find(".standard-filter-section input.input-with-feedback");
			const $title = title_field ? $inputs.filter(`[data-fieldname="${title_field}"]`) : $();
			($title.length ? $title : $inputs.first()).attr("placeholder", __("Пошук (Ctrl+F)"));
		}, 300);
	};

	// A catalog with a title field shows the title, not the internal ID (hash, or a code like "VatRate").
	L.has_title = function (doctype) {
		const meta = frappe.get_meta(doctype);
		if (doctype === "UA Account Turnover") return true; // the name is a hash and the row has no title
		return !!(meta && meta.title_field && meta.title_field !== "name");
	};

	// docstatus -> posted / not posted (Frappe's own indicator in other views)
	L.get_indicator = function (doc) {
		if (doc.docstatus === 1) return [__("Проведено"), "green", "docstatus,=,1"];
		if (doc.docstatus === 2) return [__("Скасовано"), "red", "docstatus,=,2"];
		return [__("Не проведено"), "gray", "docstatus,=,0"];
	};

	L.register = function () {
		const doctypes = new Set(Object.keys(ua_accounting.ui.TREE_DOCTYPES));
		ua_accounting.shell.SECTIONS.forEach((s) =>
			(s.groups || []).forEach((g) =>
				g.items.forEach((c) => c.doctype && ua_accounting.ui.is_ua_doctype(c.doctype) && doctypes.add(c.doctype))
			)
		);
		Object.keys(L.COLUMNS).forEach((d) => doctypes.add(d));
		doctypes.forEach((doctype) => {
			const settings = { onload: L.setup };
			// read when the columns are built, after the meta is loaded
			Object.defineProperty(settings, "hide_name_column", {
				enumerable: true,
				configurable: true,
				get: () => L.has_title(doctype),
			});
			if (ua_accounting.ui.DOCUMENTS.includes(doctype)) {
				settings.get_indicator = L.get_indicator;
				// without these flags Frappe shows its own Draft / Cancelled before our indicator
				settings.has_indicator_for_draft = true;
				settings.has_indicator_for_cancelled = true;
				// fields of our columns (link titles come with them); read after the meta is loaded
				const wanted = ["posting_date", "counterparty", "contract", "warehouse", "cash_desk", "bank_account"].concat(
					["total_amount", "amount", "currency", "content"]
				);
				Object.defineProperty(settings, "add_fields", {
					enumerable: true,
					configurable: true,
					get: () => wanted.filter((f) => frappe.meta.has_field(doctype, f)).concat(["owner", "docstatus", "marked_for_deletion"]),
				});
			}
			if (!ua_accounting.ui.DOCUMENTS.includes(doctype)) {
				Object.defineProperty(settings, "add_fields", {
					enumerable: true,
					configurable: true,
					get: () => {
						const meta = frappe.get_meta(doctype);
						const want = ["is_group", "marked_for_deletion"];
						if (meta && meta.title_field) want.push(meta.title_field);
						L.spec(doctype).forEach((c) => {
							if (c.field) want.push(c.field);
							if (c.sub) want.push(c.sub);
						});
						return want.filter((f) => frappe.meta.has_field(doctype, f));
					},
				});
			}
			const target = frappe.listview_settings[doctype] || (frappe.listview_settings[doctype] = {});
			Object.defineProperties(target, Object.getOwnPropertyDescriptors(settings));
		});
	};

	L.register();
})();
