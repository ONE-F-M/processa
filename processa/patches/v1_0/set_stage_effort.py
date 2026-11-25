"""Sets Effort on the ProsAlly and Logix stages that have none: high where the stage draws, writes or reviews, low where it classifies."""

import frappe

AGENT_EFFORT = {
	"logix_script_writer": "high",
	"logix_tool_writer": "high",
	"logix_script_reviewer": "high",
	"logix_intent_classifier": "low",
}
PROSALLY = "prosally_agent"
PROSALLY_STAGE_EFFORT = {
	"process_generator": "high",
	"modifier": "high",
	"operation_writer": "high",
	"intent_classifier": "low",
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
