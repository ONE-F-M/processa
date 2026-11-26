"""Sets Effort on the ProsAlly and Logix stages that have none: High where the stage draws, writes, tests or reviews, Low where it classifies."""

import frappe

AGENT_EFFORT = {
	"logix_script_writer": "High",
	"logix_tool_writer": "High",
	"logix_script_reviewer": "High",
	"logix_test_writer": "High",
	"logix_intent_classifier": "Low",
}
PROSALLY = "prosally_agent"
PROSALLY_STAGE_EFFORT = {
	"process_generator": "High",
	"modifier": "High",
	"operation_writer": "High",
	"intent_classifier": "Low",
}


def execute():
	for agent_id, effort in AGENT_EFFORT.items():
		frappe.db.set_value(
			"AI Agent Configuration", {"agent_id": agent_id, "effort": ["is", "not set"]}, "effort", effort
		)
		frappe.cache.delete_value(f"agent_config:{agent_id}")
	prosally = frappe.db.get_value("AI Agent Configuration", {"agent_id": PROSALLY}, "name")
	for stage, effort in PROSALLY_STAGE_EFFORT.items():
		frappe.db.set_value(
			"AI Agent Sub Prompt",
			{"parent": prosally, "sub_agent_id": stage, "effort": ["is", "not set"]},
			"effort",
			effort,
		)
	frappe.cache.delete_value(f"agent_config:{PROSALLY}")
