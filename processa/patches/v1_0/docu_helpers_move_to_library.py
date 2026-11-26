# Copyright (c) 2026, one-fm and contributors
"""The Docu map gets 'Docu: Lib Schema' in a Libraries box, and its scripts load the schema helpers from it.

The library needs no approval. Each script that imports one of the moved names loses that name from its import line,
loads the library once and calls the library instead. A site without the Docu map is left alone, and a second run
changes nothing.
"""

import re

import frappe

from processa.patches.v1_0.logix_helpers_move_to_libraries import (
	DATA,
	_ensure_library,
	task_scripts,
	with_libraries_box,
)

MODEL_NAME = "Docu \u2013 DocType Agent"
LIBRARY = "Docu: Lib Schema"
BOX_ID = "docu_libraries"
TASK_IDS = {LIBRARY: "lib_schema"}
LOAD = f'_schema = import_script("{LIBRARY}")'
MOVED_FUNCTIONS = (
	"extract_json",
	"format_history",
	"diff_ir",
	"merge_into_live_fields",
	"validate_doctype_json",
	"validate_doctype_ir",
)
MOVED_CONSTANT = "RESERVED_FIELDNAMES"
MOVED = (*MOVED_FUNCTIONS, MOVED_CONSTANT)
HELPER_IMPORT = re.compile(
	r"^(\s*)from (processa\.ai_agent_registry\.definitions\.(?:shared\.helpers|shared\.tools|docu\.tools|docu\.validators|lucrusher\.tools|prosally\.helpers|prosally\.tools_\w+)) import (.+)$"
)


def execute(moved: tuple = MOVED):
	model = frappe.db.get_value("BPMN Process Model", MODEL_NAME, ["bpmn_xml", "process_name"], as_dict=True)
	if not model:
		return
	_ensure_library(LIBRARY, (DATA / "docu_lib_schema.py").read_text())
	xml = with_libraries_box(model.bpmn_xml or "", BOX_ID, TASK_IDS)
	if xml != model.bpmn_xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)
	for task_id, name in task_scripts(xml).items():
		if not name or task_id in TASK_IDS.values():
			continue
		script = frappe.db.get_value("Server Script", name, "script") or ""
		edited = uses_library(script, moved)
		if edited != script:
			frappe.db.set_value("Server Script", name, "script", edited)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def uses_library(script: str, moved: tuple = MOVED, load: str = LOAD) -> str:
	"""script loading the moved names from the library instead of the backend; unchanged if it imports none."""
	lines, found = [], False
	for line in script.split("\n"):
		match = HELPER_IMPORT.match(line)
		names = [n.strip() for n in match.group(3).split(",")] if match else []
		kept = [n for n in names if n not in moved]
		if not match or len(kept) == len(names):
			lines.append(line)
			continue
		if kept:
			lines.append(f"{match.group(1)}from {match.group(2)} import {', '.join(kept)}")
		if not found and load not in script:
			lines.append(match.group(1) + load)
		found = True
	if not found:
		return script
	# A moved name used as code: not inside a word, an attribute or a string.
	use = re.compile(r"(?<![\w.\"'])\b(" + "|".join(moved) + r")\b(?![\"'])")
	return load_before_first_use("\n".join(_point_at_library(line, use, load) for line in lines), load)


def _point_at_library(line: str, use: re.Pattern, load: str) -> str:
	if line.lstrip().startswith("#") or line.strip() == load or HELPER_IMPORT.match(line):
		return line
	alias = load.split(" = ", 1)[0] + "."
	code, hash_, comment = line.partition("  #")
	code = use.sub(
		lambda m: "_schema.reserved_fieldnames()" if m.group(1) == MOVED_CONSTANT else alias + m.group(1),
		code,
	)
	return code + hash_ + comment


def load_before_first_use(script: str, load: str) -> str:
	"""script with its library load moved above the top-level statement that first uses the library."""
	import ast

	alias = load.split(" = ", 1)[0] + "."
	lines = script.split("\n")
	at = next((i for i, line in enumerate(lines) if line.strip() == load), None)
	first = next(
		(i for i, line in enumerate(lines) if alias in line and not line.lstrip().startswith("#")), None
	)
	if at is None or first is None or at < first:
		return script
	start = next(n.lineno - 1 for n in ast.parse(script).body if n.lineno - 1 <= first <= n.end_lineno - 1)
	del lines[at]
	lines.insert(start, load)
	return "\n".join(lines)
