# Copyright (c) 2026, one-fm and contributors
"""The Frontend Agent configuration prompt stops naming one_bpmn, since the map copies its prompt from there."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_evals.tests.factories import make_agent_configuration
from processa.patches.v1_0 import frontend_agent_config_names_processa as p

PROMPT = (
	"You are the Frontend Agent. the Processa Vue application under one_bpmn/spiff/src, Frappe desk JavaScript.\n"
	"a folder inside an app is not an app: spiff/ lives inside one_bpmn, so target_app is one_bpmn.\n"
	"Ours - one_fm, one_bpmn, onefm_mcp, frappe_agile, onefm_sso."
)


class TestFrontendAgentConfigNamesProcessa(FrappeTestCase):
	def test_the_configuration_prompt_is_renamed(self):
		config = make_agent_configuration(system_prompt=PROMPT)
		with patch.object(p, "CONFIG_NAME", config.name):
			p.execute()
		prompt = frappe.db.get_value("AI Agent Configuration", config.name, "system_prompt")
		self.assertNotIn("one_bpmn", prompt)
		self.assertIn("under processa/frontend/src", prompt)
		self.assertIn("frontend/ lives inside processa, so target_app is processa.", prompt)
		self.assertIn("one_fm, processa, onefm_mcp", prompt)

	def test_a_missing_configuration_is_skipped(self):
		with patch.object(p, "CONFIG_NAME", "_Test No Such Agent"):
			p.execute()
		self.assertFalse(frappe.db.exists("AI Agent Configuration", "_Test No Such Agent"))
