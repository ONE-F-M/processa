# Copyright (c) 2026, one-fm and contributors
"""The LuCrusher map gets 'LuCrusher: Lib Codebase' in a Libraries box, and its codebase scripts load from it.

Scan Codebase and Read DocType Logic, and the library task, get an Approved request shipped by the patch. A site without
the LuCrusher map is left alone, and a second run changes nothing.
"""

import frappe

from processa.patches.v1_0.docu_helpers_move_to_library import uses_library
from processa.patches.v1_0.logix_helpers_move_to_libraries import (
	DATA,
	_approve,
	_ensure_library,
	task_scripts,
	with_libraries_box,
)

MODEL_NAME = "LuCrusher \u2013 Migration Agent"
LIBRARY = "LuCrusher: Lib Codebase"
BOX_ID = "lucrusher_libraries"
TASK_IDS = {LIBRARY: "lib_codebase"}
LOAD = f'_codebase = import_script("{LIBRARY}")'
MOVED = ("find_whitelisted_methods", "get_codebase_index", "read_doctype_sources")
APPROVED_TASKS = ("scan_codebase_for_process", "read_doctype_logic", TASK_IDS[LIBRARY])
REASON = "LuCrusher codebase helpers moved into the map's library."


def execute():
	model = frappe.db.get_value("BPMN Process Model", MODEL_NAME, ["bpmn_xml", "process_name"], as_dict=True)
	if not model or not model.process_name:
		return
	_ensure_library(LIBRARY, (DATA / "lucrusher_lib_codebase.py").read_text())
	xml = with_libraries_box(model.bpmn_xml or "", BOX_ID, TASK_IDS)
	if xml != model.bpmn_xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)
	scripts = task_scripts(xml)
	for task_id, name in scripts.items():
		if not name or task_id in TASK_IDS.values():
			continue
		script = frappe.db.get_value("Server Script", name, "script") or ""
		edited = uses_library(script, MOVED, LOAD)
		if edited != script:
			frappe.db.set_value("Server Script", name, "script", edited)
	for task_id in APPROVED_TASKS:
		if scripts.get(task_id):
			_approve(model.process_name, task_id, scripts[task_id], REASON)
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)
