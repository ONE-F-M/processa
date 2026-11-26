# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly map gets 'ProsAlly: Lib Replies' in a Libraries box, and its scripts load the reply helpers from it.

Only the import lines and the calls to the moved functions change. The library needs no approval. A site without the
ProsAlly map is left alone, and a second run changes nothing.
"""

import frappe

from processa.patches.v1_0.docu_helpers_move_to_library import uses_library
from processa.patches.v1_0.logix_helpers_move_to_libraries import (
	DATA,
	_ensure_library,
	task_scripts,
	with_libraries_box,
)

MODEL_NAME = "ProsAlly \u2013 Process Modeller (1)"
LIBRARY = "ProsAlly: Lib Replies"
BOX_ID = "prosally_libraries"
TASK_IDS = {LIBRARY: "lib_replies", "ProsAlly: Lib IR": "lib_ir"}
LOAD = f'_replies = import_script("{LIBRARY}")'
MOVED = (
	"pending_confirmation",
	"add_document_sources",
	"asks_for_links_review",
	"lint_prompt",
	"no_lint_fix_reply",
	"lint_leftovers",
	"lint_unfixed_reply",
	"join_confirmation",
	"stage_max_tokens",
	"asks_to_make_call_activity",
	"crossing_line_note",
	"format_removal_warning",
	"constraint_prompt",
	"request_constraints",
	"unrequested_changes",
	"describe_changes",
	"layout_asks",
	"no_change_reply",
)


def execute(
	library: str = LIBRARY, data_file: str = "prosally_lib_replies.py", moved: tuple = MOVED, load: str = LOAD
):
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if xml is None:
		return
	_ensure_library(library, (DATA / data_file).read_text())
	task_ids = {library: TASK_IDS[library]}
	boxed = with_libraries_box(xml, BOX_ID, task_ids)
	if boxed != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", boxed)
	for task_id, name in task_scripts(boxed).items():
		if not name or task_id in TASK_IDS.values():
			continue
		script = frappe.db.get_value("Server Script", name, "script") or ""
		edited = uses_library(script, moved, load)
		if edited != script:
			frappe.db.set_value("Server Script", name, "script", edited)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)
