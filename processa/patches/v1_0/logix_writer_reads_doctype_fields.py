"""Logix's script writer sees the fields of the DocTypes a request is about.

Build Context loads them with doctype_inputs and keeps them in the turn, its new import is approved on the map, and
the write_script prompt lists each DocType's fields. Each step runs once.
"""

import frappe

from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.patches.v1_0.approve_live_script_tasks import approve

MODEL_NAME = "Logix \u2013 Script Task Agent"
BUILD_CONTEXT = "Logix \u2013 Build Context"
TASK = "build_context"
IMPORT_OLD = "from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs\n"
IMPORT_NEW = "from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs, doctype_inputs\n"
SPREAD_OLD = (
	'    **debug_inputs(task_data.get("user_text"), task_data.get("original_script_content"), '
	'task_data.get("current_script")),\n'
)
SPREAD_NEW = SPREAD_OLD + (
	'    **doctype_inputs(task_data.get("user_text"), task_data.get("process_context"), '
	'task_data.get("current_script")),\n'
)
WRITER_ANCHOR = "{% if turn.violations %}"
WRITER_BLOCK = (
	"{% if turn.doctype_fields %}**Fields of the DocTypes this request is about. Read and write only these "
	"fields:**&#10;{% for dt, info in turn.doctype_fields.items() %}- {{ dt }}: "
	"{{ info.fields | join(&quot;, &quot;) }}&#10;{% endfor %}&#10;{% endif %}"
)


def execute():
	process = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "process_name")
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
	if not process or not code:
		return
	new = build_context(code)
	if "doctype_inputs" not in new:
		frappe.log_error(title="logix_writer_reads_doctype_fields: anchor not found", message=BUILD_CONTEXT)
		return
	if new != code:
		frappe.db.set_value("Server Script", BUILD_CONTEXT, "script", new, update_modified=False)
	if script_task_findings(new, process, TASK, BUILD_CONTEXT):
		approve(process, TASK, TASK, BUILD_CONTEXT)
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if writer_prompt(xml) != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", writer_prompt(xml))
		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)


def build_context(code: str) -> str:
	"""Build Context that loads the request's DocType fields into the turn."""
	if "doctype_inputs" in code or code.count(IMPORT_OLD) != 1 or code.count(SPREAD_OLD) != 1:
		return code
	return code.replace(IMPORT_OLD, IMPORT_NEW).replace(SPREAD_OLD, SPREAD_NEW)


def writer_prompt(xml: str) -> str:
	"""The map with the field list in write_script's prompt."""
	start = xml.find('<bpmn:serviceTask id="write_script"')
	end = xml.find("</bpmn:serviceTask>", start)
	anchor = xml.find(WRITER_ANCHOR, start)
	if start < 0 or anchor < 0 or anchor > end or "turn.doctype_fields" in xml[start:end]:
		return xml
	return xml[:anchor] + WRITER_BLOCK + xml[anchor:]
