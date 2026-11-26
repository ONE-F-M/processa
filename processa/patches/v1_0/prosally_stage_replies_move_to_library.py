# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly Libraries box gets 'ProsAlly: Lib Stage Replies', and the scripts load the stage reply helpers from it.

The library imports only platform functions, so each task that loads it, and the library task, gets an Approved
request shipped by the patch for what it uses through the library. A second run changes nothing.
"""

from processa.patches.v1_0 import prosally_replies_move_to_library

LIBRARY = "ProsAlly: Lib Stage Replies"
LOAD = f'_stage_lib = import_script("{LIBRARY}")'
MOVED = (
	"clarify_output",
	"no_stage_reply",
	"redirect_output",
	"diagnose_output",
	"answer_to_confirmation",
	"unapplied_proposal",
	"similar_steps",
)
APPROVED_TASKS = (
	"build_context",
	"classify_intent",
	"redirect",
	"clarify",
	"modify_process",
	"finalize",
	"lib_stage_replies",
)
REASON = "ProsAlly stage reply helpers moved into the map's library."


def execute():
	prosally_replies_move_to_library.execute(
		LIBRARY, "prosally_lib_stage_replies.py", MOVED, LOAD, APPROVED_TASKS, REASON
	)
