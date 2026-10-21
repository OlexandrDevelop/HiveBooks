// Group tree in the list sidebar for tree catalogs (like folders in 1C).
// A click filters the list by the group and all its descendants.
frappe.provide("ua_accounting.ui");

ua_accounting.ui.render_group_tree = function (listview, parent_field) {
	const doctype = listview.doctype;
	const title_field = frappe.get_meta(doctype).title_field || "name";
	const fields = Array.from(new Set(["name", title_field, parent_field]));

	frappe.db
		.get_list(doctype, { filters: { is_group: 1 }, fields: fields, limit: 0, order_by: `${title_field} asc` })
		.then((groups) => {
			const by_parent = {};
			groups.forEach((g) => {
				const key = g[parent_field] || "";
				(by_parent[key] = by_parent[key] || []).push(g);
			});

			const build = (parent) => {
				const items = by_parent[parent] || [];
				if (!items.length) return "";
				const li = items
					.map(
						(g) =>
							`<li><a data-group="${frappe.utils.escape_html(g.name)}">${frappe.utils.escape_html(
								g[title_field]
							)}</a>${build(g.name)}</li>`
					)
					.join("");
				return `<ul>${li}</ul>`;
			};

			const sidebar = listview.page.sidebar;
			sidebar.find(".ua-group-tree").remove();
			const $tree = $(
				`<div class="ua-group-tree"><div class="ua-tree-title">${__("Групи")}</div>` +
					`<ul><li><a data-group="">${__("Всі")}</a></li></ul>${build("")}</div>`
			);
			sidebar.prepend($tree);

			$tree.on("click", "a[data-group]", function () {
				const group = $(this).attr("data-group");
				$tree.find("a").removeClass("active");
				$(this).addClass("active");
				listview.filter_area.clear().then(() => {
					if (group) {
						return listview.filter_area.add([[doctype, parent_field, "descendants of (inclusive)", group]]);
					}
				});
			});
		});
};

// Register list view hooks. A doctype list script that sets frappe.listview_settings
// for the same doctype must call ua_accounting.ui.render_group_tree itself.
$.each(ua_accounting.ui.TREE_DOCTYPES, function (doctype, parent_field) {
	frappe.listview_settings[doctype] = Object.assign(frappe.listview_settings[doctype] || {}, {
		onload: function (listview) {
			ua_accounting.ui.render_group_tree(listview, parent_field);
		},
	});
});
