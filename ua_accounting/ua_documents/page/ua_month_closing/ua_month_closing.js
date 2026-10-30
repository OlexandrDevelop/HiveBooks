// Month-end closing assistant (1C «Закриття місяця»): routine operations in order with their status.
// Data and actions: ua_accounting.api.month_closing (accounting/month_closing.py).
frappe.pages["ua-month-closing"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Закриття місяця"), single_column: true });
	$(wrapper).find(".layout-main-section").append('<div class="ua-mc"></div>');
	$(document).on("ua-org-changed", () => {
		if ($(wrapper).is(":visible")) frappe.pages["ua-month-closing"].on_page_show(wrapper);
	});
};

frappe.pages["ua-month-closing"].on_page_show = function (wrapper) {
	const ui = ua_accounting.ui;
	const esc = ui.esc;
	const API = "ua_accounting.api.month_closing.";
	const $root = $(wrapper).find(".ua-mc");
	const MONTHS = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"];
	const DONE = "Виконано";
	const TODO = "Не виконано";
	const ERROR = "Помилка";

	const query = Object.assign({}, frappe.utils.get_query_params ? frappe.utils.get_query_params() : {}, frappe.route_options || {});
	frappe.route_options = null;
	const shell_org = ua_accounting.shell.current_org ? ua_accounting.shell.current_org() : null;
	const org = query.organization || (shell_org && shell_org.name) || null;
	let period = query.period;
	if (!period) {
		const now = new Date();
		const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
		period = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}-01`;
	}
	const view = { org, year: +period.slice(0, 4), month: +period.slice(5, 7), busy: false, data: null };

	const uk_date = (iso) => (iso ? iso.slice(8, 10) + "." + iso.slice(5, 7) + "." + iso.slice(0, 4) : "");
	const badge = (status) => {
		const cls = status === DONE ? "posted" : status === ERROR ? "cancelled" : status === TODO ? "unposted" : "warning";
		return `<span class="ua-badge ua-badge--${cls}">${esc(__(status))}</span>`;
	};
	const doc_link = (s) =>
		s.document
			? `<a href="/desk/${esc(frappe.router.slug(s.document_type))}/${encodeURIComponent(s.document)}">${esc(s.document)}</a>`
			: "";

	const last_done = (steps) => {
		let last = -1;
		steps.forEach((s, i) => {
			if (s.status === DONE) last = i;
		});
		return last;
	};

	const render = () => {
		if (!view.org) {
			$root.html(ui.empty_html({ title: __("Оберіть організацію"), text: __("Організація вибирається у верхньому меню.") }));
			return;
		}
		const d = view.data;
		const years = [];
		for (let y = view.year - 3; y <= view.year + 1; y++) years.push(y);
		const busy = view.busy ? " disabled" : "";
		let html = `<div class="ua-mc-head ua-card">
			<div class="ua-mc-pick">
				<label>${esc(__("Місяць"))}
					<select class="ua-mc-month">${MONTHS.map((m, i) => `<option value="${i + 1}"${i + 1 === view.month ? " selected" : ""}>${esc(__(m))}</option>`).join("")}</select>
				</label>
				<label>${esc(__("Рік"))}
					<select class="ua-mc-year">${years.map((y) => `<option value="${y}"${y === view.year ? " selected" : ""}>${y}</option>`).join("")}</select>
				</label>
				<span class="ua-mc-org">${esc(d ? d.organization_title || "" : "")}</span>
			</div>
			<div class="ua-mc-actions">
				${d ? badge(d.status) : ""}
				<button type="button" class="ua-btn ua-btn--primary" data-act="run-all"${busy}>${esc(__("Виконати все"))}</button>
				<button type="button" class="ua-btn ua-btn--danger-ghost" data-act="cancel-all"${busy}>${esc(__("Скасувати все"))}</button>
			</div>
		</div>`;
		if (d && d.edit_lock_date) {
			html += `<div class="ua-mc-lock">${esc(__("Дата заборони редагування"))}: ${esc(uk_date(d.edit_lock_date))}</div>`;
		}
		if (!d) {
			html += `<div class="ua-card ua-mc-card">${ui.skeleton_rows(6)}</div>`;
		} else {
			const last = last_done(d.steps);
			html += `<div class="ua-card ua-mc-card"><div class="ua-table-wrap"><table class="ua-table ua-mc-table"><thead><tr>
				<th class="ua-c">№</th><th>${esc(__("Операція"))}</th><th>${esc(__("Стан"))}</th><th>${esc(__("Документ"))}</th>
				<th>${esc(__("Результат"))}</th><th></th></tr></thead><tbody>`;
			d.steps.forEach((s, i) => {
				const can_cancel = s.status === DONE && i === last;
				const run_label = s.status === DONE ? __("Повторити") : __("Виконати");
				html += `<tr data-step="${esc(s.step)}"><td class="ua-c">${i + 1}</td><td>${esc(__(s.step_name))}</td>
					<td>${badge(s.status)}</td><td>${doc_link(s)}</td>
					<td class="ua-mc-msg" title="${esc(s.message)}">${esc(s.message)}</td>
					<td class="ua-mc-row-actions">
						<button type="button" class="ua-btn ua-btn--ghost ua-btn--sm" data-act="run" data-step="${esc(s.step)}"${busy}>${esc(run_label)}</button>
						${can_cancel ? `<button type="button" class="ua-btn ua-btn--danger-ghost ua-btn--sm" data-act="cancel" data-step="${esc(s.step)}"${busy}>${esc(__("Скасувати"))}</button>` : ""}
					</td></tr>`;
			});
			html += "</tbody></table></div></div>";
		}
		$root.html(html);
	};

	const call = (method, args) => {
		view.busy = true;
		render();
		return frappe
			.call({ method: API + method, args })
			.then((r) => {
				view.busy = false;
				view.data = Object.assign(r.message, { organization_title: view.data && view.data.organization_title });
				render();
			})
			.catch(() => {
				view.busy = false;
				load();
			});
	};

	const load = () => {
		if (!view.org) return render();
		view.data = null;
		render();
		frappe
			.call({ method: API + "open_closing", args: { organization: view.org, period: `${view.year}-${String(view.month).padStart(2, "0")}-01` } })
			.then((r) => {
				view.data = r.message;
				frappe.db.get_value("UA Organization", view.org, "org_name").then((v) => {
					view.data.organization_title = (v.message && v.message.org_name) || view.org;
					render();
				});
				render();
			});
	};

	$root.off(".mc");
	$root.on("change.mc", ".ua-mc-month, .ua-mc-year", () => {
		view.month = +$root.find(".ua-mc-month").val();
		view.year = +$root.find(".ua-mc-year").val();
		load();
	});
	$root.on("click.mc", "[data-act]", function () {
		if (view.busy || !view.data) return;
		const act = this.dataset.act;
		const name = view.data.name;
		if (act === "run-all") call("run_all", { name });
		else if (act === "run") call("run_step", { name, step: this.dataset.step });
		else if (act === "cancel") call("cancel_step", { name, step: this.dataset.step });
		else if (act === "cancel-all") {
			frappe.confirm(__("Скасувати всі виконані операції закриття місяця?"), () => call("cancel_all", { name }));
		}
	});
	load();
};
