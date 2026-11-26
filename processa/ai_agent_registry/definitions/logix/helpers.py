"""Logix's map Server Script functions: the script under debug, its last error, the library scripts on the map
and the fields of the DocTypes a turn is about."""

import ast
import re
import xml.etree.ElementTree as ET

import frappe
from frappe.model import child_table_fields, default_fields, optional_fields

from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import

CODE_FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)
TRACEBACK = "Traceback (most recent call last)"
ERROR_CHARS = 3000
LIBRARY_CODE_CHARS = 3000
ENGINE_ERROR_TITLE = 'BPMN ScriptTask: "{}" execution failed'
CHECK_ERROR_TITLE = 'Logix check: "{}" failed'
BPMN_NS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
SERVER_SCRIPT_ATTR = "{http://spiffworkflow.org/bpmn/schema/1.0/core}serverScript"
MAX_DOCTYPES = 3
# "the Employee DocType", "Leave Application records": a name followed by a word that marks it as a DocType.
NAMED_DOCTYPE = re.compile(r"((?:[A-Z][\w-]*\s+){0,3}[A-Z][\w-]*)\s+((?i:doctype|record|records|form))\b")
# "this Medical Appointment", "each Leave Application": a capitalised name after a word that points at records.
REFERRED_DOCTYPE = re.compile(r"\b(this|the|each|every|an?|for)\s+((?:[A-Z][\w-]*\s+){0,3}[A-Z][\w-]*)")
STANDARD_FIELDS = frozenset(default_fields + child_table_fields + optional_fields)
DOC_LOADERS = ("get_doc", "new_doc", "get_cached_doc", "get_last_doc")
FIELD_QUERIES = {
	"get_all": "fields",
	"get_list": "fields",
	"get_value": "fieldname",
	"get_values": "fieldname",
	"set_value": "fieldname",
	"exists": None,
	"count": None,
	"delete": None,
}


def step_functions(process_model: str | None, current_script: str = "") -> list[dict]:
	"""The functions defined in scripts on a map that also run code, which the user can read, other than the open script.

	import_script cannot load these: importing one would run its other code too.
	"""
	bpmn_xml = process_model and frappe.db.get_value("BPMN Process Model", process_model, "bpmn_xml")
	if not bpmn_xml:
		return []
	steps = []
	for task in ET.fromstring(bpmn_xml.strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		name = task.get(SERVER_SCRIPT_ATTR)
		if not name or name == current_script or not frappe.db.exists("Server Script", name):
			continue
		if not frappe.has_permission("Server Script", "read", doc=name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		if not runs_code_on_import(code):
			continue
		functions = [node for node in ast.parse(code).body if isinstance(node, ast.FunctionDef)]
		if functions:
			steps.append(
				{
					"step": task.get("name") or task.get("id"),
					"script": name,
					"functions": [f"{node.name}({ast.unparse(node.args)})" for node in functions],
					"code": "\n\n".join(ast.get_source_segment(code, node) for node in functions)[
						:LIBRARY_CODE_CHARS
					],
				}
			)
	return steps


def library_scripts(process_model: str | None) -> list[dict]:
	"""The library scripts on a map that the user can read, each with its function signatures and code.

	A library is a script task whose script only defines functions or does not parse; its arrows do not matter.
	"""
	bpmn_xml = process_model and frappe.db.get_value("BPMN Process Model", process_model, "bpmn_xml")
	if not bpmn_xml:
		return []
	libraries = []
	for task in ET.fromstring(bpmn_xml.strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		name = task.get(SERVER_SCRIPT_ATTR)
		if not name or not frappe.db.exists("Server Script", name):
			continue
		if not frappe.has_permission("Server Script", "read", doc=name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		functions = function_signatures(code)
		if functions is not None:
			libraries.append({"name": name, "functions": functions, "code": code[:LIBRARY_CODE_CHARS]})
	return libraries


def function_signatures(code: str) -> list[str] | None:
	"""Each function other scripts can call, as name(args); None when code does more than define functions.

	import_script hands over only functions whose names do not start with an underscore.
	"""
	try:
		body = ast.parse(code).body
	except SyntaxError:
		return []
	if any(not isinstance(node, ast.FunctionDef) for node in body):
		return None
	return [f"{node.name}({ast.unparse(node.args)})" for node in body if not node.name.startswith("_")]


def workflow_states(process_model: str | None) -> list[str]:
	"""Each state of the active Workflow on the map's trigger DocType, as 'State (doc status N)'."""
	doctype = process_model and frappe.db.get_value("BPMN Process Model", process_model, "trigger_doctype")
	workflow = doctype and frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
	if not workflow:
		return []
	rows = frappe.get_all(
		"Workflow Document State",
		filters={"parent": workflow},
		fields=["state", "doc_status"],
		order_by="idx asc",
	)
	return list(dict.fromkeys(f"{row.state} (doc status {row.doc_status})" for row in rows))


def library_text(libraries: list[dict]) -> str:
	"""The library section of the text Logix reads."""
	lines = [
		"LIBRARY SCRIPTS ON THIS MAP: reuse these functions instead of writing them again. "
		'Load one with lib = import_script("<library name>") and call lib.<function>(...).'
	]
	for library in libraries:
		lines.append(
			f"- {library['name']}: {', '.join(library['functions']) or 'no functions could be read'}"
		)
	return "\n".join(lines)


def step_function_text(steps: list[dict]) -> str:
	"""The section of the text Logix reads that lists the functions inside steps."""
	lines = [
		"FUNCTIONS INSIDE STEPS ON THIS MAP: a step runs its own code when the flow reaches it, so "
		"import_script cannot load these. Copy one into the open script, or move it into a library to share it."
	]
	for step in steps:
		lines.append(f"- step {step['step']} (script {step['script']}): {', '.join(step['functions'])}")
	return "\n".join(lines)


def _leading_doctype(words: list[str]) -> str | None:
	"""The longest run of leading words that names a DocType."""
	return next(
		(" ".join(words[:i]) for i in range(len(words), 0, -1) if _is_doctype(" ".join(words[:i]))), None
	)


def _trigger_doctype(process_context: dict) -> str | None:
	process_id = process_context.get("process_name")
	return process_id and frappe.db.get_value(
		"BPMN Process Model", {"process_id": process_id}, "trigger_doctype", order_by="modified desc"
	)


def _called_fields(node: ast.Call, bound: dict):
	func = node.func
	if (
		isinstance(func.value, ast.Name)
		and func.value.id in bound
		and func.attr in ("get", "set", "db_set", "append")
	):
		if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
			yield bound[func.value.id], node.args[0].value
		return
	if func.attr in DOC_LOADERS and node.args and isinstance(node.args[0], ast.Constant):
		yield node.args[0].value, None
		return
	if func.attr not in FIELD_QUERIES or not node.args:
		return
	doctype = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
	if not isinstance(doctype, str):
		return
	yield doctype, None
	keyword = {k.arg: k.value for k in node.keywords}
	filters = keyword.get("filters") or (node.args[1] if len(node.args) > 1 else None)
	fields = keyword.get(FIELD_QUERIES[func.attr]) if FIELD_QUERIES[func.attr] else None
	if fields is None and func.attr in ("get_value", "get_values") and len(node.args) > 2:
		fields = node.args[2]
	if fields is None and func.attr == "set_value" and len(node.args) > 2:
		fields = node.args[2]
	for value in (filters, fields, keyword.get("pluck")):
		for field in _field_names(value):
			yield doctype, field


def _field_names(node) -> list[str]:
	"""Field names in a literal fields list, field name, filters dict or filters list."""
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return [node.value]
	if isinstance(node, ast.Dict):
		return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
	if isinstance(node, (ast.List, ast.Tuple)):
		names = []
		for item in node.elts:
			if not isinstance(item, (ast.List, ast.Tuple)):
				names.extend(_field_names(item))
				continue
			# A filter row is [field, op, value] or [doctype, field, op, value].
			entry = item.elts[1 if len(item.elts) == 4 else 0] if item.elts else None
			if isinstance(entry, ast.Constant) and isinstance(entry.value, str):
				names.append(entry.value)
		return names
	return []


def _is_doctype(name: str) -> bool:
	return bool(name) and bool(frappe.db.exists("DocType", name))


def _dict_doctype(node: ast.Dict) -> str | None:
	for key, value in zip(node.keys, node.values, strict=True):
		if isinstance(key, ast.Constant) and key.value == "doctype" and isinstance(value, ast.Constant):
			return value.value
	return None
