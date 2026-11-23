# Copyright (c) 2026, one-fm and contributors
"""Logix's reviewer prompts and safety skill keep a network call that needs approval."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_reviewer_keeps_calls_needing_approval as p
from processa.patches.v1_0.move_domain_rules_into_skills import LOGIX_REVIEWER_PROMPT

STALE_SKILL = "\n\n".join(old for old, _new in p.SKILL_FIXES)


class TestLogixReviewerKeepsCallsNeedingApproval(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_reviewer_no_longer_rewrites_a_requests_call(self):
		text = p.reviewer_text(LOGIX_REVIEWER_PROMPT)
		self.assertNotIn("ALL blocked by the security gate", text)
		self.assertNotIn("you are the ONLY layer that catches it", text)
		self.assertIn("Keep such a call as the draft wrote it", text)
		self.assertEqual(text.count("never log it."), 1)

	def test_a_fixed_prompt_is_left_as_it_is(self):
		text = p.reviewer_text(LOGIX_REVIEWER_PROMPT)
		self.assertEqual(p.reviewer_text(text), text)

	def test_the_skill_calls_flagged_items_needing_approval(self):
		text = p.skill_text(STALE_SKILL)
		self.assertNotIn("Always rejected", text)
		self.assertNotIn("only through", text)
		self.assertIn("## Flagged, needs approval", text)
		self.assertIn("Keep a `requests` call an existing script already makes.", text)

	def test_the_reviewer_configuration_is_saved_with_the_new_rule(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": "logix_script_reviewer"}, "name")
		if not name:
			self.skipTest("no Logix reviewer configuration on this site")
		frappe.db.set_value("AI Agent Configuration", name, "system_prompt", LOGIX_REVIEWER_PROMPT)
		p.execute()
		prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt")
		self.assertNotIn("ALL blocked by the security gate", prompt)
		self.assertIn("Keep such a call as the draft wrote it", prompt)
