# Copyright (c) 2026, one-fm and contributors
"""Logix's baseline suite checks that a script in a Libraries box defines functions only and reads no task data."""

import json

import frappe

from processa.patches.v1_0.add_logix_library_eval_case import finalize_check

AGENT_ID = "logix_agent"
SHAPE = "run_logix_agent"
SUITE_TITLE = "Logix - Baseline"
TITLE = "A library script defines functions only and reads no task data"
CONTEXT = {
	"element_name": "Reply Helpers",
	"process_context": {
		"element_id": "task_reply_helpers",
		"element_name": "Reply Helpers",
		"element_type": "ScriptTask",
		"process_name": "prosally_1",
		"parent_type": "AdHocSubProcess",
		"shape_kind": "script_task",
		"is_library": True,
		"incoming": [],
		"outgoing": [],
	},
}


def execute():
	process_model = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "process_model")
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite or not process_model or frappe.db.exists("AI Eval Case", {"suite": suite, "title": TITLE}):
		return
	frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"suite": suite,
			"title": TITLE,
			"case_type": "Trajectory",
			"process_model": process_model,
			"bpmn_id": SHAPE,
			"input_user_prompt": "Write a function that strips code fences from a model reply.",
			"input_context": json.dumps(CONTEXT),
			"assertions": [
				{"assertion_type": "skill_in_prompt", "value": "bpmn-library-script-contract"},
				finalize_check(
					"modified_script", "regex", r"^(?![\s\S]*\b(task_data|result|doc)\b)[\s\S]*\bdef \w+\("
				),
			],
		}
	).insert(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
