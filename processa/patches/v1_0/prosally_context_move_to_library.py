# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly Libraries box gets 'ProsAlly: Lib Context', and the scripts load the context helpers from it.

The library imports only platform functions, so each task that loads it, and the library task, gets an Approved
request shipped by the patch for what it uses through the library. A second run changes nothing.
"""

from processa.patches.v1_0 import prosally_replies_move_to_library

LIBRARY = "ProsAlly: Lib Context"
LOAD = f'_ctx_lib = import_script("{LIBRARY}")'
MOVED = (
	"complete_sub_prompt",
	"prosally_config",
	"queue_process_memory",
	"recall_process_memory",
	"links_review_output",
	"process_links_for_turn",
	"read_process_map_for_turn",
	"search_dms_for_turn",
	"describe_lanes",
	"lint_fix_requested",
)
APPROVED_TASKS = (
	"build_context",
	"classify_intent",
	"clarify",
	"confirm",
	"generate_process",
	"modify_process",
	"search_dms_documents",
	"get_process_links",
	"read_process_map",
	"save_response",
	"lib_context",
)
REASON = "ProsAlly context helpers moved into the map's library."


def execute():
	prosally_replies_move_to_library.execute(
		LIBRARY, "prosally_lib_context.py", MOVED, LOAD, APPROVED_TASKS, REASON
	)
