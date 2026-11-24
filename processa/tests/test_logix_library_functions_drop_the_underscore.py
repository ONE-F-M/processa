# Copyright (c) 2026, one-fm and contributors
"""Logix's writer is told to drop a leading underscore when it moves a function into a library."""

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_library_functions_drop_the_underscore as p

MAP = (
	f'<bpmn:serviceTask id="other" aiUserPrompt="{p.OLD}"></bpmn:serviceTask>'
	f'<bpmn:serviceTask id="write_script" aiUserPrompt="library above, {p.OLD} Otherwise"></bpmn:serviceTask>'
)


class TestLogixLibraryFunctionsDropTheUnderscore(FrappeTestCase):
	def test_only_the_write_script_sentence_changes_once(self):
		xml = p.writer_prompt(MAP)
		head, writer = xml.split('id="write_script"')
		self.assertIn(p.OLD, head)
		self.assertIn(p.NEW, writer)
		self.assertNotIn(p.OLD, writer)
		self.assertEqual(p.writer_prompt(xml), xml)
