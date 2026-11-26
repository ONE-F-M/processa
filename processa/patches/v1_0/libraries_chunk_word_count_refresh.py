# Copyright (c) 2026, one-fm and contributors
"""The three libraries with document search take the fix that lets search_dms_documents split a document into chunks.

A site without one of the libraries is left alone, and a second run changes nothing.
"""

import frappe

from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA

LIBRARIES = {
	"LuCrusher: Lib DMS": "lucrusher_lib_dms.py",
	"ProsAlly: Lib Context": "prosally_lib_context.py",
	"ProsAlly: Lib Stage Replies": "prosally_lib_stage_replies.py",
}


def execute():
	for library, data_file in LIBRARIES.items():
		if not frappe.db.exists("Server Script", library):
			continue
		code = (DATA / data_file).read_text()
		if frappe.db.get_value("Server Script", library, "script") != code:
			frappe.db.set_value("Server Script", library, "script", code)
