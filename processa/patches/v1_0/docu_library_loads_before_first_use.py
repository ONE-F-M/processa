# Copyright (c) 2026, one-fm and contributors
"""Each Docu script that calls 'Docu: Lib Schema' above the line that loads it gets the load moved above that call."""

import frappe

from processa.patches.v1_0.docu_helpers_move_to_library import LOAD, MODEL_NAME, load_before_first_use
from processa.patches.v1_0.logix_helpers_move_to_libraries import task_scripts


def execute():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if not xml:
		return
	for name in {name for name in task_scripts(xml).values() if name}:
		script = frappe.db.get_value("Server Script", name, "script") or ""
		fixed = load_before_first_use(script, LOAD)
		if fixed != script:
			frappe.db.set_value("Server Script", name, "script", fixed)
