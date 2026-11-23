# Copyright (c) 2026, one-fm and contributors
"""The explain-the-script Logix case lets the writer answer in words."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_explain_case_lets_the_writer_answer as p


class TestLogixExplainCaseLetsTheWriterAnswer(FrappeTestCase):
	def test_the_case_expects_the_writer_and_no_code_or_diff(self):
		case = frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"title": p.CASE_TITLE,
				"expected_tool_calls": [{"call_order": 1, "tool_name": "classify_intent"}],
				"assertions": [
					{"assertion_type": "no_tool_call", "value": "write_script", "pass_threshold": 4}
				],
			}
		)
		p.let_the_writer_answer(case)
		self.assertEqual([d.tool_name for d in case.expected_tool_calls], list(p.CALLS))
		values = [d.value for d in case.assertions]
		self.assertNotIn("write_script", values)
		self.assertTrue(any('"path": "diff"' in v for v in values))
