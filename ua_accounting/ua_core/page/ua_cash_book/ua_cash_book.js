frappe.pages["ua-cash-book"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({parent: wrapper, title: "Касова книга", single_column: true});
	const $body = $(wrapper).find(".layout-main-section");
	$body.html(`<div class="ua-card"><h2>Касова книга</h2><p>Касові документи та підсумки за кожний день.</p>
		<button class="btn btn-primary">Відкрити звіт</button></div>`);
	$body.find("button").on("click", () => frappe.set_route("query-report", "UA Cash Book"));
};
