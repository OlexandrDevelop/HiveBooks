"""Titles of linked values (a counterparty name instead of its id). One query per DocType."""

import frappe


class Titles:
    def __init__(self):
        self._cache = {}
        self._title_field = {}

    def _field(self, doctype):
        if doctype not in self._title_field:
            field = None
            if doctype and frappe.db.exists("DocType", doctype):
                meta = frappe.get_meta(doctype)
                if meta.title_field and meta.has_field(meta.title_field):
                    field = meta.title_field
            self._title_field[doctype] = field
        return self._title_field[doctype]

    def preload(self, pairs):
        """pairs: iterable of (doctype, name)."""
        wanted = {}
        for doctype, name in pairs:
            if name and (doctype, name) not in self._cache:
                wanted.setdefault(doctype, set()).add(name)
        for doctype, names in wanted.items():
            field = self._field(doctype)
            found = {}
            if field:
                rows = frappe.get_all(
                    doctype,
                    filters={"name": ("in", list(names))},
                    fields=["name", field],
                    limit_page_length=0,
                )
                found = {r.name: r[field] for r in rows}
            for name in names:
                self._cache[(doctype, name)] = found.get(name) or name

    def get(self, doctype, name):
        if not name:
            return ""
        key = (doctype, name)
        if key not in self._cache:
            self.preload([key])
        return self._cache[key]
