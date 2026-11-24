# Copyright (c) 2026, one-fm and contributors
"""The Frontend Agent configuration's prompt names processa; after_migrate copies it onto the map."""

import frappe

from processa.patches.v1_0.frontend_agent_names_processa import renamed

CONFIG_NAME = "Frontend Agent"


def execute():
	prompt = frappe.db.get_value("AI Agent Configuration", CONFIG_NAME, "system_prompt")
	if not prompt or renamed(prompt) == prompt:
		return
	# db.set_value, not save: a save of a Live agent starts a re-provision.
	frappe.db.set_value("AI Agent Configuration", CONFIG_NAME, "system_prompt", renamed(prompt))
