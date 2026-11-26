# Copyright (c) 2026, one-fm and contributors
"""Logix writes and reviews a script in a Libraries box against a library contract and does not try it on a record."""

import frappe

from processa.patches.v1_0.seed_logix_skills import _upsert_skill

WRITER_AGENT_ID = "logix_script_writer"
MODEL_NAME = "Logix \u2013 Script Task Agent"
REVIEW_SCRIPT = "Logix \u2013 Tool Review Script"

SKILL = {
	"skill_name": "bpmn-library-script-contract",
	"description": (
		"The contract for a library script, a script task in a Libraries box that other scripts load "
		"with import_script. Use this skill when the request has an Is library line, instead of "
		"bpmn-script-task-contract."
	),
	"body": """# Library script contract

Other scripts on the same map load this script with `lib = import_script("<script name>")` and call its functions as `lib.name(...)`.

- Define functions, and constants they use. Do no work at the top level: no query, no write, no call that runs when the script loads.
- The script sees only `frappe`. There is no `doc`, `task_data`, `result`, `instance` or `context_doctype`. A function takes what it needs as arguments and returns its answer.
- Never call `import_script`. A library cannot load another library.
- Only functions are handed over, and only those whose names do not start with an underscore. Name every function a caller needs without a leading underscore.
- The rules of `frappe-server-script-safety` apply.

## Worked example
```python
# Clean up text a model sent back.
def strip_fences(text):
    lines = (text or "").strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\\n".join(lines).strip()
```
""",
}

WRITER_EDITS = (
	(
		"when it says agent_tool.",
		"when it says agent_tool. When the request has an Is library line, load "
		"`bpmn-library-script-contract` instead of `bpmn-script-task-contract`.",
	),
	(
		"**Shape kind:** {{ shape_kind }}&#10;",
		"**Shape kind:** {{ shape_kind }}&#10;{% if turn.process_context.is_library %}**Is library:** yes. "
		"Other scripts load this script with import_script. Define functions and constants only; never read "
		"task_data, doc or result.&#10;{% endif %}",
	),
)

REVIEW_EDITS = (
	(
		'_contract_skill = "bpmn-agent-tool-contract" if shape_kind == "agent_tool" else "bpmn-script-task-contract"',
		'_is_library = bool((turn.get("process_context") or {}).get("is_library"))\n'
		'_contract_skill = "bpmn-library-script-contract" if _is_library else "bpmn-agent-tool-contract" '
		'if shape_kind == "agent_tool" else "bpmn-script-task-contract"',
	),
	(
		'if _valid and shape_kind == "script_task":',
		'if _valid and shape_kind == "script_task" and not _is_library:',
	),
)


def execute():
	_upsert_skill(SKILL)
	_enable_for_writer()
	_edit_writer_prompt()
	_edit_review_script()


def _enable_for_writer():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": WRITER_AGENT_ID}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Agent Configuration", name)
	if SKILL["skill_name"] in {row.skill for row in doc.enabled_skills}:
		return
	doc.append("enabled_skills", {"skill": SKILL["skill_name"]})
	doc.save(ignore_permissions=True)


def _edit_writer_prompt():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	new = writer_prompt(xml)
	if new == xml:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", new)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def writer_prompt(xml: str) -> str:
	"""The map with each write_script edit applied where its old text is there exactly once."""
	start = xml.find('<bpmn:serviceTask id="write_script"')
	end = xml.find("</bpmn:serviceTask>", start)
	if start < 0:
		return xml
	segment = xml[start:end]
	for old, new in WRITER_EDITS:
		if new not in segment and segment.count(old) == 1:
			segment = segment.replace(old, new)
	return xml[:start] + segment + xml[end:]


def _edit_review_script():
	if not frappe.db.exists("Server Script", REVIEW_SCRIPT):
		return
	doc = frappe.get_doc("Server Script", REVIEW_SCRIPT)
	new = review_script(doc.script or "")
	if new != doc.script:
		doc.script = new
		doc.save(ignore_permissions=True)


def review_script(script: str) -> str:
	"""The Review Script text with the library contract pick and, where it has one, the dry run skipped for a library."""
	(contract_old, contract_new), (dry_run_old, dry_run_new) = REVIEW_EDITS
	if contract_new not in script:
		if script.count(contract_old) != 1:
			return script
		script = script.replace(contract_old, contract_new)
	if script.count(dry_run_old) == 1:
		script = script.replace(dry_run_old, dry_run_new)
	return script
