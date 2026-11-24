# Copyright (c) 2026, one-fm and contributors
"""The Dynamic code and reflection category lists import_star, which the validator no longer names itself."""

import frappe

CATEGORY = "Dynamic code and reflection"
ROW = {"dotted_name": "import_star", "kind": "Syntax"}


def execute():
	if not frappe.db.exists("Script Import Category", CATEGORY):
		return
	category = frappe.get_doc("Script Import Category", CATEGORY)
	if any(d.dotted_name == ROW["dotted_name"] for d in category.names):
		return
	category.append("names", ROW)
	category.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
