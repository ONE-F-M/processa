# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly Libraries box gets 'ProsAlly: Lib IR', and the scripts load the IR helpers from it.

Only the import lines and the calls to the moved functions change. The library holds its own copy of extract_json and
format_history, because a library cannot import another script. A second run changes nothing.
"""

from processa.patches.v1_0 import prosally_replies_move_to_library

LIBRARY = "ProsAlly: Lib IR"
LOAD = f'_ir_lib = import_script("{LIBRARY}")'
MOVED = (
	"extract_json",
	"format_history",
	"auto_fix_ir",
	"chunk_exit_node_id",
	"ensure_default_lanes",
	"extract_process_name",
	"extract_element_ids",
	"merge_chunked_ir",
	"translate_problems",
	"translate_violations",
	"apply_operations",
)


def execute():
	prosally_replies_move_to_library.execute(LIBRARY, "prosally_lib_ir.py", MOVED, LOAD)
