"""Raises Max Tokens to the thinking minimum on agents whose AI Model thinks, so each one saves under the new check."""

import frappe

from processa.processa_engine.agent_runtime.llm_factory import thinking_min_tokens


def execute():
	for agent in frappe.get_all(
		"AI Agent Configuration",
		filters={"ai_model": ["is", "set"]},
		fields=["name", "agent_id", "ai_model", "max_tokens", "thinking_min_tokens"],
	):
		minimum = thinking_min_tokens(agent.ai_model, agent.thinking_min_tokens)
		if not agent.max_tokens:
			continue
		if agent.max_tokens < minimum:
			frappe.db.set_value(
				"AI Agent Configuration", agent.name, "max_tokens", minimum, update_modified=False
			)
			frappe.cache.delete_value(f"agent_config:{agent.agent_id}")
