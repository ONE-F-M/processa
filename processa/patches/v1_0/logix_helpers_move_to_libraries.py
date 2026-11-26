# Copyright (c) 2026, one-fm and contributors
"""The Logix map gets two library scripts in a Libraries box, and its scripts load the helpers from them.

'Logix: Lib Replies' needs no approval. 'Logix: Lib DocType Sources' reads files, so the library task and the two tasks
that load it get an Approved request shipped by this patch, as the live scripts already use those names through the
backend. A site without the Logix map is left alone, a script whose text has moved is logged and left as it is, and a
second run changes nothing.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

import frappe
from frappe.utils import now_datetime

from processa.ai_agent_registry.definitions.prosally.helpers import NS
from processa.ai_agent_registry.definitions.prosally.tools_subprocess import put_back_libraries
from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.ai_agent_security.code_checks.script_validator import NOT_APPROVABLE
from processa.patches.v1_0.prosally_scope_modify_to_subprocess import with_edits

MODEL_NAME = "Logix \u2013 Script Task Agent"
DATA = Path(__file__).parent / "data"
REPLIES = "Logix: Lib Replies"
SOURCES = "Logix: Lib DocType Sources"
LIBRARIES = {REPLIES: "logix_lib_replies.py", SOURCES: "logix_lib_doctype_sources.py"}
BOX_ID = "logix_libraries"
TASK_IDS = {REPLIES: "lib_replies", SOURCES: "lib_doctype_sources"}
# The library task is approved too: import_script checks a library against its own task when it loads it.
APPROVED_TASKS = ("review_script", "read_doctype_logic", TASK_IDS[SOURCES])
REASON = "Logix helpers moved into the map's libraries."

SCRIPT_EDITS = {
	"build_context": (
		(
			"from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs, doctype_inputs\n",
			f'_replies = import_script("{REPLIES}")\n',
		),
		("**debug_inputs(", "**_replies.debug_inputs("),
		("**doctype_inputs(", "**_replies.doctype_inputs("),
	),
	"finalize": (
		(
			"from processa.ai_agent_registry.definitions.logix.tools import reply_with_code, revert_output\n",
			"from processa.ai_agent_registry.definitions.logix.tools import revert_output\n"
			f'_replies = import_script("{REPLIES}")\n',
		),
		("final = reply_with_code(final, code)", "final = _replies.reply_with_code(final, code)"),
	),
	"review_script": (
		(
			"from processa.ai_agent_registry.definitions.logix.helpers import field_findings\n",
			f'_sources = import_script("{SOURCES}")\n',
		),
		("_checks + field_findings(code, turn)", "_checks + _sources.field_findings(code, turn)"),
	),
	"read_doctype_logic": (
		(
			"from processa.ai_agent_registry.definitions.lucrusher.tools import read_doctype_sources\n",
			f'_sources = import_script("{SOURCES}")\n',
		),
		("_logic = read_doctype_sources(_names, 40)", "_logic = _sources.read_doctype_sources(_names, 40)"),
	),
}


def execute():
	model = frappe.db.get_value("BPMN Process Model", MODEL_NAME, ["bpmn_xml", "process_name"], as_dict=True)
	if not model or not model.process_name:
		return
	for name, file_name in LIBRARIES.items():
		_ensure_library(name, (DATA / file_name).read_text())
	xml = with_libraries_box(model.bpmn_xml or "")
	if xml != model.bpmn_xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)
	scripts = task_scripts(xml)
	for task_id, edits in SCRIPT_EDITS.items():
		if scripts.get(task_id):
			_edit_script(scripts[task_id], edits)
	for task_id in APPROVED_TASKS:
		if scripts.get(task_id):
			_approve(model.process_name, task_id, scripts[task_id])
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def with_libraries_box(xml: str, box_id: str = BOX_ID, task_ids: dict | None = None) -> str:
	"""xml with a Libraries box holding a script task per library, drawn below the flow; unchanged when present."""
	task_ids = task_ids or TASK_IDS
	if f'id="{box_id}"' in xml or "<bpmn:process " not in xml:
		return xml
	process_id = xml.split("<bpmn:process ", 1)[1].split('id="', 1)[1].split('"', 1)[0]
	spiff = 'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"'
	bpmn = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
	tasks = "".join(
		f'<bpmn:scriptTask id="{task_ids[name]}" name="{name.split(": ", 1)[1]}" spiffworkflow:serverScript="{name}" '
		f'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{name}" />'
		for name in task_ids
	)
	element = (
		f'<bpmn:adHocSubProcess {bpmn} {spiff} id="{box_id}" name="Libraries" spiffworkflow:scriptLibrary="true">'
		f"{tasks}</bpmn:adHocSubProcess>"
	)
	di = 'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"'
	shapes = [
		f'<bpmndi:BPMNShape {di} id="{box_id}_di" bpmnElement="{box_id}" isExpanded="true">'
		'<dc:Bounds x="0" y="0" width="300" height="140" /></bpmndi:BPMNShape>'
	] + [
		f'<bpmndi:BPMNShape {di} id="{task_ids[name]}_di" bpmnElement="{task_ids[name]}">'
		f'<dc:Bounds x="{30 + 140 * index}" y="30" width="100" height="80" /></bpmndi:BPMNShape>'
		for index, name in enumerate(task_ids)
	]
	return put_back_libraries(xml, [{"process": process_id, "element": element, "shapes": shapes}])


def task_scripts(xml: str) -> dict:
	"""The Server Script name on each script task of the map, keyed by task id."""
	tasks = ET.fromstring(xml).iter("{" + NS["bpmn"] + "}scriptTask")
	return {task.get("id"): task.get("{" + NS["spiffworkflow"] + "}serverScript") for task in tasks}


def _ensure_library(name: str, code: str) -> None:
	if frappe.db.exists("Server Script", name):
		if frappe.db.get_value("Server Script", name, "script") != code:
			frappe.db.set_value("Server Script", name, "script", code)
		return
	frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": frappe.scrub(name).replace(":", ""),
			"script": code,
		}
	).insert(ignore_permissions=True)  # patch: library for the Logix map


def _edit_script(name: str, edits: tuple) -> None:
	script = frappe.db.get_value("Server Script", name, "script") or ""
	if edits[0][1] in script:
		return
	edited = with_edits(script, edits)
	if edited is None:
		frappe.log_error(
			title="logix_helpers_move_to_libraries: anchors not found",
			message=f"Server Script {name} does not carry each anchor exactly once; it is left as it is.",
		)
		return
	frappe.db.set_value("Server Script", name, "script", edited)


def _approve(process: str, task_id: str, server_script: str, reason: str = REASON) -> None:
	if frappe.db.exists(
		"Script Approval Request",
		{"process_name": process, "script_task": task_id, "source": "Shipped by patch", "reason": reason},
	):
		return
	code = frappe.db.get_value("Server Script", server_script, "script") or ""
	findings = script_task_findings(code, process, task_id, server_script)
	if all(f["category"] in NOT_APPROVABLE for f in findings):
		return
	request = frappe.get_doc(
		{
			"doctype": "Script Approval Request",
			"process_name": process,
			"script_task": task_id,
			"script_task_label": task_id,
			"server_script": server_script,
			"reason": reason,
		}
	).insert(ignore_permissions=True)  # patch: approval shipped with the moved helpers
	request.db_set(
		{
			"status": "Approved",
			"source": "Shipped by patch",
			"approved_by": "Administrator",
			"approved_on": now_datetime(),
		}
	)
