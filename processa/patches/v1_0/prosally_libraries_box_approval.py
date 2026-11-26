# Copyright (c) 2026, one-fm and contributors
"""Generate Process and Modify Process get an Approved request for take_out_libraries and put_back_libraries.

The scripts call them to keep a map's Libraries box while ProsAlly redraws the diagram. A site without the ProsAlly
map is left alone, and a second run creates nothing twice.
"""

import frappe

from processa.patches.v1_0.logix_helpers_move_to_libraries import _approve, task_scripts
from processa.patches.v1_0.prosally_keeps_the_libraries_box import GENERATE_SCRIPT, MODIFY_SCRIPT

MODEL_NAME = "ProsAlly \u2013 Process Modeller (1)"
REASON = "ProsAlly keeps a map's Libraries box while it redraws the diagram."


def execute():
	model = frappe.db.get_value("BPMN Process Model", MODEL_NAME, ["bpmn_xml", "process_name"], as_dict=True)
	if not model or not model.process_name:
		return
	for task_id, name in task_scripts(model.bpmn_xml or "").items():
		if name in (GENERATE_SCRIPT, MODIFY_SCRIPT):
			_approve(model.process_name, task_id, name, REASON)
