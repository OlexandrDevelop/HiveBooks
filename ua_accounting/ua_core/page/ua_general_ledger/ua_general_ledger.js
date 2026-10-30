frappe.pages["ua-general-ledger"].on_page_load = function (wrapper) {
	ua_accounting.reports.open_more(wrapper, "general_ledger");
};
