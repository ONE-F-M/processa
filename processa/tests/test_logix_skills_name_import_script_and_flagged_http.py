# Copyright (c) 2026, one-fm and contributors
"""Logix's skills name import_script and _, and treat requests as needing approval."""

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_skills_name_import_script_and_flagged_http as p


class TestLogixSkillsNameImportScriptAndFlaggedHttp(FrappeTestCase):
	def test_the_script_task_contract_names_import_script_and_underscore(self):
		((old, _new),) = p.FIXES["bpmn-script-task-contract"]
		text = p.fixed("intro\n" + old + "## Reading inputs\n", p.FIXES["bpmn-script-task-contract"])
		self.assertIn("- `import_script`: loads a library script on the same map.", text)
		self.assertIn("- `_`: the translate function", text)
		self.assertEqual(p.fixed(text, p.FIXES["bpmn-script-task-contract"]), text)

	def test_the_outbound_skill_no_longer_says_requests_is_rejected(self):
		((old, _new),) = p.FIXES["frappe-outbound-http"]
		text = p.fixed("# Calling an external service\n\n" + old + "\n", p.FIXES["frappe-outbound-http"])
		self.assertNotIn("rejects the script on save", text)
		self.assertIn("cannot be deployed until they are approved", text)
