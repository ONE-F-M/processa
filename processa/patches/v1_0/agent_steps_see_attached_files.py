"""Docu's and the Connector Agent's steps that call the model send the files attached to the turn.

Docu's Build Context keeps the turn's files; each model call passes them through with_attachments, and the new
import is approved on each map task that runs the script. Edits each script once; one whose anchor moved is
logged and left as it is.
"""

import xml.etree.ElementTree as ET

import frappe

from processa.ai_agent_registry.definitions.logix.helpers import BPMN_NS, SERVER_SCRIPT_ATTR
from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.patches.v1_0.approve_live_script_tasks import approve
from processa.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

TURN_IMPORT = "from processa.processa_engine.agent_runtime.turn_state import "
IMPORT = "from processa.processa_engine.dispatch.attachments import with_attachments\n"

BUILD_CONTEXT = (
	(
		'    "user_text": task_data.get("user_text", "") or "",\n',
		'    "user_text": task_data.get("user_text", "") or "",\n    "files": task_data.get("files") or [],\n',
	),
)


def _edits(user: str, rest: str = ")", files: str = 'turn.get("files")', indent: str = "") -> tuple:
	"""The import and model-call edits that make one step send the turn's files."""
	return (
		(indent + TURN_IMPORT, indent + IMPORT + indent + TURN_IMPORT),
		(
			f"complete(system=_system, user={user}{rest}",
			f"complete(system=_system, **with_attachments({user}, {files}){rest}",
		),
	)


STEPS = {
	"Docu%Tool Classify Intent": _edits("prompt"),
	"Docu%Tool Clarify": _edits("prompt", ", tools=_clarifier_tools)"),
	"Docu%Tool Review Schema": _edits("_review_user", ", tools=_reviewer_tools)"),
	"Docu%Tool Edit Field Property": _edits("prompt"),
	"Docu%Tool Edit Client Script": _edits("prompt + _feedback"),
	"Docu%Tool Write List Script": _edits("prompt"),
	"Connector Agent: Tool Draft Connector": _edits("_prompt", files='task_data.get("files")', indent="    "),
}


def execute():
	edit_script("Docu%Build Context", BUILD_CONTEXT)
	for pattern, edits in STEPS.items():
		name = edit_script(pattern, edits)
		if name:
			approve_import(name)


def edit_script(pattern: str, edits: tuple) -> str | None:
	"""The script's name once its edits are in, or None when it is missing or an anchor moved."""
	name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
	if not name:
		return None
	doc = frappe.get_doc("Server Script", name)
	script = doc.script
	for anchor, replacement in edits:
		script = apply_edit(script, anchor, replacement)
		if script is None:
			frappe.log_error(
				title="agent_steps_see_attached_files: anchor not found",
				message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
			)
			return None
	if script != doc.script:
		doc.script = script
		doc.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
	return name


def approve_import(name: str) -> None:
	"""Approve the script's findings on every map task that runs it."""
	code = frappe.db.get_value("Server Script", name, "script")
	models = frappe.get_all(
		"BPMN Process Model",
		filters={"bpmn_xml": ["like", f"%{name}%"]},
		fields=["process_name", "bpmn_xml"],
	)
	for model in models:
		for element_id, label in map_tasks(model.bpmn_xml).get(name, []):
			if model.process_name and script_task_findings(code, model.process_name, element_id, name):
				approve(model.process_name, element_id, label, name)


def map_tasks(xml: str) -> dict:
	"""Each Server Script on the map with the (element id, label) of the tasks that run it."""
	tasks = {}
	for task in ET.fromstring((xml or "<x/>").strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		script = task.get(SERVER_SCRIPT_ATTR)
		if script:
			tasks.setdefault(script, []).append((task.get("id"), task.get("name") or task.get("id")))
	return tasks
