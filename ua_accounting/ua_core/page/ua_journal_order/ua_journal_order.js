frappe.pages["ua-journal-order"].on_page_load = function (wrapper) {
	ua_accounting.reports.open_more(wrapper, "journal_order");
};
