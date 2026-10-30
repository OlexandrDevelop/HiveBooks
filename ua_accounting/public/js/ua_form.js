// Forms of UA doctypes (design/mockups/form-document.html). Frappe's Form stays the engine;
// we draw the head (title, status, "Є незаписані зміни", star), the 1C toolbar, the cards
// ("Основне" + side card "Взаєморозрахунки" / "Пов’язані документи"), the table part card with
// tabs and a toolbar, the sticky totals footer, the unsaved-changes dialog and the toasts.
// Frappe's own buttons stay (hidden) and keep their logic in ua_form_toolbar.js.
frappe.provide("ua_accounting.form");

(function () {
	const F = ua_accounting.form;
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const icon = (n, c) => ua_accounting.ui.icon(n, c);
	const money = (v) => ua_accounting.ui.money(v, { cur: true });

	F.kind = (frm) => (document.body.classList.contains("ua-shell") ? ua_accounting.ui.kind(frm.doctype) : null);

	F.perm = (frm) => (frm.perm && frm.perm[0]) || {};

	F.posting = (frm) => ua_accounting.docs && ua_accounting.docs.POSTING.includes(frm.doctype);

	// ---------------------------------------------------------------- head and toolbar

	F.title_text = function (frm) {
		const meta = frappe.get_meta(frm.doctype);
		if (meta.issingle) return ""; // the name of a single is its title: do not repeat it
		if (frm.is_new()) return __("номер буде присвоєно");
		if (meta.is_submittable) {
			const date = frm.doc.posting_date ? ` ${__("від")} ${frappe.datetime.str_to_user(frm.doc.posting_date)}` : "";
			return `${frm.doc.name}${date}`;
		}
		return ua_accounting.shell.doc_title(frm);
	};

	F.status = function (frm) {
		if (frm.is_new()) return ["ua-badge--draft", __("Чернетка")];
		if (frappe.get_meta(frm.doctype).is_submittable) {
			const b = ua_accounting.list.BADGE[frm.doc.docstatus] || ua_accounting.list.BADGE[0];
			return [b[0], __(b[1])];
		}
		return null;
	};

	F.fav_entry = function (frm) {
		const route = ["Form", frm.doctype, frm.doc.name];
		return { key: "route:" + route.join("/"), route, label: `${__(frm.doctype)} ${ua_accounting.shell.doc_title(frm)}` };
	};

	F.render_head = function (frm) {
		const $title = $(frm.page.wrapper).find(".page-head .page-title").first();
		let $block = $title.find(".ua-ph-block");
		if (!$block.length) {
			$block = $(
				`<div class="ua-ph-block ua-doc-head">
					<div class="ua-doc-title-row">
						<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-ua-cmd="back" aria-label="${esc(
							__("До списку")
						)}" data-ua-tip="${esc(__("До списку · Esc"))}">${icon("chev-l")}</button>
						<h1 class="ua-doc-title"><span class="ua-doc-type"></span> <span class="ua-no"></span></h1>
						<span class="ua-badge ua-badge--lg ua-doc-status" role="status"></span>
						<span class="ua-dirty">${esc(__("Є незаписані зміни"))}</span>
						<div class="ua-right">
							<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-ua-cmd="prev" aria-label="${esc(
								__("Попередній документ")
							)}" data-ua-tip="${esc(__("Попередній"))}">${icon("chev-u")}</button>
							<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon" data-ua-cmd="next" aria-label="${esc(
								__("Наступний документ")
							)}" data-ua-tip="${esc(__("Наступний"))}">${icon("chev-d")}</button>
							<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-fav" data-ua-cmd="fav" aria-pressed="false" aria-label="${esc(
								__("В обране")
							)}" data-ua-tip="${esc(__("Додати в обране"))}">${icon("star")}</button>
						</div>
					</div>
					<div class="ua-doc-toolbar" role="toolbar" aria-label="${esc(__("Команди документа"))}"></div>
				</div>`
			);
			$title.prepend($block);
			$block.on("click", "[data-ua-cmd]", function (e) {
				F.command(window.cur_frm && cur_frm.doctype === frm.doctype ? cur_frm : frm, $(this).attr("data-ua-cmd"), this, e);
			});
		}
		$block.find(".ua-doc-type").text(__(frm.doctype));
		$block.find(".ua-no").text(F.title_text(frm));
		const st = F.status(frm);
		$block
			.find(".ua-doc-status")
			.attr("class", `ua-badge ua-badge--lg ua-doc-status ${st ? st[0] : ""}`)
			.text(st ? st[1] : "")
			.prop("hidden", !st);
		const fav = !frm.is_new() && ua_accounting.shell.is_fav(F.fav_entry(frm).key);
		$block.find(".ua-fav").toggleClass("is-on", fav).attr("aria-pressed", fav).prop("hidden", frm.is_new());
		$block.find("[data-ua-cmd=prev], [data-ua-cmd=next]").prop("hidden", frm.is_new());
		F.render_toolbar(frm, $block.find(".ua-doc-toolbar"));
		F.render_dirty(frm);
	};

	F.render_dirty = function (frm) {
		// a new document is always "dirty" in Frappe; the "Чернетка" badge already says it is not written
		const on = frm.is_dirty() && !frm.is_new() && frm.doc.docstatus === 0;
		$(frm.page.wrapper).find(".ua-dirty").toggleClass("is-on", !!on);
	};

	const btn = (cmd, label, ic, opts) => {
		opts = opts || {};
		const cls = ["ua-btn"];
		if (opts.primary) cls.push("ua-btn--primary");
		if (opts.ghost) cls.push("ua-btn--ghost");
		if (opts.icon_only) cls.push("ua-btn--icon");
		const tip = opts.tip ? ` data-ua-tip="${esc(opts.tip)}"` : "";
		const menu = opts.menu ? ' aria-haspopup="menu" aria-expanded="false"' : "";
		const aria = opts.icon_only ? ` aria-label="${esc(label)}"` : "";
		return (
			`<button type="button" class="${cls.join(" ")}" data-ua-cmd="${cmd}"${tip}${menu}${aria}>` +
			(ic ? icon(ic) : "") +
			(opts.icon_only ? "" : esc(label)) +
			(opts.menu && !opts.icon_only ? icon("chev-d") : "") +
			"</button>"
		);
	};

	F.render_toolbar = function (frm, $bar) {
		const kind = F.kind(frm);
		const perm = F.perm(frm);
		const ds = frm.doc.docstatus;
		const left = [];
		const mid = [];
		if (kind === "catalog") {
			if (perm.write && !frm.save_disabled) {
				left.push(btn("save_close", __("Записати і закрити"), "check", { primary: true, tip: "Ctrl + Enter" }));
				left.push(btn("save", __("Записати"), "save", { tip: "Ctrl + S" }));
			}
		} else if (ds === 0) {
			if (perm.write && !frm.save_disabled) {
				if (perm.submit) left.push(btn("post_close", __("Провести і закрити"), "checks", { primary: true, tip: "Ctrl + Enter" }));
				else left.push(btn("save_close", __("Записати і закрити"), "check", { primary: true, tip: "Ctrl + Enter" }));
				left.push(btn("save", __("Записати"), "save", { tip: "Ctrl + S" }));
				if (perm.submit) left.push(btn("post", __("Провести"), "checks"));
			}
		} else if (ds === 1) {
			if (perm.cancel) left.push(btn("unpost", F.posting(frm) ? __("Скасувати проведення") : __("Скасувати"), "undo"));
		} else if (ds === 2 && perm.amend) {
			left.push(btn("amend", __("Змінити"), "pencil", { primary: true }));
		}
		if (kind === "document") {
			if (F.posting(frm)) mid.push(btn("dtkt", __("Дт/Кт"), "dtkt", { tip: __("Проводки документа") }));
			if (beeone.basis.entries(frm).length) {
				mid.push(btn("basis", __("Створити на підставі"), "branch", { menu: true }));
			}
		}
		((ua_accounting.docs.EXTRA || {})[frm.doctype] || []).forEach(([label, ic, fn, show], i) => {
			if (!frm.is_new() && (!show || show(frm))) mid.push(btn("extra" + i, __(label), ic));
		});
		if (!frm.is_new()) mid.push(btn("print", __("Друк"), "printer"));
		const sep = left.length && mid.length ? '<span class="ua-toolbar-sep"></span>' : "";
		$bar.html(
			left.join("") +
				sep +
				mid.join("") +
				`<div class="ua-right">${btn("more", __("Ще дії"), "more", { ghost: true, icon_only: true, menu: true })}${btn(
					"close_list",
					__("Закрити"),
					null,
					{ ghost: true }
				)}</div>`
		);
	};

	F.command = function (frm, cmd, el) {
		const go_list = () => frappe.set_route("List", frm.doctype);
		if (/^extra\d+$/.test(cmd)) {
			const extra = (ua_accounting.docs.EXTRA[frm.doctype] || [])[+cmd.slice(5)];
			return extra && extra[2](frm);
		}
		switch (cmd) {
			case "back":
			case "close_list":
				return F.leave(frm, go_list);
			case "close":
				return go_list();
			case "post_close":
				return ua_accounting.form.save_and_close(frm, "Submit", $(el));
			case "save_close":
				return ua_accounting.form.save_and_close(frm, "Save", $(el));
			case "save":
				return frm.save("Save", null, $(el));
			case "post":
				return frm.save("Submit", null, $(el));
			case "unpost":
				return frm.savecancel($(el));
			case "amend":
				return frm.amend_doc();
			case "dtkt":
				return F.dtkt(frm);
			case "print":
				return frm.print_doc();
			case "prev":
			case "next":
				return $(frm.page.wrapper).find(`.page-head .${cmd}-doc`).first().trigger("click");
			case "fav": {
				const on = ua_accounting.shell.toggle_fav(F.fav_entry(frm));
				$(el).toggleClass("is-on", on).attr("aria-pressed", on);
				return;
			}
			case "basis":
				return F.basis_menu(frm, el);
			case "more":
				return F.more_menu(frm, el);
		}
	};

	F.dtkt = function (frm) {
		if (frm.doc.docstatus === 1) {
			ua_accounting.docs.show_entries(frm);
			return;
		}
		const can_post = frm.doc.docstatus === 0 && F.perm(frm).submit && F.perm(frm).write;
		const d = ua_accounting.ui.dialog({
			title: __("Проводок ще немає"),
			width: 480,
			html:
				`<div class="ua-dialog-head"><div><div class="ua-dialog-title">${esc(__("Проводок ще немає"))}</div>` +
				`<div class="ua-dialog-sub">${esc(__("Документ не проведено, тому він не формує записів Дт/Кт."))}</div></div>` +
				`<button class="ua-btn ua-btn--ghost ua-btn--icon" data-close aria-label="${esc(__("Закрити"))}">${icon("x")}</button></div>` +
				`<div class="ua-dialog-foot"><span></span><div class="ua-right"><button class="ua-btn" data-close>${esc(__("Скасувати"))}</button>` +
				(can_post
					? `<button class="ua-btn ua-btn--primary" data-act="post" autofocus>${icon("checks")}${esc(__("Провести і показати"))}</button>`
					: "") +
				"</div></div>",
		});
		$(d.box)
			.find("[data-act=post]")
			.on("click", () => {
				d.close();
				frm.save("Submit").then(() => frm.doc.docstatus === 1 && ua_accounting.docs.show_entries(frm));
			});
	};

	F.basis_menu = function (frm, el) {
		const list = beeone.basis.entries(frm);
		ua_accounting.ui.menu(
			el,
			`<div class="ua-menu-label">${esc(__("Створити на підставі"))}</div>` +
				list.map((b, i) => `<button class="ua-menu-item" data-i="${i}">${icon("file-plus")}${esc(__(b.label))}</button>`).join(""),
			(item) => {
				const b = list[+item.getAttribute("data-i")];
				if (!b) return;
				if (frm.doc.docstatus !== 1) {
					ua_accounting.ui.toast({ type: "warning", title: __("Спочатку проведіть документ"), text: __("Документ на підставі створюється з проведеного.") });
					return;
				}
				beeone.basis.create(frm, b);
			}
		);
	};

	F.more_menu = function (frm, el) {
		const perm = F.perm(frm);
		const items = [];
		if (!frm.is_new() && frm.perm[0] && frappe.model.can_create(frm.doctype)) {
			items.push(`<button class="ua-menu-item" data-a="copy">${icon("copy")}${esc(__("Скопіювати"))}</button>`);
		}
		if (!frm.is_new()) {
			items.push(`<button class="ua-menu-item" data-a="reload">${icon("refresh")}${esc(__("Оновити з бази"))}</button>`);
			items.push(`<button class="ua-menu-item" data-a="history">${icon("history")}${esc(__("Історія змін"))}</button>`);
		}
		if (!frm.is_new() && frm.doc.docstatus !== 1 && perm.delete) {
			items.push('<div class="ua-menu-sep"></div>');
			items.push(`<button class="ua-menu-item is-danger" data-a="delete">${icon("trash")}${esc(__("Видалити"))}</button>`);
		}
		if (!items.length) items.push(`<div class="ua-menu-empty">${esc(__("Інших дій немає"))}</div>`);
		ua_accounting.ui.menu(
			el,
			items.join(""),
			(item) => {
				const a = item.getAttribute("data-a");
				if (a === "copy") frm.copy_doc();
				if (a === "reload") frm.reload_doc();
				if (a === "history") F.toggle_history(frm, true);
				if (a === "delete") {
					frappe.confirm(__("Видалити {0}?", [ua_accounting.shell.doc_title(frm)]), () =>
						frappe.model.delete_doc(frm.doctype, frm.doc.name, () => frappe.set_route("List", frm.doctype))
					);
				}
			},
			{ align: "right" }
		);
	};

	F.toggle_history = function (frm, show) {
		const $w = $(frm.page.wrapper);
		$w.toggleClass("ua-show-history", show);
		if (show) {
			const el = $w.find(".form-footer").get(0);
			if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
		}
	};

	// ---------------------------------------------------------------- unsaved changes

	F.leave = function (frm, go) {
		if (!frm.is_dirty() || frm.doc.docstatus !== 0) {
			go();
			return;
		}
		const d = ua_accounting.ui.dialog({
			title: __("Записати зміни?"),
			width: 460,
			html:
				`<div class="ua-dialog-head"><div><div class="ua-dialog-title">${esc(__("Записати зміни?"))}</div>` +
				`<div class="ua-dialog-sub">${esc(
					frm.is_new()
						? __("Новий документ ще не записано.")
						: __("У документі {0} є незаписані зміни.", [ua_accounting.shell.doc_title(frm)])
				)}</div></div></div>` +
				`<div class="ua-dialog-foot"><button class="ua-btn ua-btn--danger-ghost" data-act="drop">${esc(__("Не записувати"))}</button>` +
				`<div class="ua-right"><button class="ua-btn" data-close>${esc(__("Скасувати"))}</button>` +
				`<button class="ua-btn ua-btn--primary" data-act="save" autofocus>${esc(__("Записати"))}</button></div></div>`,
		});
		d.box.setAttribute("role", "alertdialog");
		$(d.box).on("click", "[data-act]", function () {
			const act = $(this).attr("data-act");
			d.close();
			if (act === "save") {
				frm.save().then(() => !frm.is_dirty() && go());
			} else {
				// the changes stay only in the browser: drop them, the next open reads the database
				frappe.model.remove_from_locals(frm.doctype, frm.doc.name);
				go();
			}
		});
	};

	// ---------------------------------------------------------------- layout: cards, side card, table part

	F.section_kind = function (section) {
		const df = section.df || {};
		const fields = (section.fields_list || []).map((f) => f.df || {});
		if (fields.some((f) => f.fieldtype === "Table")) return "table";
		if (df.fieldname === "sb_totals") return "totals";
		if (df.fieldname === "sb_more" && fields.every((f) => ["comment", "amended_from"].includes(f.fieldname))) return "more";
		return "main";
	};

	F.setup_layout = function (frm) {
		const layout = frm.layout;
		if (!layout || layout.ua_done) return;
		const kind = F.kind(frm);
		const $page = $(layout.wrapper).find(".form-page").first();
		if (!$page.length) return;
		layout.ua_done = true;
		const sections = (layout.sections || []).filter((s) => s.wrapper && $(s.wrapper).closest(".form-page")[0] === $page[0]);
		const groups = { main: [], table: [], totals: [], more: [] };
		sections.forEach((s) => groups[F.section_kind(s)].push(s));
		const is_doc = kind === "document";

		// "Основне" card (+ side card for documents)
		const $grid = $(`<div class="ua-doc-grid${is_doc ? "" : " ua-doc-grid--single"}"></div>`);
		const $main = $(
			`<section class="ua-card ua-main-card"><div class="ua-card-head"><h2 class="ua-card-title">${esc(
				__("Основне")
			)}</h2></div><div class="ua-main-body"></div></section>`
		);
		$grid.append($main);
		if (is_doc) {
			$grid.append(
				`<aside class="ua-card ua-aside" aria-label="${esc(__("Відомості про документ"))}"><div class="ua-aside-body"></div></aside>`
			);
		}
		const first = groups.main[0] || sections[0];
		if (first) $(first.wrapper).before($grid);
		// catalogs: only the first section joins the card, the others stay cards of their own
		const into_main = is_doc ? groups.main : groups.main.slice(0, 1);
		into_main.forEach((s) => $main.find(".ua-main-body").append(s.wrapper));
		groups.main.slice(into_main.length).forEach((s) => $(s.wrapper).addClass("ua-card ua-sec-card"));

		// table part card with tabs
		if (groups.table.length) {
			const $tp = $(
				`<section class="ua-card ua-tp" aria-label="${esc(__("Табличні частини"))}">` +
					`<div class="ua-tabs ua-tp-tabs" role="tablist"></div><div class="ua-tp-toolbar" role="toolbar" aria-label="${esc(
						__("Команди таблиці")
					)}"></div><div class="ua-tp-body"></div></section>`
			);
			$grid.after($tp);
			groups.table.forEach((s, i) => {
				const grid_field = (s.fields_list || []).find((f) => f.df && f.df.fieldtype === "Table");
				const key = grid_field ? grid_field.df.fieldname : "t" + i;
				$(s.wrapper).attr("data-ua-tab", key).addClass("ua-tp-section");
				$tp.find(".ua-tp-body").append(s.wrapper);
				$tp.find(".ua-tp-tabs").append(
					`<button type="button" class="ua-tab" role="tab" data-tab="${esc(key)}">${esc(
						__((grid_field && grid_field.df.label) || (s.df && s.df.label) || "")
					)} <span class="ua-count"></span></button>`
				);
			});
			frm.ua_tab = frm.ua_tab || $tp.find(".ua-tab").first().attr("data-tab");
			$tp.on("click", ".ua-tab", function () {
				frm.ua_tab = $(this).attr("data-tab");
				F.render_tp(frm);
			});
			$tp.on("click", "[data-tp]", function () {
				F.tp_command(frm, $(this).attr("data-tp"));
			});
		}
		groups.totals.forEach((s) => $(s.wrapper).addClass("ua-hidden-section"));
		groups.more.forEach((s) => $(s.wrapper).addClass("ua-hidden-section"));

		// sticky totals footer (documents with totals or a comment)
		const has_totals = ["total_amount", "amount"].some((f) => frappe.meta.has_field(frm.doctype, f));
		const has_comment = frappe.meta.has_field(frm.doctype, "comment");
		if (is_doc && (has_totals || has_comment)) {
			const $foot = $(
				`<div class="ua-doc-foot">` +
					(has_comment
						? `<label class="ua-input ua-comment" data-ua-tip="${esc(__("Коментар видно лише в базі, він не друкується"))}">${icon(
								"pencil"
						  )}<input data-ua-comment placeholder="${esc(__("Коментар"))}" aria-label="${esc(__("Коментар"))}"></label>`
						: "") +
					`<div class="ua-totals" aria-live="polite"></div></div>`
			);
			$(layout.wrapper).closest(".layout-main-section").after($foot);
			$foot.on("change", "[data-ua-comment]", function () {
				if (frm.doc.docstatus === 0 && cur_frm === frm) frm.set_value("comment", this.value);
			});
		}
		$(frm.page.wrapper).addClass("ua-form ua-form--" + kind);
	};

	F.render_tp = function (frm) {
		const $tp = $(frm.layout.wrapper).find(".ua-tp");
		if (!$tp.length) return;
		const tab = frm.ua_tab;
		$tp.find(".ua-tp-section").each(function () {
			$(this).toggleClass("ua-tp-off", $(this).attr("data-ua-tab") !== tab);
		});
		$tp.find(".ua-tab").each(function () {
			const key = $(this).attr("data-tab");
			const on = key === tab;
			$(this).toggleClass("is-on", on).attr("aria-selected", on);
			$(this).find(".ua-count").text((frm.doc[key] || []).length);
		});
		ua_accounting.ui.place_ink($tp.find(".ua-tp-tabs")[0]);
		const field = frm.fields_dict[tab];
		const grid = field && field.grid;
		const editable = !!grid && frm.doc.docstatus === 0 && !grid.df.read_only && !!F.perm(frm).write;
		const rows = (frm.doc[tab] || []).length;
		const sel = grid ? grid.get_selected_children().length : 0;
		const b = (cmd, label, ic, extra) =>
			`<button type="button" class="ua-btn ua-btn--sm${extra && extra.icon_only ? " ua-btn--ghost ua-btn--icon" : ""}" data-tp="${cmd}"` +
			`${extra && extra.tip ? ` data-ua-tip="${esc(extra.tip)}"` : ""}${extra && extra.icon_only ? ` aria-label="${esc(label)}"` : ""}>` +
			`${icon(ic)}${extra && extra.icon_only ? "" : esc(label)}</button>`;
		$tp.find(".ua-tp-toolbar").html(
			(editable
				? b("add", __("Додати"), "plus", { tip: "Ins" }) +
				  '<span class="ua-toolbar-sep"></span>' +
				  b("up", __("Перемістити вгору"), "arrow-up", { icon_only: true, tip: __("Вгору · Ctrl + Shift + ↑") }) +
				  b("down", __("Перемістити вниз"), "arrow-down", { icon_only: true, tip: __("Вниз · Ctrl + Shift + ↓") }) +
				  b("copy", __("Скопіювати рядок"), "copy", { icon_only: true, tip: __("Скопіювати") }) +
				  b("delete", __("Видалити рядок"), "trash", { icon_only: true, tip: __("Видалити") })
				: "") +
				`<span class="ua-right ua-tp-meta">${esc(
					sel ? __("Вибрано {0} з {1}", [sel, rows]) : rows ? __("Рядків: {0}", [rows]) : ""
				)}</span>`
		);
		// empty table: the mockup's "Додайте товари"
		$tp.find(".ua-tp-empty").remove();
		if (!rows && grid) {
			const label = __((field.df && field.df.label) || "");
			$(grid.wrapper).append(
				`<div class="ua-tp-empty">${ua_accounting.ui.empty_html({
					art: tab === "goods" ? "package" : "file",
					title: tab === "goods" ? __("Додайте товари") : __("Таблиця «{0}» порожня", [label]),
					text: editable ? __("Натисніть «Додати», щоб внести перший рядок.") : "",
				})}</div>`
			);
		}
	};

	F.tp_command = function (frm, cmd) {
		const field = frm.fields_dict[frm.ua_tab];
		const grid = field && field.grid;
		if (!grid) return;
		if (cmd === "add") {
			const $add = $(grid.wrapper).find(".grid-add-row").first();
			if ($add.length) $add.trigger("click");
			else grid.add_new_row(null, null, true);
		} else if (cmd === "up" || cmd === "down") {
			ua_accounting.form.move_rows(frm, grid, cmd === "up" ? -1 : 1);
		} else if (cmd === "copy" || cmd === "delete") {
			if (!grid.get_selected_children().length) {
				ua_accounting.ui.toast({ type: "info", title: __("Відмітьте рядки"), text: __("Поставте позначку зліва від рядка.") });
				return;
			}
			if (cmd === "copy") {
				grid.duplicate_rows();
				// the copies change the totals: the same recalculation as a changed row
				if (ua_accounting.docs.TRADE.includes(frm.doctype)) ua_accounting.docs.recalc(frm);
			} else grid.delete_rows();
		}
		setTimeout(() => F.render_tp(frm), 50);
	};

	// ---------------------------------------------------------------- side card

	F.render_side = function (frm) {
		const $side = $(frm.layout.wrapper).find(".ua-aside-body");
		if (!$side.length) return;
		const last = (txt) =>
			`<div class="ua-last-ev">${icon("history", "ua-i-sm")}<span>${esc(txt)}</span>` +
			(frm.is_new() ? "" : `<button class="ua-btn ua-btn--ghost ua-btn--sm" data-side="history">${esc(__("Історія змін"))}</button>`) +
			"</div>";
		if (frm.is_new()) {
			$side.html(
				`<div class="ua-card-head"><h2 class="ua-card-title">${esc(__("Взаєморозрахунки"))}</h2></div>` +
					`<div class="ua-card-body ua-side-note">${esc(__("Після запису тут будуть взаєморозрахунки та пов’язані документи."))}</div>` +
					`<div class="ua-last-ev is-new">${icon("history", "ua-i-sm")}<span>${esc(__("Документ ще не записано"))}</span></div>`
			);
			return;
		}
		if (frm.ua_side_for !== frm.doc.name + frm.doc.modified) {
			$side.html(
				`<div class="ua-card-head"><h2 class="ua-card-title">${esc(__("Взаєморозрахунки"))}</h2></div>` +
					`<div class="ua-card-body">${ua_accounting.ui.skeleton_rows(3, [80])}</div>`
			);
		}
		const key = frm.doc.name + frm.doc.modified;
		frm.ua_side_for = key;
		frappe
			.xcall("ua_accounting.desk.get_doc_side", { doctype: frm.doctype, name: frm.doc.name })
			.then((r) => {
				if (frm.ua_side_for !== key) return;
				const kv = (label, v, hint) =>
					`<div class="ua-kv"><span>${esc(label)}</span><b class="ua-num">${esc(v)}${
						hint ? ` <span class="ua-kv-hint">${esc(hint)}</span>` : ""
					}</b></div>`;
				const side = (v) => (v > 0 ? __("Дт") : v < 0 ? __("Кт") : "");
				let html = `<div class="ua-card-head"><h2 class="ua-card-title">${esc(__("Взаєморозрахунки"))}</h2></div><div class="ua-card-body ua-kvs">`;
				const s = r.settlement;
				if (s) {
					html += kv(__("Сальдо до документа"), money(Math.abs(s.before)), side(s.before));
					if (s.after !== null && s.after !== undefined) {
						html += kv(frm.doc.docstatus === 1 ? __("Після документа") : __("Після проведення"), money(Math.abs(s.after)), side(s.after));
					}
				} else {
					html += `<div class="ua-side-note">${esc(__("Контрагента не вказано"))}</div>`;
				}
				html += "</div>";
				// related documents + documents that can be made from this one
				const rel = (r.related || []).map(
					(d) =>
						`<a class="ua-rel" href="${esc(frappe.utils.get_form_link(d.doctype, d.name))}"><span class="ua-fi">${icon(
							"file"
						)}</span><div class="ua-grow">${esc(__(d.doctype))}<small>${esc(d.name)}${
							d.posting_date ? ` ${esc(__("від"))} ${esc(frappe.datetime.str_to_user(d.posting_date))}` : ""
						} · ${esc(d.role === "basis" ? __("підстава") : __("на підставі"))}</small></div></a>`
				);
				beeone.basis.entries(frm).forEach(({ label }, i) => {
					if ((r.related || []).some((d) => d.role === "derived" && __(d.doctype) === __(label))) return;
					rel.push(
						`<div class="ua-rel"><span class="ua-fi">${icon("file-plus")}</span><div class="ua-grow">${esc(__(label))}<small>${esc(
							__("Ще не створено")
						)}</small></div><button class="ua-btn ua-btn--sm ua-btn--secondary" data-side="basis" data-i="${i}">${esc(
							__("Створити")
						)}</button></div>`
					);
				});
				html +=
					`<div class="ua-card-head ua-aside-sep"><h2 class="ua-card-title">${esc(__("Пов’язані документи"))}</h2></div>` +
					`<div class="ua-card-body ua-rels">${rel.length ? rel.join("") : `<div class="ua-side-note">${esc(__("Пов’язаних документів немає"))}</div>`}</div>`;
				html += last(__("Записано {0}", [frappe.datetime.str_to_user(r.modified).slice(0, 16)]));
				$side.html(html);
			})
			.catch(() => {
				if (frm.ua_side_for !== key) return;
				frm.ua_side_for = null;
				$side.html(
					ua_accounting.ui.empty_html({
						error: true,
						title: __("Не вдалося завантажити"),
						text: __("Взаєморозрахунки та пов’язані документи недоступні."),
						actions: [{ label: __("Повторити"), act: "side-retry", icon: "refresh" }],
						cls: "ua-empty--sm",
					})
				);
			});
		$side.off("click.ua").on("click.ua", "[data-side], [data-act=side-retry]", function () {
			const what = $(this).attr("data-side") || "retry";
			if (what === "history") F.toggle_history(frm, !$(frm.page.wrapper).hasClass("ua-show-history"));
			if (what === "retry") F.render_side(frm);
			if (what === "basis") {
				const b = beeone.basis.entries(frm)[+$(this).attr("data-i")];
				if (!b) return;
				if (frm.doc.docstatus !== 1) {
					ua_accounting.ui.toast({ type: "warning", title: __("Спочатку проведіть документ"), text: __("Документ на підставі створюється з проведеного.") });
					return;
				}
				beeone.basis.create(frm, b);
			}
		});
	};

	// ---------------------------------------------------------------- totals footer

	F.render_totals = function (frm) {
		const $foot = $(frm.page.wrapper).find(".ua-doc-foot");
		if (!$foot.length) return;
		const d = frm.doc;
		const cur = d.currency && d.currency !== "UAH" ? d.currency : "₴";
		const m = (v) => `${ua_accounting.ui.money(v || 0)} ${cur}`;
		const parts = [];
		if (frappe.meta.has_field(frm.doctype, "total_amount")) {
			parts.push(`<span class="ua-t">${esc(__("Сума без ПДВ"))} <b class="ua-num">${esc(m(d.total_net))}</b></span>`);
			parts.push(`<span class="ua-t">${esc(__("ПДВ"))} <b class="ua-num">${esc(m(d.vat_total))}</b></span>`);
			parts.push(`<span class="ua-t ua-t-grand">${esc(__("Всього"))} <b class="ua-num">${esc(m(d.total_amount))}</b></span>`);
			if (cur !== "₴" && d.base_total) parts.push(`<span class="ua-t">${esc(__("у гривнях"))} <b class="ua-num">${esc(money(d.base_total))}</b></span>`);
		} else if (frappe.meta.has_field(frm.doctype, "amount")) {
			if (d.vat_amount) parts.push(`<span class="ua-t">${esc(__("ПДВ"))} <b class="ua-num">${esc(m(d.vat_amount))}</b></span>`);
			parts.push(`<span class="ua-t ua-t-grand">${esc(__("Сума"))} <b class="ua-num">${esc(m(d.amount))}</b></span>`);
		}
		$foot.find(".ua-totals").html(parts.join(""));
		const $c = $foot.find("[data-ua-comment]");
		if ($c.length && !$c.is(":focus")) $c.val(d.comment || "");
		$c.prop("readonly", d.docstatus !== 0);
	};

	// ---------------------------------------------------------------- wiring

	F.refresh = function (frm) {
		if (!F.kind(frm) || F.kind(frm) === "register") return;
		if (frm.page.current_view_name === "print" || frm.hidden) return;
		F.setup_layout(frm);
		F.render_head(frm);
		F.render_tp(frm);
		F.render_side(frm);
		F.render_totals(frm);
		$(frm.page.wrapper).removeClass("ua-show-history");
	};

	$(document).on("form-refresh", (e, frm) => {
		try {
			F.refresh(frm);
		} catch (err) {
			console.error("ua_form", err);
		}
	});

	// "dirty" comes on every change of a value: the chip, the totals and the table meta follow it
	$(document).on("dirty", ".page-container", function () {
		const frm = window.cur_frm;
		if (!frm || !F.kind(frm) || $(frm.page.wrapper)[0] !== this) return;
		F.render_dirty(frm);
		F.render_totals(frm);
		F.render_tp(frm);
	});

	// totals change through set_value after the recalculation
	ua_accounting.ui.DOCUMENTS.forEach((doctype) => {
		const on = (frm) => F.kind(frm) && F.render_totals(frm);
		frappe.ui.form.on(doctype, { total_amount: on, total_net: on, vat_total: on, amount: on, vat_amount: on });
	});

	// grid row selection changes the table meta
	$(document).on("change", ".ua-form .grid-row-check", () => {
		const frm = window.cur_frm;
		if (frm && F.kind(frm)) setTimeout(() => F.render_tp(frm), 0);
	});

	// Ctrl+S = Записати (Frappe uses it for the primary action, which is "Провести і закрити" here).
	// frappe.app exists after "startup".
	$(document).on("startup", () => {
		if (!frappe.app || frappe.app.ua_patched_ctrl_s || !frappe.app.trigger_primary_action) return;
		const original = frappe.app.trigger_primary_action;
		frappe.app.ua_patched_ctrl_s = true;
		frappe.app.trigger_primary_action = function () {
			const frm = window.cur_frm;
			const route = frappe.get_route() || [];
			if (frm && route[0] === "Form" && route[1] === frm.doctype && F.kind(frm) && !$(".modal.show").length) {
				if (frm.doc.docstatus === 0 && F.perm(frm).write) frm.save("Save");
				return;
			}
			return original.apply(this, arguments);
		};
	});

	// Esc on a form (no field, menu or dialog in focus) goes back to the list
	$(document).on("keydown.ua_form_esc", (e) => {
		if (e.key !== "Escape" || e.defaultPrevented) return;
		const frm = window.cur_frm;
		const route = frappe.get_route() || [];
		if (!frm || route[0] !== "Form" || route[1] !== frm.doctype || !F.kind(frm)) return;
		if ($(document.activeElement).is("input, textarea, select, [contenteditable=true]")) return;
		if ($(".modal.show").length || document.querySelector(".ua-dialog-backdrop") || ua_accounting.ui.menu_open()) return;
		if (document.documentElement.classList.contains("ua-fpanel-open")) return;
		F.leave(frm, () => frappe.set_route("List", frm.doctype));
	});

	// Ctrl+Shift+↑/↓: move the marked rows of the open table part
	$(document).on("keydown.ua_form_rows", (e) => {
		if (!(e.ctrlKey || e.metaKey) || !e.shiftKey || !["ArrowUp", "ArrowDown"].includes(e.key)) return;
		const frm = window.cur_frm;
		if (!frm || !F.kind(frm) || !frm.ua_tab || frm.doc.docstatus !== 0) return;
		const field = frm.fields_dict[frm.ua_tab];
		if (!field || !field.grid) return;
		e.preventDefault();
		ua_accounting.form.move_rows(frm, field.grid, e.key === "ArrowUp" ? -1 : 1);
	});

	// ---------------------------------------------------------------- messages

	// "Missing Fields": the message says what to do («Заповніть поле «Контрагент».»)
	(function () {
		const original = frappe.msgprint;
		frappe.msgprint = function (msg) {
			try {
				const frm = window.cur_frm;
				if (msg && typeof msg === "object" && msg.title === __("Missing Fields") && frm && F.kind(frm)) {
					const items = $("<div>")
						.html(msg.message || "")
						.find("li")
						.map((i, li) => $(li).text().trim())
						.get()
						.filter(Boolean);
					// a line is "Організація: обов’язкове поле." -> «Організація»
					const names = items.map((t) => `«${t.split(/:\s/)[0].replace(/\.$/, "")}»`);
					const text =
						names.length === 1 ? __("Заповніть поле {0}.", [names[0]]) : __("Заповніть поля: {0}.", [names.join(", ")]);
					arguments[0] = Object.assign({}, msg, {
						title: __("Не всі поля заповнені"),
						message: esc(text),
						indicator: "red",
					});
				}
			} catch (e) {
				// keep Frappe's own message
			}
			return original.apply(this, arguments);
		};
	})();

	// frappe.show_alert -> our toast (bottom right, icon, 4 s, stops on hover)
	(function () {
		const original = frappe.show_alert;
		const TYPE = { green: "success", red: "error", orange: "warning", yellow: "warning", blue: "info", gray: "info" };
		frappe.show_alert = function (message, seconds, actions) {
			if (!document.body.classList.contains("ua-shell") || !ua_accounting.ui.toast) {
				return original.apply(this, arguments);
			}
			const o = typeof message === "string" ? { message } : message || {};
			const text = $("<div>")
				.html(o.message || o.body || "")
				.text()
				.trim();
			if (!text) return original.apply(this, arguments);
			ua_accounting.ui.toast({
				title: o.title ? $("<div>").html(o.title).text() : text,
				text: o.title ? text : "",
				type: TYPE[o.indicator] || "success",
				duration: Math.max(4000, (seconds || 0) * 1000),
			});
			return $("<div>");
		};
	})();
})();
