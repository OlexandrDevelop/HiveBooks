"""The SQL of the app runs on MariaDB and on PostgreSQL: no MariaDB-only functions in the code."""

import ast
import re
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

# MariaDB-only forms. PostgreSQL has no IFNULL, IF(), REGEXP, DATE_FORMAT, YEAR(), CAST AS UNSIGNED,
# INSERT IGNORE, ON DUPLICATE KEY, and it refuses FOR UPDATE on an aggregate.
FORBIDDEN = re.compile(
    r"\b(ifnull|date_format|group_concat|str_to_date|year|month|if)\s*\(\s*[\w`.'%]+\s*(,|[=<>!])"
    r"|\bregexp\b|\bas\s+unsigned\b|\bon\s+duplicate\s+key\b|\binsert\s+ignore\b"
    r"|\bselect\s+[^;]*\b(sum|max|min|count|avg)\s*\([^;]*\bfor\s+update\b",
    re.IGNORECASE | re.DOTALL,
)
SQL_WORDS = re.compile(r"\b(select|update|insert|delete)\b", re.IGNORECASE)


def _docstrings(tree) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


class TestDialectSql(IntegrationTestCase):
    def test_no_mariadb_only_sql(self):
        root = Path(frappe.get_app_path("ua_accounting"))
        problems = []
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            skip = _docstrings(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr):
                    # an f-string is one query: its constant parts, the expressions as a placeholder
                    text = "".join(p.value if isinstance(p, ast.Constant) else "{}" for p in node.values)
                    skip.update(id(p) for p in node.values)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    text = node.value
                else:
                    continue
                if id(node) in skip:
                    continue
                if SQL_WORDS.search(text) and FORBIDDEN.search(text):
                    problems.append(f"{path.relative_to(root)}:{node.lineno}: {text[:70]!r}")
        self.assertEqual(problems, [])
