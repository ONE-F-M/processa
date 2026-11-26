# Copyright (c) 2026, one-fm and contributors
"""ProsAlly sets a map's Libraries box aside before it changes or regenerates the diagram, then puts it back below the flow.

Edits the Modify Process and Generate Process scripts in place. Text already carrying the change is skipped, and text
whose anchors are not each found exactly once is logged and left as it is. A site without the scripts is left alone.
"""

import frappe

from processa.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

MODIFY_SCRIPT = "ProsAlly \u2013 Tool Modify Process"
GENERATE_SCRIPT = "ProsAlly \u2013 Tool Generate Process"
MARKER = "put_back_libraries"
RELAYOUT_MARKER = 'output["bpmn_xml"] = put_back_libraries(output["bpmn_xml"], _libraries)'

MODIFY_EDITS = (
	(
		"restore_call_activities, splice_subprocess, unapplied_proposal\n",
		"restore_call_activities, splice_subprocess, unapplied_proposal, take_out_libraries, put_back_libraries\n",
	),
	(
		'current_xml = turn.get("current_xml", "")\n',
		'current_xml, _libraries = take_out_libraries(turn.get("current_xml", ""))\n',
	),
	('"pending_xml": merged_xml,', '"pending_xml": put_back_libraries(merged_xml, _libraries),'),
	(
		'output["bpmn_xml"] = merged_xml\n',
		'output["bpmn_xml"] = put_back_libraries(merged_xml, _libraries)\n',
	),
)
MODIFY_RELAYOUT_EDITS = (
	(
		"            output = relayout_output(current_xml, _layout_text)\n",
		"            output = relayout_output(current_xml, _layout_text)\n"
		'            if "bpmn_xml" in output:\n'
		'                output["bpmn_xml"] = put_back_libraries(output["bpmn_xml"], _libraries)\n',
	),
)
GENERATE_EDITS = (
	(
		"from processa.ai_agent_registry.definitions.prosally.validators import validate_bpmn_xml\n",
		"from processa.ai_agent_registry.definitions.prosally.validators import validate_bpmn_xml\n"
		"from processa.ai_agent_registry.definitions.prosally.tools_subprocess import put_back_libraries, take_out_libraries\n",
	),
	(
		'        "bpmn_xml": best_xml,\n',
		'        "bpmn_xml": put_back_libraries(best_xml, take_out_libraries(turn.get("current_xml", ""))[1]),\n',
	),
)


def execute():
	if frappe.db.exists("Server Script", MODIFY_SCRIPT):
		apply_edits("Server Script", MODIFY_SCRIPT, "script", MODIFY_EDITS, MARKER)
		script = frappe.db.get_value("Server Script", MODIFY_SCRIPT, "script") or ""
		# Only the newer Modify script handles a layout-only request; the older one has no such line.
		if MARKER in script and MODIFY_RELAYOUT_EDITS[0][0] in script:
			apply_edits("Server Script", MODIFY_SCRIPT, "script", MODIFY_RELAYOUT_EDITS, RELAYOUT_MARKER)
	if frappe.db.exists("Server Script", GENERATE_SCRIPT):
		apply_edits("Server Script", GENERATE_SCRIPT, "script", GENERATE_EDITS, MARKER)
