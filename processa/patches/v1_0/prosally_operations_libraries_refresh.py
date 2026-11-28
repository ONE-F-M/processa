# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's Lib IR, Lib Map XML, Lib Layout and Lib Replies take the retype, move and condition edits.

An edit keeps every shape it does not name where it was, and the reply lists the edits that were made. A site
without a library is left alone, and a second run changes nothing.
"""

import frappe

from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA

LIBRARIES = {
	"ProsAlly: Lib IR": "prosally_lib_ir.py",
	"ProsAlly: Lib Map XML": "prosally_lib_map_xml.py",
	"ProsAlly: Lib Layout": "prosally_lib_layout.py",
	"ProsAlly: Lib Replies": "prosally_lib_replies.py",
}


def execute():
	for library, data_file in LIBRARIES.items():
		if not frappe.db.exists("Server Script", library):
			continue
		code = (DATA / data_file).read_text()
		if frappe.db.get_value("Server Script", library, "script") != code:
			frappe.db.set_value("Server Script", library, "script", code)
