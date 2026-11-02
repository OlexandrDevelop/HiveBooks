// The accounting app on the beeone shell: organization chip, form titles, favourites.
// The shell itself (rail, windows, widgets, UI kit) is in the beeone core (beeone.shell, beeone.ui).
frappe.provide("ua_accounting.ui");
frappe.provide("ua_accounting.shell");

(function () {
	const UA_ROLES = ["UA Accountant", "UA Accounting Manager", "System Manager"];
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const shell = ua_accounting.shell;

	// the former home pages open the desktop
	if (window.beeone && beeone.shell && beeone.shell.desktop_routes) beeone.shell.desktop_routes.push("ua-home");

	shell.is_ua_user = () => UA_ROLES.some((r) => frappe.user.has_role(r));

	shell.initials = function (name) {
		return (
			String(name || "")
				.split(/\s+/)
				.filter(Boolean)
				.slice(0, 2)
				.map((w) => w[0])
				.join("")
				.toUpperCase() || "—"
		);
	};

	// documents show their number; catalogs show their title (never the hash name)
	shell.doc_title = function (frm) {
		const meta = frappe.get_meta(frm.doctype);
		if (meta && meta.is_submittable) return frm.doc.name;
		if (meta && meta.issingle) return __(frm.doctype);
		const tf = meta && meta.title_field;
		return (tf && frm.doc[tf]) || frm.doc.name;
	};

	// ---------------------------------------------------------------- favourites (kept per user on the server)
	// entry: {key: "route:Form/DocType/name", route, label}
	shell.is_fav = (key) => beeone.shell.is_fav(String(key).replace(/^route:/, ""));
	shell.toggle_fav = function (entry) {
		const on = beeone.shell.toggle_fav({ route: entry.route, label: entry.label });
		beeone.ui.toast({
			title: on ? __("Додано в Обране") : __("Прибрано з Обраного"),
			text: entry.label,
			type: "info",
			duration: 2600,
		});
		return on;
	};

	// ---------------------------------------------------------------- organizations (the chip of the top bar)
	shell.orgs = [];
	const store_key = () => `ua_shell:${frappe.session.user}:org`;

	shell.current_org = function () {
		let id = null;
		try {
			id = localStorage.getItem(store_key());
		} catch (e) {
			id = null;
		}
		const orgs = shell.orgs;
		return orgs.find((o) => o.name === id) || orgs.find((o) => o.edrpou) || orgs[0] || null;
	};

	shell.org_mark = function (title) {
		const words = String(title || "")
			.replace(/[«»"']/g, "")
			.split(/\s+/)
			.filter((w) => w && !["ТОВ", "ПП", "ФОП", "ПрАТ", "АТ"].includes(w));
		return (words.slice(0, 2).map((w) => w[0]).join("") || "—").toUpperCase();
	};

	const meta_line = (o) => (o.edrpou ? `${__("ЄДРПОУ")} ${o.edrpou}` : __("ЄДРПОУ не вказано"));

	shell.render_org = function () {
		if (!beeone.shell.add_context_chip) return;
		beeone.shell.add_context_chip({
			id: "ua-org",
			render: () => {
				const org = shell.current_org();
				if (!org) return "";
				return `<span class="bo-chip-mark">${esc(shell.org_mark(org.org_name))}</span><span class="bo-chip-text">${esc(
					org.org_name
				)}<small>${esc(meta_line(org))}</small></span>${beeone.ui.icon("chev-d", "bo-i-sm")}`;
			},
			menu: shell.org_menu,
		});
	};

	shell.org_menu = function (trigger) {
		const current = shell.current_org();
		const items = shell.orgs
			.map(
				(o) =>
					`<button class="bo-menu-item${current && o.name === current.name ? " is-active" : ""}" data-org="${esc(o.name)}">` +
					`<span class="bo-chip-mark">${esc(shell.org_mark(o.org_name))}</span>` +
					`<span class="bo-two"><span>${esc(o.org_name)}</span><small>${esc(meta_line(o))}</small></span>` +
					`${current && o.name === current.name ? beeone.ui.icon("check", "bo-i-sm") : ""}</button>`
			)
			.join("");
		beeone.ui.menu(
			trigger,
			`<div class="bo-menu-label">${esc(__("Організація"))}</div>${items}`,
			(item) => {
				const id = item.getAttribute("data-org");
				if (!id) return;
				try {
					localStorage.setItem(store_key(), id);
				} catch (e) {
					// blocked storage: the choice lasts until reload
				}
				shell.render_org();
				$(document).trigger("ua-org-changed");
			},
			{ cls: "bo-org-pop" }
		);
	};

	shell.load_orgs = function () {
		if (!frappe.model.can_read("UA Organization")) return Promise.resolve([]);
		return frappe.db
			.get_list("UA Organization", { fields: ["name", "org_name", "edrpou"], limit: 50, order_by: "org_name asc" })
			.then((rows) => {
				shell.orgs = rows || [];
				shell.render_org();
				$(document).trigger("ua-org-changed");
				return rows;
			})
			.catch(() => []);
	};

	// The accountant calendar: overdue, today and upcoming tasks of the working organization.
	shell.render_calendar = function (root, request) {
		const organization = shell.current_org();
		if (!organization) return;
		frappe
			.call({ method: "ua_accounting.api.calendar.get_home", args: { organization: organization.name }, silent: true })
			.then((r) => {
				const res = r.message;
				if (request !== home_request || !root.isConnected || !res) return;
				const task = (t, cls) =>
					`<div class="ua-home-task" data-task="${esc(t.name)}"><span class="ua-home-dot ua-home-dot--${cls}"></span><div>${esc(t.title)}<small>` +
					`${cls === "danger" ? `<b>${esc(__("Прострочено"))}</b> · ` : ""}${esc(__("Строк"))}: ${esc(frappe.datetime.str_to_user(t.due_date))}</small></div>` +
					`<button type="button" class="bo-btn bo-btn--sm" data-complete="${esc(t.name)}">${esc(__("Виконано"))}</button></div>`;
				const parts = [].concat(
					res.overdue.map((t) => task(t, "danger")),
					res.today.map((t) => task(t, "warning")),
					res.upcoming.map((t) => task(t, "info"))
				);
				const section = document.createElement("section");
				section.className = "ua-home-calendar";
				section.innerHTML =
					`<h2>${esc(__("Календар бухгалтера"))}</h2>` + (parts.length ? parts.join("") : `<p>${esc(__("Завдань немає"))}</p>`);
				section.addEventListener("click", (e) => {
					const done = e.target.closest("[data-complete]");
					if (done) frappe.xcall("ua_accounting.api.calendar.complete", { name: done.dataset.complete }).then(() => shell.render_home_summary());
				});
				root.prepend(section);
			})
			.catch(() => {});
	};

	// Keep the former /desk/ua-home bookmark useful inside the new desktop.
	// The balances are read through the application's permission-checked dashboard API.
	let home_request = 0;
	shell.render_home_summary = function () {
		const host = document.getElementById("bo-desk-bg");
		if (!host) return;
		const old = host.querySelector(".ua-home-summary");
		if (old) old.remove();
		const route = frappe.get_route() || [];
		const is_home = route[0] === "ua-home" || (route[0] === "desk" && route[1] === "ua-home");
		const is_desktop = !route[0] || route[0] === "beeone-desktop" || is_home;
		if (!is_desktop || !shell.is_ua_user()) return;
		const request = ++home_request;
		const root = document.createElement("div");
		root.className = "ua-home-summary";
		host.appendChild(root);
		shell.render_calendar(root, request);
		if (!is_home) return; // the desktop shows the calendar; the former home page also shows the summary
		root.innerHTML +=
			`<section role="region" aria-label="${esc(__("Швидке створення"))}" class="ua-home-summary-create"><h2>${esc(__("Швидке створення"))}</h2><div class="ua-home-summary-actions"></div></section>` +
			`<div class="ua-home-summary-cards"></div><section><h2>${esc(__("Останні документи"))}</h2></section>` +
			`<section><h2>${esc(__("Обране"))}</h2></section><section><h2>${esc(__("Нагадування"))}</h2></section>`;
		const actions = root.querySelector(".ua-home-summary-actions");
		for (const dt of ["UA Sales Invoice", "UA Purchase Receipt", "UA Cash Receipt", "UA Cash Payment"]) {
			if (!frappe.model.can_create(dt)) continue;
			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "bo-btn bo-btn--sm";
			btn.textContent = __(dt);
			btn.addEventListener("click", () => frappe.new_doc(dt));
			actions.appendChild(btn);
		}
		const organization = shell.current_org();
		frappe.xcall("ua_accounting.ua_core.page.ua_home.ua_home.get_dashboard", { organization: organization && organization.name })
			.then((data) => {
				if (request !== home_request || !root.isConnected || !data.cards) return;
				const cards = root.querySelector(".ua-home-summary-cards");
				const labels = [
					["bank", "Гроші на рахунках"], ["cash", "Готівка в касі"],
					["receivable", "Нам винні покупці"], ["payable", "Ми винні постачальникам"],
				];
				const number = new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
				cards.innerHTML = labels.map(([key, label]) =>
					`<div class="ua-home-summary-card"><span>${esc(__(label))}</span><strong>${esc(number.format(data.cards[key].balance))}</strong></div>`
				).join("");
			})
			.catch(() => {});
	};
	$(document).on("ua-org-changed", () => shell.render_home_summary());

	$(document).on("startup", function () {
		if (!shell.is_ua_user()) return;
		if (frappe.boot.sysdefaults && !frappe.boot.sysdefaults.setup_complete) return;
		shell.load_orgs();
		frappe.router.on("change", () => setTimeout(shell.render_home_summary, 0));
		setTimeout(shell.render_home_summary, 0);
	});
})();
