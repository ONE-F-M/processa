# Copyright (c) 2026, one-fm and contributors
"""The white-screen Logix case follows the debug path."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_white_screen_case_follows_the_debug_path as p


class TestLogixWhiteScreenCaseFollowsTheDebugPath(FrappeTestCase):
	def _case(self):
		return frappe._dict(
			expected_tool_calls=[
				frappe._dict(tool_name=t) for t in ("classify_intent", "debug_script", "finalize")
			],
			assertions=[
				frappe._dict(assertion_type="regex", value="\\S"),
				frappe._dict(
					assertion_type="tool_artifact",
					value='{"tool": "finalize", "path": "response", "matcher": "regex", "expected": "x"}',
				),
			],
		)

	def test_the_case_expects_debug_script_last_and_checks_the_reply(self):
		case = self._case()
		self.assertTrue(p.follow_debug_path(case))
		self.assertEqual([d.tool_name for d in case.expected_tool_calls], ["classify_intent", "debug_script"])
		self.assertEqual(
			(case.assertions[1].assertion_type, case.assertions[1].value), ("regex", p.NO_REFUSAL)
		)
		self.assertFalse(p.follow_debug_path(case))
