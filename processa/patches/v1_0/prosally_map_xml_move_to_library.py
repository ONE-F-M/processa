# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly Libraries box gets 'ProsAlly: Lib Map XML', and the scripts load the map XML helpers from it.

The four tasks that import them, and the library task, get an Approved request shipped by the patch, because the
helpers use xml.etree, which the scripts already reach through the backend. A second run changes nothing.
"""

from processa.patches.v1_0 import prosally_replies_move_to_library

LIBRARY = "ProsAlly: Lib Map XML"
LOAD = f'_xml_lib = import_script("{LIBRARY}")'
MOVED = (
	"lint_findings",
	"overwrite_warning",
	"compare_output",
	"none_tasks_output",
	"xml_to_ir",
	"find_missing_target",
	"resolve_scope",
	"resolve_step",
	"describe_task_config",
	"validate_bpmn_xml",
	"transfer_properties",
	"describe_flow_references",
	"describe_links",
	"keep_process_kind",
	"convert_step_to_subprocess",
	"restore_call_activities",
	"splice_subprocess",
	"stage_system_prompt",
	"take_out_libraries",
	"put_back_libraries",
)
APPROVED_TASKS = ("classify_intent", "confirm", "generate_process", "modify_process", "lib_map_xml")
REASON = "ProsAlly map XML helpers moved into the map's library."


def execute():
	prosally_replies_move_to_library.execute(
		LIBRARY, "prosally_lib_map_xml.py", MOVED, LOAD, APPROVED_TASKS, REASON
	)
