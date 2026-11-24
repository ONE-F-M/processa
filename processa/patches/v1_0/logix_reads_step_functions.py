# Copyright (c) 2026, one-fm and contributors
"""Logix sees the functions inside the steps of a map and can copy one into the open script.

Build Context keeps the turn's step_functions, write_script lists them with their code,
and clarify names them so it does not say it cannot see them.
"""

import frappe

MODEL_NAME = "Logix \u2013 Script Task Agent"
BUILD_CONTEXT = "Logix \u2013 Build Context"
TURN_ANCHOR = '    "library_scripts": task_data.get("library_scripts") or [],\n'
TURN_LINE = '    "step_functions": task_data.get("step_functions") or [],\n'
WRITER_ANCHOR = "{% if turn.violations %}"
WRITER_BLOCK = (
	"{% if turn.step_functions %}**FUNCTIONS INSIDE STEPS ON THIS MAP** (a step runs its own code when the "
	"flow reaches it, so import_script cannot load these). When the person asks to use one: if the open "
	"script is one of the library scripts above, copy the function in as written. Otherwise copy it into the "
	"open script as written, and say in one sentence that a library would share it instead: add a script "
	"task with no arrows, open it in Logix and ask to move the function there, then import it.&#10;"
	"{% for s in turn.step_functions %}- step {{ s.step }} (script {{ s.script }}): "
	"{{ s.functions | join(', ') }}&#10;```python&#10;{{ s.code }}&#10;```&#10;{% endfor %}&#10;{% endif %}"
)
CLARIFY_ANCHOR = "User request: {{ user_request }}"
CLARIFY_BLOCK = (
	"{% set sf = get_turn(instance.context_docname).step_functions %}{% if sf %}Functions inside steps on "
	"this map (Logix can read them and copy one into this script): {% for s in sf %}"
	"{{ s.functions | join(', ') }} in step {{ s.step }}{% if not loop.last %}; {% endif %}{% endfor %}&#10;"
	"{% endif %}"
)


def execute():
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
	if code and build_context(code) != code:
		frappe.db.set_value(
			"Server Script", BUILD_CONTEXT, "script", build_context(code), update_modified=False
		)
	elif code and TURN_LINE not in code:
		frappe.log_error(title="logix_reads_step_functions: anchor not found", message=BUILD_CONTEXT)
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	new = prompts(xml)
	if xml and new.count("step_functions") < 2:
		frappe.log_error(title="logix_reads_step_functions: anchor not found", message=MODEL_NAME)
	if new != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", new)
		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)


def build_context(code: str) -> str:
	"""Build Context with step_functions kept in the turn, or the input when done or the anchor is missing."""
	if TURN_LINE in code or code.count(TURN_ANCHOR) != 1:
		return code
	return code.replace(TURN_ANCHOR, TURN_ANCHOR + TURN_LINE)


def prompts(xml: str) -> str:
	"""The map with the step functions in the write_script and clarify prompts; each is added once."""
	xml = _insert(xml, "write_script", WRITER_ANCHOR, WRITER_BLOCK)
	return _insert(xml, "clarify", CLARIFY_ANCHOR, CLARIFY_BLOCK)


def _insert(xml: str, task_id: str, anchor: str, block: str) -> str:
	start = xml.find(f'<bpmn:serviceTask id="{task_id}"')
	end = xml.find("</bpmn:serviceTask>", start)
	at = xml.find(anchor, start)
	if start < 0 or at < 0 or at > end or "step_functions" in xml[start:end]:
		return xml
	return xml[:at] + block + xml[at:]
