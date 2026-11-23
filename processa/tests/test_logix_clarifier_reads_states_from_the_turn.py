# Copyright (c) 2026, one-fm and contributors
"""Logix's clarify step reads the workflow states from the turn."""

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_clarifier_reads_states_from_the_turn as p

MAP = (
	'<bpmn:serviceTask id="clarify" spiffworkflow:aiMaxTokens="512" aiUserPrompt="'
	+ p.OLD_BLOCK
	+ 'User request"></bpmn:serviceTask><bpmn:serviceTask id="write_script" spiffworkflow:aiMaxTokens="512">'
	"</bpmn:serviceTask>"
)


class TestLogixClarifierReadsStatesFromTheTurn(FrappeTestCase):
	def test_build_context_keeps_the_states_in_the_turn(self):
		code = p.build_context(p.TURN_ANCHOR)
		self.assertIn(p.TURN_LINE, code)
		self.assertEqual(p.build_context(code), code)

	def test_only_the_clarify_step_changes(self):
		xml = p.clarify(MAP)
		self.assertIn(p.NEW_BLOCK, xml)
		self.assertNotIn(p.OLD_BLOCK, xml)
		self.assertEqual(xml.count(p.NEW_TOKENS), 1)
		self.assertIn('id="write_script" spiffworkflow:aiMaxTokens="512"', xml)
		self.assertEqual(p.clarify(xml), xml)
