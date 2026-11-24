"""Logix's map Server Script functions: the script under debug, its last error, the library scripts on the map
and the fields of the DocTypes a turn is about."""

import ast
import re
import xml.etree.ElementTree as ET

import frappe
from frappe.model import child_table_fields, default_fields, display_fieldtypes, optional_fields
from frappe.model.document import Document
from frappe.utils.safe_exec import SERVER_SCRIPT_FILE_PREFIX

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


def debug_inputs(user_text: str, original_script_content: str, current_script: str) -> dict:
	"""The script under debug and its newest error; what the person pasted wins over the saved script."""
	user_text = user_text or ""
	script_text = _saved_script(current_script) or original_script_content or ""
	for block in CODE_FENCE.findall(user_text):
		if TRACEBACK not in block:
			script_text = block.strip()
			break

	at = user_text.find(TRACEBACK)
	last_error = user_text[at:][-ERROR_CHARS:] if at != -1 else _logged_error(current_script)
	return {"script_text": script_text, "last_error": last_error}


def _saved_script(script_name: str) -> str:
	return (script_name and frappe.db.get_value("Server Script", script_name, "script")) or ""


def _logged_error(script_name: str) -> str:
	"""The newest Error Log raised by this script, whichever path ran it, with when it and the script were saved."""
	if not script_name:
		return ""
	rows = frappe.get_all(
		"Error Log",
		or_filters=[
			["method", "=", ENGINE_ERROR_TITLE.format(script_name)],
			["method", "=", CHECK_ERROR_TITLE.format(script_name)],
			["error", "like", f'%{SERVER_SCRIPT_FILE_PREFIX}: {frappe.scrub(script_name)}"%'],
		],
		fields=["error", "creation"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return ""
	saved = frappe.db.get_value("Server Script", script_name, "modified")
	return f"Logged {rows[0].creation}; the script was last saved {saved}.\n{rows[0].error[-ERROR_CHARS:]}"


def step_functions(process_model: str | None, current_script: str = "") -> list[dict]:
	"""The functions defined inside the connected steps of a map that the user can read, other than the open script.

	import_script cannot load these: a step runs its own code when the flow reaches it.
	"""
	bpmn_xml = process_model and frappe.db.get_value("BPMN Process Model", process_model, "bpmn_xml")
	if not bpmn_xml:
		return []
	steps = []
	for task in ET.fromstring(bpmn_xml.strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		name = task.get(SERVER_SCRIPT_ATTR)
		connected = task.find(f"{BPMN_NS}incoming") is not None or task.find(f"{BPMN_NS}outgoing") is not None
		if not connected or not name or name == current_script or not frappe.db.exists("Server Script", name):
			continue
		if not frappe.has_permission("Server Script", "read", doc=name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		try:
			functions = [node for node in ast.parse(code).body if isinstance(node, ast.FunctionDef)]
		except SyntaxError:
			continue
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

	A library is a script task with no incoming or outgoing flow whose script only defines functions or does not parse.
	"""
	bpmn_xml = process_model and frappe.db.get_value("BPMN Process Model", process_model, "bpmn_xml")
	if not bpmn_xml:
		return []
	libraries = []
	for task in ET.fromstring(bpmn_xml.strip().encode()).iter(f"{BPMN_NS}scriptTask"):
		name = task.get(SERVER_SCRIPT_ATTR)
		connected = task.find(f"{BPMN_NS}incoming") is not None or task.find(f"{BPMN_NS}outgoing") is not None
		if connected or not name or not frappe.db.exists("Server Script", name):
			continue
		if not frappe.has_permission("Server Script", "read", doc=name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		functions = function_signatures(code)
		if functions is not None:
			libraries.append({"name": name, "functions": functions, "code": code[:LIBRARY_CODE_CHARS]})
	return libraries


def function_signatures(code: str) -> list[str] | None:
	"""Each function code defines as name(args); None when code does more than define functions."""
	try:
		body = ast.parse(code).body
	except SyntaxError:
		return []
	if any(not isinstance(node, ast.FunctionDef) for node in body):
		return None
	return [f"{node.name}({ast.unparse(node.args)})" for node in body]


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


def doctype_inputs(user_text: str, process_context: dict | None, current_script: str) -> dict:
	"""The fields of each DocType the turn is about, and the DocTypes it names that do not exist."""
	names, missing = _turn_doctypes(user_text or "", process_context or {}, current_script)
	return {
		"doctype_fields": {name: field_list(name) for name in names},
		"missing_doctypes": missing,
		"doc_doctype": _trigger_doctype(process_context or {}) or _this_doctype(user_text or ""),
	}


def field_findings(code: str, turn: dict) -> list[dict]:
	"""A finding for each field the script reads or writes that its DocType does not have."""
	try:
		tree = ast.parse(code)
	except SyntaxError:
		return []
	lines = code.splitlines()
	bound = {"doc": turn.get("doc_doctype")} if turn.get("doc_doctype") else {}
	for node in ast.walk(tree):
		if not isinstance(node, ast.Assign) or len(node.targets) != 1:
			continue
		doctype = _loaded_doctype(node.value)
		if doctype and isinstance(node.targets[0], ast.Name):
			bound[node.targets[0].id] = doctype

	findings, seen = [], set()
	for node in ast.walk(tree):
		for doctype, field in _used_fields(node, bound):
			if (doctype, field) in seen:
				continue
			seen.add((doctype, field))
			finding = _field_finding(doctype, field)
			if finding:
				findings.append(dict(finding, line=node.lineno, code=lines[node.lineno - 1].strip()))
	return findings


def field_list(doctype: str) -> dict:
	"""The data fields of a DocType and of each of its child tables."""
	meta = frappe.get_meta(doctype)
	return {
		"fields": [f.fieldname for f in meta.fields if f.fieldtype not in display_fieldtypes],
		"child_tables": {
			f.fieldname: {
				"doctype": f.options,
				"fields": [
					c.fieldname
					for c in frappe.get_meta(f.options).fields
					if c.fieldtype not in display_fieldtypes
				],
			}
			for f in meta.get_table_fields()
		},
	}


def _turn_doctypes(user_text: str, process_context: dict, current_script: str) -> tuple[list[str], list[str]]:
	"""The start event's DocType, the linked script's and those the request names, in that order."""
	candidates = [_trigger_doctype(process_context)]
	if current_script:
		candidates.append(frappe.db.get_value("Server Script", current_script, "reference_doctype"))
	missing = []
	for match in NAMED_DOCTYPE.finditer(user_text):
		words = match.group(1).split()
		found = next(
			(" ".join(words[i:]) for i in range(len(words)) if _is_doctype(" ".join(words[i:]))), None
		)
		if found:
			candidates.append(found)
		elif match.group(2).lower() == "doctype":
			missing.append(match.group(1))
	for match in REFERRED_DOCTYPE.finditer(user_text):
		candidates.append(_leading_doctype(match.group(2).split()))
	names = []
	for name in candidates:
		if not name or name in names:
			continue
		if _is_doctype(name):
			names.append(name)
		elif name not in missing:
			missing.append(name)
	return names[:MAX_DOCTYPES], missing


def _this_doctype(user_text: str) -> str | None:
	"""The DocType the request calls "this X": the record the script task runs on."""
	for match in REFERRED_DOCTYPE.finditer(user_text):
		if match.group(1).lower() == "this":
			found = _leading_doctype(match.group(2).split())
			if found:
				return found
	return None


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


def _loaded_doctype(value) -> str | None:
	"""The DocType of frappe.get_doc("X", ...), frappe.new_doc("X") or frappe.get_doc({"doctype": "X", ...})."""
	if not (
		isinstance(value, ast.Call)
		and isinstance(value.func, ast.Attribute)
		and value.func.attr in DOC_LOADERS
	):
		return None
	first = value.args[0] if value.args else None
	if isinstance(first, ast.Dict):
		return _dict_doctype(first)
	return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def _used_fields(node, bound: dict):
	"""(DocType, field) pairs a node reads or writes."""
	owner = node.value.id if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) else None
	if owner in bound:
		if not hasattr(Document, node.attr):
			yield bound[owner], node.attr
	elif isinstance(node, ast.Dict) and _dict_doctype(node):
		doctype = _dict_doctype(node)
		for key in node.keys:
			if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value != "doctype":
				yield doctype, key.value
	elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
		yield from _called_fields(node, bound)


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


def _field_finding(doctype: str, field: str | None) -> dict | None:
	"""A finding when the DocType does not exist, or the field is not one of its fields."""
	if not _is_doctype(doctype):
		return {
			"category": "Field check",
			"name": doctype,
			"rule": f"{doctype} is not a DocType on this site. Do not guess one; ask which DocType the person means.",
		}
	field = (field or "").split(" as ")[0].strip()
	if not field or field in STANDARD_FIELDS:
		return None
	if any(c in field for c in "(*`."):
		return None
	if frappe.get_meta(doctype).has_field(field):
		return None
	return {
		"category": "Field check",
		"name": field,
		"rule": f"{field} is not a field of {doctype}. Use one of its fields, or ask which field the person means.",
	}


def _is_doctype(name: str) -> bool:
	return bool(name) and bool(frappe.db.exists("DocType", name))


def _dict_doctype(node: ast.Dict) -> str | None:
	for key, value in zip(node.keys, node.values, strict=True):
		if isinstance(key, ast.Constant) and key.value == "doctype" and isinstance(value, ast.Constant):
			return value.value
	return None
