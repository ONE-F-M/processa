# Copyright (c) 2026, one-fm and contributors
"""Docu's DocType tools, read_doctype_definition, keep_unrequested_fields and timed move into 'Docu: Lib Schema'.

The library is updated from its data file, and each Docu script that imports one of these names loads it from the
library instead. A site without the Docu map is left alone, and a second run changes nothing.
"""

from processa.patches.v1_0 import docu_helpers_move_to_library

MOVED = (
	"doctype_exists",
	"list_doctypes",
	"list_roles",
	"get_doctype_definition",
	"get_doctype_fields",
	"read_doctype_definition",
	"keep_unrequested_fields",
	"timed",
)


def execute():
	docu_helpers_move_to_library.execute(MOVED)
