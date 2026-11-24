# Copyright (c) 2026, one-fm and contributors
"""The patch makes Docu's and the Connector Agent's model steps send the turn's files, approving the import."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import agent_steps_see_attached_files as patch_module

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF = "http://spiffworkflow.org/bpmn/schema/1.0/core"
CONNECTOR = "Connector Agent: Tool Draft Connector"


def _script_name(pattern):
	return frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")


def _map(script):
	return (
		f'<definitions xmlns="{BPMN}" xmlns:spiffworkflow="{SPIFF}"><process id="p">'
		f'<scriptTask id="classify_intent" name="Classify" spiffworkflow:serverScript="{script}"/>'
		f'<scriptTask id="other" spiffworkflow:serverScript="Someone Else"/><scriptTask id="plain"/></process></definitions>'
	)


class TestAgentStepsSeeAttachedFiles(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _seed(self, pattern, body):
		name = _script_name(pattern)
		if not name:
			self.skipTest(f"no Server Script like {pattern} on this site")
		frappe.db.set_value("Server Script", name, "script", body)
		return name

	def _body(self, pattern, edits):
		(import_anchor, _), (call_anchor, _) = edits
		if pattern == CONNECTOR:
			return f"def _main(task_data):\n{import_anchor}get_turn\n    raw = _adapter.{call_anchor}\n"
		return f"{import_anchor}get_turn\nturn = {{}}\nraw = _adapter.{call_anchor}\n"

	def test_each_step_sends_the_turns_files(self):
		self._seed(
			"Docu%Build Context", "set_turn(conversation_id, {\n" + patch_module.BUILD_CONTEXT[0][0] + "})\n"
		)
		names = {
			pattern: self._seed(pattern, self._body(pattern, edits))
			for pattern, edits in patch_module.STEPS.items()
		}
		with patch.object(patch_module, "approve_import"):
			patch_module.execute()
			patch_module.execute()
		for pattern, edits in patch_module.STEPS.items():
			script = frappe.db.get_value("Server Script", names[pattern], "script")
			for _, replacement in edits:
				self.assertEqual(script.count(replacement), 1, pattern)
			compile(script, pattern, "exec")
		self.assertIn(
			'**with_attachments(prompt + _feedback, turn.get("files"))',
			frappe.db.get_value("Server Script", names["Docu%Tool Edit Client Script"], "script"),
		)
		connector = frappe.db.get_value("Server Script", names[CONNECTOR], "script")
		self.assertIn('**with_attachments(_prompt, task_data.get("files"))', connector)
		self.assertIn(
			"    from processa.processa_engine.dispatch.attachments import with_attachments\n", connector
		)
		build_context = frappe.db.get_value("Server Script", _script_name("Docu%Build Context"), "script")
		self.assertEqual(build_context.count('"files": task_data.get("files") or []'), 1)

	def test_the_import_is_approved_on_each_map_task_that_runs_the_script(self):
		name = _script_name("Docu%Tool Classify Intent") or "Docu - Tool Classify Intent"
		models = [frappe._dict(process_name="Docu", bpmn_xml=_map(name))]
		with (
			patch.object(patch_module.frappe.db, "get_value", return_value="code"),
			patch.object(patch_module.frappe, "get_all", return_value=models),
			patch.object(
				patch_module, "script_task_findings", return_value=[{"name": "with_attachments"}]
			) as findings,
			patch.object(patch_module, "approve") as approve,
		):
			patch_module.approve_import(name)
		findings.assert_called_once_with("code", "Docu", "classify_intent", name)
		approve.assert_called_once_with("Docu", "classify_intent", "Classify", name)

	def test_a_task_already_covered_is_not_approved_again(self):
		models = [frappe._dict(process_name="Docu", bpmn_xml=_map("S"))]
		with (
			patch.object(patch_module.frappe.db, "get_value", return_value="code"),
			patch.object(patch_module.frappe, "get_all", return_value=models),
			patch.object(patch_module, "script_task_findings", return_value=[]),
			patch.object(patch_module, "approve") as approve,
		):
			patch_module.approve_import("S")
		approve.assert_not_called()

	def test_a_script_whose_anchor_moved_is_left_as_it_is(self):
		name = self._seed("Docu%Tool Clarify", "raw = something_else()\n")
		with patch.object(patch_module, "approve_import") as approve_import:
			patch_module.execute()
		self.assertEqual(frappe.db.get_value("Server Script", name, "script"), "raw = something_else()\n")
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": "agent_steps_see_attached_files: anchor not found"})
		)
		self.assertNotIn(name, [c.args[0] for c in approve_import.call_args_list])
