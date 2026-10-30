// 1C toolbar of the forms of UA doctypes.
//  document: Провести і закрити (Ctrl+Enter), Записати, Провести, Дт/Кт, Створити на підставі, Друк
//  catalog:  Записати і закрити, Записати
// Frappe sets its primary button again on every refresh and on "dirty", so we wrap
// Toolbar.set_primary_action. Custom buttons are added in "form-refresh" (after Frappe cleared them).
frappe.provide("ua_accounting.form");

// own scope: all scripts of the desk share one global scope
(function () {
	const POSTING = () => ua_accounting.docs.POSTING;

	ua_accounting.form.close_to_list = function (frm) {
		frappe.set_route("List", frm.doctype);
	};

	// Save (and post) then go to the list. The route changes only when the save really worked.
	ua_accounting.form.save_and_close = function (frm, action, btn) {
		return frm.save(action, null, btn).then(() => {
			if (!frm.is_new() && !frm.is_dirty()) {
				ua_accounting.form.close_to_list(frm);
			}
		});
	};

	ua_accounting.form.apply_toolbar = function (frm) {
		const page = frm.page;
		const kind = ua_accounting.ui.kind(frm.doctype);
		if (!page || !kind || kind === "register") return;
		// print view and hidden forms keep the Frappe buttons
		if (page.current_view_name === "print" || frm.hidden) return;

		const perm = frm.perm && frm.perm[0] ? frm.perm[0] : {};

		if (kind === "catalog") {
			if (!perm.write || frm.save_disabled) return;
			page.set_primary_action(__("Записати і закрити"), (btn) => ua_accounting.form.save_and_close(frm, "Save", btn));
			page.set_secondary_action(__("Записати"), (btn) => frm.save("Save", null, btn));
			return;
		}

		// document
		if (frm.doc.docstatus === 0) {
			if (!perm.write || frm.save_disabled) return;
			if (perm.submit) {
				page.set_primary_action(__("Провести і закрити"), (btn) =>
					ua_accounting.form.save_and_close(frm, "Submit", btn)
				);
			} else {
				page.set_primary_action(__("Записати і закрити"), (btn) => ua_accounting.form.save_and_close(frm, "Save", btn));
			}
			page.set_secondary_action(__("Записати"), (btn) => frm.save("Save", null, btn));
		} else if (frm.doc.docstatus === 1) {
			page.set_primary_action(__("Закрити"), () => ua_accounting.form.close_to_list(frm));
			if (perm.cancel) {
				const label = POSTING().includes(frm.doctype) ? __("Скасувати проведення") : __("Скасувати");
				page.set_secondary_action(label, (btn) => frm.savecancel(btn));
			}
		}
		// docstatus 2: Frappe shows "Змінити" (Amend)
	};

	ua_accounting.form.add_buttons = function (frm) {
		const kind = ua_accounting.ui.kind(frm.doctype);
		if (kind !== "document" && kind !== "catalog") return;
		if (frm.page.current_view_name === "print" || frm.hidden) return;
		const perm = frm.perm && frm.perm[0] ? frm.perm[0] : {};

		if (kind === "document") {
			if (frm.doc.docstatus === 0 && perm.submit && perm.write && !frm.save_disabled) {
				frm.add_custom_button(__("Провести"), () => frm.save("Submit"));
			}
			if (POSTING().includes(frm.doctype)) {
				const btn = frm.add_custom_button(__("Дт/Кт"), () => {
					if (frm.doc.docstatus === 1) {
						ua_accounting.docs.show_entries(frm);
					} else {
						frappe.show_alert({ message: __("Документ не проведено"), indicator: "orange" });
					}
				});
				if (btn) btn.attr("title", __("Результат проведення"));
			}
		}
		if (!frm.is_new()) {
			frm.add_custom_button(__("Друк"), () => frm.print_doc());
		}
	};

	// ---------------------------------------------------------------- table parts: ↑ / ↓

	ua_accounting.form.move_rows = function (frm, grid, direction) {
		const field = grid.df.fieldname;
		const rows = frm.doc[field] || [];
		const selected = grid.get_selected_children().map((r) => r.name);
		if (!selected.length) {
			frappe.show_alert({ message: __("Відмітьте рядки"), indicator: "orange" });
			return;
		}
		const order = rows.slice();
		const indexes = order.map((r, i) => (selected.includes(r.name) ? i : -1)).filter((i) => i >= 0);
		const walk = direction < 0 ? indexes : indexes.slice().reverse();
		walk.forEach((i) => {
			const j = i + direction;
			if (j < 0 || j >= order.length || selected.includes(order[j].name)) return;
			[order[i], order[j]] = [order[j], order[i]];
		});
		order.forEach((row, i) => (row.idx = i + 1));
		frm.doc[field] = order;
		frm.dirty();
		frm.refresh_field(field);
	};

	ua_accounting.form.setup_grids = function (frm) {
		Object.values(frm.fields_dict || {}).forEach((field) => ua_accounting.form.setup_grid(frm, field.grid));
	};

	ua_accounting.form.setup_grid = function (frm, grid) {
		if (!grid || !grid.wrapper || grid.wrapper.find(".ua-grid-up").length) return;
		const $add = grid.wrapper.find(".grid-buttons .grid-add-row");
		if (!$add.length) return;
		const make = (cls, text, title, direction) =>
			$(
				`<button type="button" class="btn btn-xs btn-default ${cls}" title="${frappe.utils.escape_html(
					title
				)}">${text}</button>`
			).on("click", () => ua_accounting.form.move_rows(frm, grid, direction));
		$add.after(make("ua-grid-down", "↓", __("Вниз"), 1)).after(make("ua-grid-up", "↑", __("Вгору"), -1));
	};

	// ---------------------------------------------------------------- wiring

	(function () {
		if (!frappe.ui.form || !frappe.ui.form.Toolbar) return;
		const original = frappe.ui.form.Toolbar.prototype.set_primary_action;
		frappe.ui.form.Toolbar.prototype.set_primary_action = function () {
			const result = original.apply(this, arguments);
			try {
				ua_accounting.form.apply_toolbar(this.frm);
			} catch (e) {
				console.error("ua_form_toolbar", e);
			}
			return result;
		};
	})();

	// Ctrl+Enter = the primary button of the form ("Провести і закрити" / "Записати і закрити").
	$(document).on("keydown.ua_form", function (e) {
		if (!(e.ctrlKey || e.metaKey) || e.key !== "Enter" || e.shiftKey || e.altKey) return;
		if ($(".modal.show").length) return;
		const frm = window.cur_frm;
		if (!frm || !frm.page || !ua_accounting.ui.kind(frm.doctype) || frm.page.current_view_name === "print") return;
		if (!$(frm.page.wrapper).is(":visible")) return;
		// the UA toolbar has the real command; Frappe's own primary button is hidden
		const $btn = $(frm.page.wrapper).find(".ua-form-toolbar [data-ua-cmd].ua-btn--primary, [data-ua-cmd].ua-btn--primary").filter(":visible").first();
		if (!$btn.length || $btn.prop("disabled")) return;
		e.preventDefault();
		// leave the field first, so its value reaches the document
		if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
		setTimeout(() => ua_accounting.form.command(frm, $btn.attr("data-ua-cmd"), $btn[0]), 150);
	});

	$(document).on("form-refresh", function (e, frm) {
		if (!ua_accounting.ui.kind(frm.doctype)) return;
		// a new form already says "(створення)" with the doctype: no second breadcrumb (see ua_desk.css)
		$(frm.page.wrapper).toggleClass("ua-form-new", frm.is_new());
		ua_accounting.form.apply_toolbar(frm);
		ua_accounting.form.add_buttons(frm);
		// Frappe draws the grid footers a little later
		[0, 150, 600].forEach((ms) => setTimeout(() => ua_accounting.form.setup_grids(frm), ms));
	});
})();
