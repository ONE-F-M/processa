# Copyright (c) 2026, one-fm and contributors
"""Logix's debug stage helpers and LuCrusher's document search move into libraries on their maps.

Each library imports only platform functions, so each task that loads it, and the library task, gets an Approved
request shipped by the patch. A site without a map is left alone, and a second run changes nothing.
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

MOVES = (
	{
		"model": "Logix \u2013 Script Task Agent",
		"box_id": "logix_libraries",
		"library": "Logix: Lib Debug",
		"task_id": "lib_debug",
		"data_file": "logix_lib_debug.py",
		"load": '_debug_lib = import_script("Logix: Lib Debug")',
		"moved": ("run_debug_stage", "revert_output"),
		"approved_tasks": ("debug_script", "finalize", "lib_debug"),
		"reason": "Logix debug stage helpers moved into the map's library.",
	},
	{
		"model": "LuCrusher \u2013 Migration Agent",
		"box_id": "lucrusher_libraries",
		"library": "LuCrusher: Lib DMS",
		"task_id": "lib_dms",
		"data_file": "lucrusher_lib_dms.py",
		"load": '_dms_lib = import_script("LuCrusher: Lib DMS")',
		"moved": ("search_dms_documents",),
		"approved_tasks": ("search_dms_documents", "lib_dms"),
		"reason": "LuCrusher document search moved into the map's library.",
	},
)


def execute():
	for move in MOVES:
		_move(**move)


def _move(model, box_id, library, task_id, data_file, load, moved, approved_tasks, reason):
	values = frappe.db.get_value("BPMN Process Model", model, ["bpmn_xml", "process_name"], as_dict=True)
	if not values or not values.process_name:
		return
	_ensure_library(library, (DATA / data_file).read_text())
	xml = with_libraries_box(values.bpmn_xml or "", box_id, {library: task_id})
	if xml != values.bpmn_xml:
		frappe.db.set_value("BPMN Process Model", model, "bpmn_xml", xml)
	scripts = task_scripts(xml)
	for current_task, name in scripts.items():
		if not name or current_task == task_id:
			continue
		script = frappe.db.get_value("Server Script", name, "script") or ""
		edited = uses_library(script, moved, load)
		if edited != script:
			frappe.db.set_value("Server Script", name, "script", edited)
	for approved in approved_tasks:
		if scripts.get(approved):
			_approve(values.process_name, approved, scripts[approved], reason)
	from processa.api.deploy import compile_process_model

	compile_process_model(model)
