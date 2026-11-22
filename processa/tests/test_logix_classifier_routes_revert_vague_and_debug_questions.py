# Copyright (c) 2026, one-fm and contributors
"""Logix's prompts carry the routing rules the Baseline cases expect."""

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_classifier_routes_revert_vague_and_debug_questions as p


class TestLogixClassifierRoutes(FrappeTestCase):
	def test_each_rule_is_added_once(self):
		prompt = p.with_rule("You are an intent classifier.", p.CLASSIFIER)
		self.assertIn('is REVERT and next = "finalize"', prompt)
		self.assertIn('"can you generate a script for me?"', prompt)
		self.assertEqual(p.with_rule(prompt, p.CLASSIFIER), prompt)

	def test_every_agent_that_routes_or_writes_gets_a_rule(self):
		self.assertEqual(
			set(p.RULES),
			{
				"logix_agent",
				"logix_intent_classifier",
				"logix_clarifier",
				"logix_script_writer",
				"logix_tool_writer",
			},
		)
