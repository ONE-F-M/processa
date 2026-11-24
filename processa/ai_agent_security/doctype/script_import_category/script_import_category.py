# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import builtins

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType

from processa.ai_agent_security.code_checks.script_categories import (
	SYNTAX_CHECKS,
	clear_category_cache,
	is_syntax_node,
)
from processa.ai_agent_security.code_checks.script_validator import INJECTED_NAMES

BUILTIN_NAMES = frozenset(dir(builtins)) | frozenset(INJECTED_NAMES)


class ScriptImportCategory(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from processa.ai_agent_security.doctype.script_import_category_name.script_import_category_name import (
			ScriptImportCategoryName,
		)

		allowed_by_default: DF.Check
		category_name: DF.Data
		description: DF.SmallText | None
		names: DF.Table[ScriptImportCategoryName]
		sanctioned_alternative: DF.SmallText | None
		threshold: DF.Int

	# end: auto-generated types
	def validate(self):
		for d in self.names:
			d.dotted_name = (d.dotted_name or "").strip()
			if d.kind == "Syntax" and d.dotted_name not in SYNTAX_CHECKS and not is_syntax_node(d.dotted_name):
				frappe.throw(
					_("Row {0}: {1} is not a shape check or a Python syntax node such as Global. Shape checks: {2}").format(
						d.idx, d.dotted_name, ", ".join(sorted(SYNTAX_CHECKS))
					)
				)
			if not all(part.isidentifier() for part in d.dotted_name.split(".")):
				frappe.throw(
					_("Row {0}: {1} is not a dotted name such as urllib.request").format(d.idx, d.dotted_name)
				)
			self.refuse_kind_mismatch(d)
		self.refuse_names_in_other_categories()

	def refuse_kind_mismatch(self, d):
		root = d.dotted_name.split(".")[0]
		if d.match_on_any_object and d.kind != "Frappe function":
			frappe.throw(
				_("Row {0}: Match On Any Object is only for Frappe function rows, such as db_set").format(
					d.idx
				)
			)
		if d.kind == "Builtin" and d.dotted_name not in BUILTIN_NAMES:
			frappe.throw(
				_("Row {0}: {1} is not a Python builtin or a name scripts get without importing").format(
					d.idx, d.dotted_name
				)
			)
		if d.kind == "Frappe function" and root != "frappe" and not d.match_on_any_object:
			frappe.throw(
				_(
					"Row {0}: {1} does not start with frappe. Tick Match On Any Object for a method name such as db_set"
				).format(d.idx, d.dotted_name)
			)
		if d.kind == "Module" and root == "frappe":
			frappe.throw(
				_("Row {0}: {1} is part of Frappe, so its kind is Frappe function").format(
					d.idx, d.dotted_name
				)
			)

	def refuse_names_in_other_categories(self):
		row = DocType("Script Import Category Name")
		taken = (
			frappe.qb.from_(row)
			.select(row.parent, row.dotted_name, row.kind)
			.where(row.parenttype == "Script Import Category")
			.where(row.parent != self.name)
			.where(row.dotted_name.isin([d.dotted_name for d in self.names] or [""]))
		).run(as_dict=True)
		owner = {t.dotted_name: t for t in taken}
		for d in self.names:
			other = owner.get(d.dotted_name)
			if other:
				frappe.throw(
					_("Row {0}: {1} ({2}) is already in category {3}, so it cannot also be in {4}").format(
						d.idx, d.dotted_name, other.kind, other.parent, self.name
					)
				)

	def on_update(self):
		clear_category_cache()

	def on_trash(self):
		clear_category_cache()
