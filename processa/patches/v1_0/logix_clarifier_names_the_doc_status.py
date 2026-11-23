# Copyright (c) 2026, one-fm and contributors
"""Logix's clarifier names the doc status of the workflow state a status change asks for.

Build Context passes the trigger DocType's workflow states on, the clarify prompt lists them, and the clarifier is told
to name the state with its doc status.
"""

import frappe

MODEL_NAME = "Logix \u2013 Script Task Agent"
BUILD_CONTEXT = "Logix \u2013 Build Context"
CLARIFIER_ID = "logix_clarifier"
KEYS_OLD = "for _k in ['element_name', 'current_script', 'original_script_content', 'process_context']:"
KEYS_NEW = "for _k in ['element_name', 'current_script', 'original_script_content', 'process_context', 'workflow_states']:"
PROMPT_ANCHOR = "User request: {{ user_request }}"
PROMPT_BLOCK = (
	"{% if workflow_states %}Workflow states of this DocType: "
	"{{ workflow_states | join(&quot;, &quot;) }}&#10;{% endif %}"
)
GUIDANCE_OLD = "Name the state they asked for."
GUIDANCE_NEW = (
	"Name the state they asked for and, from the workflow states listed with the request, its doc status."
)


def execute():
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
	if code and build_context(code) != code:
		frappe.db.set_value(
			"Server Script", BUILD_CONTEXT, "script", build_context(code), update_modified=False
		)
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if clarify_prompt(xml) != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", clarify_prompt(xml))
		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": CLARIFIER_ID}, "name")
	if name:
		config = frappe.get_doc("AI Agent Configuration", name)
		if GUIDANCE_NEW not in (config.system_prompt or ""):
			config.system_prompt = (config.system_prompt or "").replace(GUIDANCE_OLD, GUIDANCE_NEW)
			config.save(
				ignore_permissions=True
			)  # a patch runs as Administrator with no request user to check
	if code and KEYS_NEW not in build_context(code):
		frappe.log_error(
			title="logix_clarifier_names_the_doc_status: anchor not found", message=BUILD_CONTEXT
		)
	if xml and "workflow_states" not in clarify_prompt(xml):
		frappe.log_error(title="logix_clarifier_names_the_doc_status: anchor not found", message=MODEL_NAME)


def build_context(code: str) -> str:
	"""Build Context that passes workflow_states on as a workflow variable."""
	return code.replace(KEYS_OLD, KEYS_NEW) if KEYS_NEW not in code else code


def clarify_prompt(xml: str) -> str:
	"""The map with the workflow states listed in the clarify prompt, or the input when done or not possible."""
	start = xml.find('<bpmn:serviceTask id="clarify"')
	end = xml.find("</bpmn:serviceTask>", start)
	anchor = xml.find(PROMPT_ANCHOR, start)
	if start < 0 or anchor < 0 or anchor > end or "workflow_states" in xml[start:end]:
		return xml
	return xml[:anchor] + PROMPT_BLOCK + xml[anchor:]
