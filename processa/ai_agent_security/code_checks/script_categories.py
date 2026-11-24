"""Which Script Import Category a module, function or builtin a script uses belongs to."""

import ast

import frappe
from frappe.query_builder import DocType

UNLISTED = "Unlisted"
CACHE_KEY = "script_import_category_rows"

# Shapes the validator finds in code, which a Syntax row can name but not describe.
SYNTAX_CHECKS = frozenset(
	{
		"def",
		"lambda",
		"while",
		"class",
		"permission_kwarg",
		"session_write",
		"destructive_sql",
		"dunder_attribute",
		"dunder_subscript",
		"large_multiplication",
		"import_star",
	}
)


def category_for(name: str) -> str:
	"""The longest dotted prefix of name, then a Match On Any Object row for its last part, else Unlisted."""
	by_name, by_attribute, _categories, _syntax = _category_map()
	parts = name.split(".")
	for end in range(len(parts), 0, -1):
		category = by_name.get(".".join(parts[:end]))
		if category:
			return category
	return by_attribute.get(parts[-1], UNLISTED)


def attribute_category(attribute: str) -> str | None:
	"""The category of the Match On Any Object row for attribute, or None."""
	return _category_map()[1].get(attribute)


def needs_approval(category: str) -> bool:
	"""True unless category is Allowed by Default; Unlisted and unknown categories need approval."""
	return not _category_map()[2].get(category, {}).get("allowed_by_default")


def syntax_node_category(node_name: str) -> str | None:
	"""The category of the Syntax row that names this Python syntax node, such as Global or Try, or None."""
	return _category_map()[3].get(node_name)


def is_syntax_node(name: str) -> bool:
	"""True when name is a Python syntax node class, such as Global, Try or With."""
	node = getattr(ast, name, None)
	return isinstance(node, type) and issubclass(node, ast.AST)


def category_threshold(category: str) -> int:
	return _category_map()[2].get(category, {}).get("threshold") or 0


def clear_category_cache() -> None:
	frappe.cache.delete_value(CACHE_KEY)


def _category_map() -> tuple[dict, dict, dict, dict]:
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached
	row = DocType("Script Import Category Name")
	rows = (
		frappe.qb.from_(row)
		.select(row.parent, row.dotted_name, row.kind, row.match_on_any_object)
		.where(row.parenttype == "Script Import Category")
	).run(as_dict=True)
	by_name = {d.dotted_name: d.parent for d in rows if not d.match_on_any_object}
	by_attribute = {d.dotted_name.rsplit(".", 1)[-1]: d.parent for d in rows if d.match_on_any_object}
	by_syntax = {d.dotted_name: d.parent for d in rows if d.kind == "Syntax" and is_syntax_node(d.dotted_name)}
	category = DocType("Script Import Category")
	categories = {
		d.name: {"allowed_by_default": d.allowed_by_default, "threshold": d.threshold}
		for d in frappe.qb.from_(category)
		.select(category.name, category.allowed_by_default, category.threshold)
		.run(as_dict=True)
	}
	frappe.cache.set_value(CACHE_KEY, (by_name, by_attribute, categories, by_syntax))
	return by_name, by_attribute, categories, by_syntax
