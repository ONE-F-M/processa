# Copyright (c) 2026, one-fm and contributors
"""'ProsAlly: Lib Stage Replies' takes the lint and model call code it was missing.

The library was built before the backend learnt to refuse a lint fix it cannot make and to pass each stage's effort to
the model. A site without the library is left alone, and a second run changes nothing.
"""

import frappe

from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA

LIBRARY = "ProsAlly: Lib Stage Replies"


def execute():
	if not frappe.db.exists("Server Script", LIBRARY):
		return
	code = (DATA / "prosally_lib_stage_replies.py").read_text()
	if frappe.db.get_value("Server Script", LIBRARY, "script") != code:
		frappe.db.set_value("Server Script", LIBRARY, "script", code)
