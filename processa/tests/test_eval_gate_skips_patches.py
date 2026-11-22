# Copyright (c) 2026, one-fm and contributors
"""The eval gate refuses a deploy below the pass rate, but not a patch that re-deploys an active map."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.compiler import checks

SUITE = frappe._dict(name="s1", title="Gate Suite", min_pass_rate=90)
RUN = frappe._dict(name="r1", status="Completed", pass_rate=60, total_executions=10)


class TestEvalGateSkipsPatches(FrappeTestCase):
	def _gate(self):
		with patch.object(checks.frappe, "get_list", side_effect=[[SUITE], [RUN]]):
			checks.enforce_eval_pass_rate("Gate Map - v1")

	def test_a_deploy_below_the_pass_rate_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._gate()

	def test_a_patch_is_not_refused(self):
		previous = frappe.flags.in_patch
		frappe.flags.in_patch = True
		try:
			self._gate()
		finally:
			frappe.flags.in_patch = previous
