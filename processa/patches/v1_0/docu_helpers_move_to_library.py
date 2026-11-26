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
	r"^(\s*)from (processa\.ai_agent_registry\.definitions\.(?:shared\.helpers|docu\.tools|docu\.validators)) import (.+)$"
)
# A moved name used as code: not inside a word, an attribute, a string or after "def ".
USE = re.compile(r"(?<![\w.\"'])\b(" + "|".join(MOVED) + r")\b(?![\"'])")


def execute():
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
		edited = uses_library(script)
		if edited != script:
			frappe.db.set_value("Server Script", name, "script", edited)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def uses_library(script: str) -> str:
	"""script loading the moved helpers from the library instead of the backend; unchanged if it imports none."""
	if LOAD in script:
		return script
	lines, moved = [], False
	for line in script.split("\n"):
		match = HELPER_IMPORT.match(line)
		names = [n.strip() for n in match.group(3).split(",")] if match else []
		kept = [n for n in names if n not in MOVED]
		if not match or len(kept) == len(names):
			lines.append(line)
			continue
		if kept:
			lines.append(f"{match.group(1)}from {match.group(2)} import {', '.join(kept)}")
		if not moved:
			lines.append(match.group(1) + LOAD)
		moved = True
	if not moved:
		return script
	return "\n".join(_point_at_library(line) for line in lines)


def _point_at_library(line: str) -> str:
	if line.lstrip().startswith("#") or line.strip() == LOAD or HELPER_IMPORT.match(line):
		return line
	code, hash_, comment = line.partition("  #")
	code = USE.sub(
		lambda m: (
			"_schema.reserved_fieldnames()" if m.group(1) == MOVED_CONSTANT else "_schema." + m.group(1)
		),
		code,
	)
	return code + hash_ + comment
