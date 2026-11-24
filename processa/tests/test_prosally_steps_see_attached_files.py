# Copyright (c) 2026, one-fm and contributors
"""The patch makes ProsAlly's Build Context keep the turn's files and each model step send them."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import prosally_steps_see_attached_files as patch_module


def _script_name(pattern):
	return frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")


class TestProsAllyStepsSeeAttachedFiles(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _seed(self, pattern, body):
		name = _script_name(pattern)
		if not name:
			self.skipTest(f"no Server Script like {pattern} on this site")
		frappe.db.set_value("Server Script", name, "script", body)
		return name

	def test_each_step_passes_the_turns_files(self):
		names = {}
		for pattern, edits in patch_module.SCRIPTS.items():
			anchors = [anchor for anchor, _ in edits]
			body = "turn = {}\n" + "".join(f"raw_{i} = {a}\n" for i, a in enumerate(anchors))
			if pattern == "ProsAlly%Build Context":
				body = "set_turn(conversation_id, {\n" + anchors[0] + "})\n"
			names[pattern] = self._seed(pattern, body)
		patch_module.execute()
		patch_module.execute()
		for pattern, edits in patch_module.SCRIPTS.items():
			script = frappe.db.get_value("Server Script", names[pattern], "script")
			for _, replacement in edits:
				self.assertEqual(script.count(replacement), 1, pattern)
		self.assertIn(
			'"files": task_data.get("files") or []',
			frappe.db.get_value("Server Script", names["ProsAlly%Build Context"], "script"),
		)

	def test_a_script_whose_anchor_moved_is_left_as_it_is(self):
		name = self._seed("ProsAlly%Tool Confirm", "raw = something_else()\n")
		patch_module.execute()
		self.assertEqual(frappe.db.get_value("Server Script", name, "script"), "raw = something_else()\n")
		self.assertTrue(
			frappe.db.exists("Error Log", {"method": "prosally_steps_see_attached_files: anchor not found"})
		)
