# Copyright (c) 2026, one-fm and contributors
"""Logix's clarify step reads the workflow states from the turn and has room for its answer.

The clarify prompt cannot see workflow variables, so the states come from the turn that Build Context fills.
"""

import frappe

MODEL_NAME = "Logix \u2013 Script Task Agent"
BUILD_CONTEXT = "Logix \u2013 Build Context"
TURN_ANCHOR = '    "library_scripts": task_data.get("library_scripts") or [],\n'
TURN_LINE = '    "workflow_states": task_data.get("workflow_states") or [],\n'
OLD_BLOCK = (
	"{% if workflow_states %}Workflow states of this DocType: "
	"{{ workflow_states | join(&quot;, &quot;) }}&#10;{% endif %}"
)
NEW_BLOCK = (
	"{% set wf = get_turn(instance.context_docname).workflow_states %}{% if wf %}Workflow states of this "
	"DocType: {{ wf | join(&quot;, &quot;) }}&#10;{% endif %}"
)
OLD_TOKENS = 'spiffworkflow:aiMaxTokens="512"'
NEW_TOKENS = 'spiffworkflow:aiMaxTokens="1024"'


def execute():
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
	if code and build_context(code) != code:
		frappe.db.set_value(
			"Server Script", BUILD_CONTEXT, "script", build_context(code), update_modified=False
		)
	elif code and TURN_LINE not in code:
		frappe.log_error(
			title="logix_clarifier_reads_states_from_the_turn: anchor not found", message=BUILD_CONTEXT
		)
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if clarify(xml) != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", clarify(xml))
		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)


def build_context(code: str) -> str:
	"""Build Context that keeps workflow_states in the turn."""
	if TURN_LINE in code or code.count(TURN_ANCHOR) != 1:
		return code
	return code.replace(TURN_ANCHOR, TURN_ANCHOR + TURN_LINE)


def clarify(xml: str) -> str:
	"""The map whose clarify step reads the states from the turn and allows 1024 output tokens."""
	start = xml.find('<bpmn:serviceTask id="clarify"')
	end = xml.find("</bpmn:serviceTask>", start)
	if start < 0 or end < 0:
		return xml
	segment = xml[start:end].replace(OLD_BLOCK, NEW_BLOCK).replace(OLD_TOKENS, NEW_TOKENS)
	return xml[:start] + segment + xml[end:]
