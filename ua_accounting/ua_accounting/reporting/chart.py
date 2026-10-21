"""Chart of accounts in memory. About 300 rows: one small load per request."""

import frappe
from frappe import _

ACCOUNT_FIELDS = [
    "name",
    "account_code",
    "account_name",
    "parent_ua_account",
    "is_group",
    "account_type",
    "off_balance",
    "currency_accounting",
    "quantity_accounting",
]


class Chart:
    def __init__(self):
        self.accounts = {}
        self.children = {}
        self.types = {}
        self._depth = {}

        for t in frappe.get_all(
            "UA Subconto Type",
            fields=["name", "subconto_name", "reference_doctype", "is_dynamic"],
            limit_page_length=0,
        ):
            self.types[t.name] = t

        rows = frappe.get_all(
            "UA Account",
            fields=ACCOUNT_FIELDS,
            order_by="account_code asc",
            limit_page_length=0,
        )
        for r in rows:
            r.subs = []
            self.accounts[r.name] = r
            self.children.setdefault(r.parent_ua_account or "", []).append(r.name)

        subs = frappe.db.sql(
            """select parent, subconto_type, turnover_only, quantity, currency
            from `tabUA Account Subconto`
            where parenttype = 'UA Account'
            order by parent, idx""",
            as_dict=True,
        )
        for s in subs:
            acc = self.accounts.get(s.parent)
            if acc is not None:
                acc.subs.append(s)

    # ------------------------------------------------------------ lookups

    def get(self, name):
        acc = self.accounts.get(name)
        if acc is None:
            frappe.throw(_("Рахунок {0} не знайдено").format(name))
        return acc

    def label(self, name):
        acc = self.get(name)
        return f"{acc.account_code} {acc.account_name}"

    def depth(self, name):
        """0 for a class (root), 1 for a synthetic account, 2 for a sub-account."""
        if name not in self._depth:
            parent = self.get(name).parent_ua_account
            self._depth[name] = 0 if not parent else self.depth(parent) + 1
        return self._depth[name]

    def ancestors(self, name):
        out = []
        parent = self.get(name).parent_ua_account
        while parent:
            out.append(parent)
            parent = self.get(parent).parent_ua_account
        return out

    def type_index(self, account, subconto_type):
        """0-based slot of a subconto type in the account, or None."""
        for i, s in enumerate(self.get(account).subs):
            if s.subconto_type == subconto_type:
                return i
        return None

    def type_title(self, subconto_type):
        t = self.types.get(subconto_type)
        return (t.subconto_name if t else None) or subconto_type

    # ------------------------------------------------------------ expansion

    def leaves_of(self, name):
        acc = self.get(name)
        if not acc.is_group:
            return [name]
        out = []
        for child in self.children.get(name, []):
            out.extend(self.leaves_of(child))
        return out

    def all_leaves(self):
        out = []
        for root in self.children.get("", []):
            out.extend(self.leaves_of(root))
        return out

    def expand(self, names):
        """Leaf accounts under the given accounts (groups are opened), no duplicates."""
        seen = set()
        out = []
        for name in names:
            for leaf in self.leaves_of(name):
                if leaf not in seen:
                    seen.add(leaf)
                    out.append(leaf)
        return out

    def top_level(self, names):
        """Drop the accounts that already have an ancestor in the list."""
        chosen = set(names)
        return [n for n in names if not any(a in chosen for a in self.ancestors(n))]
