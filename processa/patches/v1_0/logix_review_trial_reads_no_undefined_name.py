"""Logix's review script stops reading _py_block on a site whose script never assigns it."""

import frappe

from processa.patches.v1_0.logix_review_passes_items_needing_approval import REVIEW_SCRIPT

UNDEFINED = "if _valid and _py_block and shape_kind"
DEFINED = "if _valid and shape_kind"


def execute():
	code = frappe.db.get_value("Server Script", REVIEW_SCRIPT, "script") or ""
	if UNDEFINED in code and "_py_block =" not in code:
		frappe.db.set_value(
			"Server Script", REVIEW_SCRIPT, "script", code.replace(UNDEFINED, DEFINED), update_modified=False
		)
