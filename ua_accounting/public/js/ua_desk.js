// Shared client base of the accounting app.
// Later tasks (documents, reports) reuse the namespace ua_accounting.ui.
frappe.provide("ua_accounting.ui");

// DocType -> parent field of the tree. Add a catalog here to get the group tree in its list.
ua_accounting.ui.TREE_DOCTYPES = {
	"UA Counterparty": "parent_ua_counterparty",
	"UA Item": "parent_ua_item",
	"UA Cash Flow Item": "parent_ua_cash_flow_item",
	"UA Department": "parent_ua_department",
};

// Frappe v16 selectors the app depends on. Checked in the dev stack. CSS files use the same names.
ua_accounting.ui.SEL = {
	nav_sidebar: ".body-sidebar-container", // the standard left sidebar (hidden in the shell)
	dock: "#desk-dock",
	main: ".main-section",
	page_head: ".page-head",
	page_actions: ".page-head .standard-actions",
	list_result: ".layout-main",
};

// Pages that have the slug of a DocType (the DocType route would win): the page route is used.
ua_accounting.ui.PAGE_ROUTES = ["ua-month-closing"];
if (frappe.router && frappe.router.setup) {
	const setup_routes = frappe.router.setup;
	frappe.router.setup = function () {
		setup_routes.apply(this, arguments);
		ua_accounting.ui.PAGE_ROUTES.forEach((route) => delete this.routes[route]);
	};
}

// Ledger doctypes are read-only registers; submittable doctypes are documents; the rest are catalogs.
ua_accounting.ui.REGISTERS = ["UA Accounting Entry", "UA Account Turnover", "UA VAT Liability Entry", "UA VAT Credit Entry"];

// Submittable documents (known before the meta is loaded, for list settings).
ua_accounting.ui.DOCUMENTS = [
	"UA Customer Order",
	"UA Sales Invoice",
	"UA Supplier Order",
	"UA Purchase Receipt",
	"UA Cash Receipt",
	"UA Cash Payment",
	"UA Payment Order",
	"UA Bank Statement",
	"UA Advance Report",
	"UA Cash Disbursement",
	"UA Currency Exchange",
	"UA Stock Transfer",
	"UA Stock Writeoff",
	"UA Stock Surplus",
	"UA Stock Inventory",
	"UA Stock Assembly",
	"UA Low Value Issue",
	"UA Special Wear Issue",
	"UA Special Wear Monthly Writeoff",
	"UA Special Wear Return",
	"UA Special Wear Writeoff",
	"UA Requirement Invoice",
	"UA Commission Receipt",
	"UA Commission Transfer",
	"UA Commission Agent Report",
	"UA Principal Report",
	"UA Commission Return",
	"UA Tolling Transfer",
	"UA Tolling Receipt",
	"UA Tolling Intake",
	"UA Tolling Output",
	"UA Packaging Return",
	"UA Journal Operation",
	"UA Dividend Accrual",
	"UA Tax Payment",
	"UA Loan Drawdown",
	"UA Loan Interest Accrual",
	"UA Loan Repayment",
	"UA Currency Revaluation",
	"UA Opening Balances",
];

ua_accounting.ui.is_ua_doctype = function (doctype) {
	return typeof doctype === "string" && doctype.startsWith("UA ");
};

// "register" | "document" | "catalog" | null (not a UA doctype or a child table)
ua_accounting.ui.kind = function (doctype) {
	if (!ua_accounting.ui.is_ua_doctype(doctype)) return null;
	if (ua_accounting.ui.REGISTERS.includes(doctype)) return "register";
	const meta = frappe.get_meta(doctype);
	if (!meta || meta.istable) return null;
	return meta.is_submittable ? "document" : "catalog";
};

// "361 Розрахунки з вітчизняними покупцями"
ua_accounting.ui.format_code_name = function (code, name) {
	return name ? `${code} ${name}` : code;
};

// Use in set_query: only accounts that can be posted to.
ua_accounting.ui.leaf_account_query = function () {
	return { filters: { is_group: 0 } };
};

ua_accounting.ui.is_ua_route = function (route) {
	// doctypes are named "UA ..."; report pages are named "ua-..."
	return (route || []).some(
		(part) => typeof part === "string" && (part.startsWith("UA ") || part.startsWith("ua-"))
	);
};

// Kind of the doctype in a Form or List route, for CSS (data-ua-kind).
ua_accounting.ui.route_kind = function (route) {
	if (route && (route[0] === "Form" || route[0] === "List" || route[0] === "Tree")) {
		return ua_accounting.ui.kind(route[1]) || "";
	}
	return "";
};

ua_accounting.ui.mark_body = function () {
	const route = frappe.get_route ? frappe.get_route() : [];
	const ua = ua_accounting.ui.is_ua_route(route) || (route && route[0] === "Workspaces" && route[1] === "Бухгалтерія");
	document.body.setAttribute("data-ua-kind", ua_accounting.ui.route_kind(route));
	document.body.setAttribute("data-ua-desk", ua ? "1" : "0");
};

$(document).on("startup", function () {
	frappe.router.on("change", ua_accounting.ui.mark_body);
	ua_accounting.ui.mark_body();
});

// Search and "frequently visited" show a route as text. Routes of the history are URL encoded
// ("UA%20Sales%20Invoice"), so the translation is not found and an English name is shown.
(function () {
	if (!frappe.utils || !frappe.utils.get_route_label) return;
	const original = frappe.utils.get_route_label;
	frappe.utils.get_route_label = function (route_str) {
		let decoded = route_str || "";
		try {
			decoded = decoded.split("/").map(decodeURIComponent).join("/");
		} catch (e) {
			// not encoded: keep it as it is
		}
		return original.call(this, decoded);
	};
})();

// The hint "Filtered by: ..." under the link search describes the technical filter of the field.
// It is noise for the user, so it is hidden for UA catalogs.
(function () {
	if (!frappe.ui.form || !frappe.ui.form.ControlLink) return;
	const proto = frappe.ui.form.ControlLink.prototype;
	const original = proto.get_filter_description;
	if (!original) return;
	proto.get_filter_description = function (filters) {
		if (ua_accounting.ui.is_ua_doctype(this.get_options())) return Promise.resolve("");
		return original.call(this, filters);
	};
})();

// Tree pages (route "<doctype>/view/tree"): a node shows the title only, not "(internal ID)",
// and the page title is the plain name of the catalog.
(function () {
	frappe.treeview_settings = frappe.treeview_settings || {};
	const doctypes = Object.keys(ua_accounting.ui.TREE_DOCTYPES).concat(["UA Account"]);
	doctypes.forEach((doctype) => {
		const settings = frappe.treeview_settings[doctype] || (frappe.treeview_settings[doctype] = {});
		settings.get_label = (node) =>
			frappe.utils.escape_html(node.label === doctype ? __(doctype) : node.title || node.label);
		Object.defineProperty(settings, "title", { enumerable: true, configurable: true, get: () => __(doctype) });
		const onload = settings.onload;
		settings.onload = function (treeview) {
			if (treeview && treeview.$search_input) treeview.$search_input.attr("placeholder", __("Пошук"));
			if (onload) onload.call(this, treeview);
		};
	});
})();

// Search of the top bar finds only what the accountant works with: the documents, catalogs and
// reports of the app (no calendar, activity log, OAuth and other system names).
$(document).on("startup", function () {
	const utils = frappe.search && frappe.search.utils;
	if (!utils || utils.ua_patched) return;
	utils.ua_patched = true;
	const keep_doctype = (name) =>
		ua_accounting.ui.is_ua_doctype(name) || ["User", "Role", "System Settings"].includes(name);
	const get_doctypes = utils.get_doctypes;
	utils.get_doctypes = function (keywords) {
		if (!ua_accounting.shell || !ua_accounting.shell.is_ua_user()) return get_doctypes.call(this, keywords);
		const boot = frappe.boot.user;
		const original = boot.can_read;
		boot.can_read = original.filter(keep_doctype);
		try {
			// "Report" results (standard report view) are not used in this app
			return get_doctypes.call(this, keywords).filter((r) => r.type !== "Report");
		} finally {
			boot.can_read = original;
		}
	};
	["get_reports", "get_workspaces", "get_dashboards", "get_executables"].forEach((name) => {
		const original = utils[name];
		if (!original) return;
		utils[name] = function (keywords) {
			if (!ua_accounting.shell || !ua_accounting.shell.is_ua_user()) return original.call(this, keywords);
			return [];
		};
	});
	const get_pages = utils.get_pages;
	utils.get_pages = function (keywords) {
		const out = get_pages.call(this, keywords);
		if (!ua_accounting.shell || !ua_accounting.shell.is_ua_user()) return out;
		return out.filter((r) => String((r.route && r.route[0]) || r.match || "").startsWith("ua-"));
	};
});

// Print preview: empty "Print Format" and "Letter Head" fields say what is used.
$(document).on("startup", function () {
	const fill = () => {
		$('input[data-fieldname="print_format"]:visible').attr("placeholder", __("Стандартний"));
		$('input[data-fieldname="letterhead"]:visible').attr("placeholder", __("Без фірмового бланка"));
	};
	frappe.router.on("change", () => [800, 2000].forEach((ms) => setTimeout(fill, ms)));
});

// Date picker (air-datepicker) has no Ukrainian locale in Frappe: without it the month names are English.
(function () {
	if (!$.fn.datepicker || !$.fn.datepicker.language || $.fn.datepicker.language.uk) return;
	$.fn.datepicker.language.uk = {
		days: ["Неділя", "Понеділок", "Вівторок", "Середа", "Четвер", "Пʼятниця", "Субота"],
		daysShort: ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
		daysMin: ["Нд", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
		months: ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"],
		monthsShort: ["Січ", "Лют", "Бер", "Кві", "Тра", "Чер", "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"],
		today: "Сьогодні",
		clear: "Очистити",
		dateFormat: "dd.mm.yyyy",
		timeFormat: "hh:ii",
		firstDay: 1,
	};
})();

// Link dropdown of UA catalogs: «Створити «текст»» and «Показати всі» (design/mockups/form-document.html).
// Frappe escapes the labels and descriptions of the found values; the typed text is escaped here (R4).
(function () {
	const Link = frappe.ui.form && frappe.ui.form.ControlLink;
	if (!Link || Link.prototype.ua_patched) return;
	Link.prototype.ua_patched = true;
	const original = Link.prototype.setup_awesomplete;
	Link.prototype.setup_awesomplete = function () {
		const out = original.apply(this, arguments);
		const me = this;
		const aw = this.awesomplete;
		if (!aw || !aw.item || !ua_accounting.ui.is_ua_doctype(this.get_options())) return out;
		const item = aw.item;
		aw.item = function (it) {
			const d = this.get_item ? this.get_item(it.value) : null;
			if (d && d.value === "create_new__link_option") {
				const txt = (me.get_input_value ? me.get_input_value() : "").trim();
				const label = txt ? __("Створити «{0}»", [frappe.utils.escape_html(txt)]) : __("Створити: {0}", [__(me.get_options())]);
				d.html = `<span class="link-option">${frappe.utils.icon("plus", "sm")} ${label}</span>`;
			} else if (d && d.value === "advanced_search__link_option") {
				d.html = `<span class="link-option">${frappe.utils.icon("search", "sm")} ${__("Показати всі")}</span>`;
			}
			return item.apply(this, arguments);
		};
		return out;
	};
})();
