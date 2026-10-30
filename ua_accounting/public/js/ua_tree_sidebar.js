// Folder tree of tree catalogs (design/mockups/catalog-items.html): a card left of the list with
// the groups and the number of elements in each group (with its sub-groups). A click filters the
// list by the group and its descendants; the path of the group is shown above the table.
// Used by ua_list.js (L.set_mode "tree") for the doctypes of ua_accounting.ui.TREE_DOCTYPES.
frappe.provide("ua_accounting.ui");

ua_accounting.ui.render_group_tree = function (listview, parent_field) {
	const doctype = listview.doctype;
	const title_field = frappe.get_meta(doctype).title_field || "name";
	const esc = frappe.utils.escape_html;
	const icon = (n, c) => ua_accounting.ui.icon(n, c);
	const $list = listview.$page.find(".frappe-list").first();

	// the list card and the tree card share one grid
	let $grid = listview.$page.find(".ua-cat-grid");
	if (!$grid.length) {
		$grid = $('<div class="ua-cat-grid"></div>').insertBefore($list);
		$grid.append($list);
	}
	let $card = $grid.find(".ua-tree-card");
	if (!$card.length) {
		$card = $(
			`<section class="ua-card ua-tree-card" aria-labelledby="ua-tree-title">
				<div class="ua-tree-head"><h2 class="ua-card-title" id="ua-tree-title">${esc(__("Групи"))}</h2>
					<div class="ua-right">
						<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-tree="collapse" aria-label="${esc(
							__("Згорнути все")
						)}" data-ua-tip="${esc(__("Згорнути все"))}">${icon("chev-u")}</button>
						${
							listview.can_create
								? `<button type="button" class="ua-btn ua-btn--ghost ua-btn--icon ua-btn--sm" data-tree="new" aria-label="${esc(
										__("Створити групу")
								  )}" data-ua-tip="${esc(__("Створити групу"))}">${icon("folder-plus")}</button>`
								: ""
						}
					</div>
				</div>
				<nav class="ua-tree" role="tree" aria-label="${esc(__("Групи"))}">${ua_accounting.ui.skeleton_rows(8, [70])}</nav>
			</section>`
		);
		$grid.prepend($card);
	}
	if (!$list.find(".ua-fpath").length) {
		$list.prepend(`<div class="ua-items-head"><nav class="ua-fpath" aria-label="${esc(__("Шлях до групи"))}"></nav></div>`);
	}

	const load = Promise.all([
		frappe.db.get_list(doctype, {
			filters: { is_group: 1 },
			fields: ["name", title_field, parent_field],
			limit: 0,
			order_by: `${title_field} asc`,
		}),
		frappe
			.xcall("frappe.client.get_list", {
				doctype,
				fields: [parent_field, { COUNT: "name", as: "n" }],
				filters: { is_group: 0 },
				group_by: parent_field,
				limit_page_length: 0,
			})
			.catch(() => []),
	]);

	load.then(([groups, counts]) => {
		const by_parent = {};
		const own = {};
		(counts || []).forEach((c) => (own[c[parent_field] || ""] = c.n || 0));
		groups.forEach((g) => (by_parent[g[parent_field] || ""] = by_parent[g[parent_field] || ""] || []).push(g));
		const total_of = {};
		const sum = (name) => {
			if (total_of[name] !== undefined) return total_of[name];
			let n = own[name] || 0;
			(by_parent[name] || []).forEach((g) => (n += sum(g.name)));
			return (total_of[name] = n);
		};
		const all = Object.values(own).reduce((a, b) => a + b, 0);
		const titles = {};
		groups.forEach((g) => (titles[g.name] = g[title_field] || g.name));
		const parents = {};
		groups.forEach((g) => (parents[g.name] = g[parent_field] || ""));
		const sel = ua_accounting.ui.current_group || "";
		// the selected group and its parents stay open
		const open = new Set(listview.ua_open || []);
		let p = sel;
		while (p) {
			open.add(p);
			p = parents[p];
		}
		const count = (n) => format_number(n, null, 0);

		const level = (parent, lvl) => {
			const items = by_parent[parent] || [];
			if (!items.length) return "";
			return (
				'<ul role="group">' +
				items
					.map((g) => {
						const kids = by_parent[g.name] && by_parent[g.name].length;
						const is_open = kids && open.has(g.name);
						const is_sel = g.name === sel;
						return (
							`<li role="treeitem" aria-expanded="${kids ? !!is_open : ""}" aria-selected="${is_sel}">` +
							`<button type="button" class="ua-tnode${is_open ? " is-open" : ""}${is_sel ? " is-sel" : ""}" style="--ua-lvl:${lvl}" data-node="${esc(
								g.name
							)}">` +
							`<span class="ua-tw${kids ? "" : " leaf"}" data-tw="${esc(g.name)}">${icon("chev-r")}</span>` +
							icon(is_sel || is_open ? "folder-open" : "folder", "ua-fic") +
							`<span class="ua-tl">${esc(titles[g.name])}</span><span class="ua-tc">${count(sum(g.name))}</span></button>` +
							(kids ? `<div class="ua-tkids${is_open ? " is-open" : ""}">${level(g.name, lvl + 1)}</div>` : "") +
							"</li>"
						);
					})
					.join("") +
				"</ul>"
			);
		};
		const root =
			'<ul role="group"><li role="treeitem" aria-expanded="true" aria-selected="' +
			!sel +
			'">' +
			`<button type="button" class="ua-tnode is-open${sel ? "" : " is-sel"}" style="--ua-lvl:0" data-node="">` +
			`<span class="ua-tw leaf"></span>${icon("folder-open", "ua-fic")}<span class="ua-tl">${esc(__("Усі"))}</span>` +
			`<span class="ua-tc">${count(all)}</span></button></li></ul>`;
		$card.find(".ua-tree").html(root + level("", 0));

		// path above the table
		const path = [];
		p = sel;
		while (p) {
			path.unshift(p);
			p = parents[p];
		}
		$list
			.find(".ua-fpath")
			.html(
				`<a href="#" data-node="">${esc(__(doctype))}</a>` +
					path
						.map((n, i) =>
							icon("chev-r") + (i === path.length - 1 ? `<b>${esc(titles[n])}</b>` : `<a href="#" data-node="${esc(n)}">${esc(titles[n])}</a>`)
						)
						.join("")
			);
		ua_accounting.ui.current_group_title = sel ? titles[sel] : "";
	});

	const select = (group) => {
		ua_accounting.ui.current_group = group;
		listview.ua_open = Array.from(new Set((listview.ua_open || []).concat(group ? [group] : [])));
		const f = group ? [doctype, parent_field, "descendants of (inclusive)", group] : null;
		ua_accounting.list.set_filter(listview, parent_field, f).then(() => ua_accounting.ui.render_group_tree(listview, parent_field));
	};

	$card.off("click.ua").on("click.ua", "[data-tw]", function (e) {
		e.stopPropagation();
		const $node = $(this).closest(".ua-tnode");
		const $kids = $node.next(".ua-tkids");
		if (!$kids.length) return;
		const name = $(this).attr("data-tw");
		const is_open = !$node.hasClass("is-open");
		$node.toggleClass("is-open", is_open).closest("li").attr("aria-expanded", is_open);
		$kids.toggleClass("is-open", is_open);
		const set = new Set(listview.ua_open || []);
		if (is_open) set.add(name);
		else set.delete(name);
		listview.ua_open = Array.from(set);
	});
	$card.on("click.ua", ".ua-tnode", function () {
		select($(this).attr("data-node") || "");
	});
	$card.on("click.ua", "[data-tree]", function () {
		if ($(this).attr("data-tree") === "new") ua_accounting.list.new_group(listview, parent_field);
		else {
			listview.ua_open = [];
			$card.find(".ua-tnode").removeClass("is-open");
			$card.find(".ua-tkids").removeClass("is-open");
		}
	});
	$list.off("click.ua_path").on("click.ua_path", ".ua-fpath [data-node]", function (e) {
		e.preventDefault();
		select($(this).attr("data-node") || "");
	});
};
