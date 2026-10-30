frappe.pages["ua-accounting-check"].on_page_load = function (wrapper) {
	ua_accounting.reports.open_more(wrapper, "accounting_check");
};
