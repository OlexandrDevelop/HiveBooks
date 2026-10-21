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

ua_accounting.ui.mark_body = function () {
	const route = frappe.get_route ? frappe.get_route() : [];
	const ua = ua_accounting.ui.is_ua_route(route) || (route && route[0] === "Workspaces" && route[1] === "Бухгалтерія");
	document.body.setAttribute("data-ua-desk", ua ? "1" : "0");
};

$(document).on("startup", function () {
	frappe.router.on("change", ua_accounting.ui.mark_body);
	ua_accounting.ui.mark_body();
});
