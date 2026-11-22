# Copyright (c) 2026, one-fm and contributors
"""The approve-an-invoice-under-500 Logix case expects Apply Workflow."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_invoice_case_expects_apply_workflow as p


class TestLogixInvoiceCaseExpectsApplyWorkflow(FrappeTestCase):
	def test_the_case_expects_apply_workflow_and_no_script(self):
		case = frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"title": p.OLD_TITLE,
				"expected_tool_calls": [{"call_order": 1, "tool_name": "write_script"}],
				"assertions": [{"assertion_type": "no_tool_call", "value": "clarify", "pass_threshold": 4}],
			}
		)
		p.expect_apply_workflow(case)
		self.assertEqual(case.title, p.TITLE)
		self.assertEqual(case.expected_tool_calls, [])
		pairs = [(d.assertion_type, d.value) for d in case.assertions]
		self.assertIn(("regex", "(?i)apply workflow"), pairs)
		self.assertIn(("no_tool_call", "write_script, write_agent_tool"), pairs)
		self.assertNotIn(("no_tool_call", "clarify"), pairs)
		self.assertEqual({d.pass_threshold for d in case.assertions}, {4})
