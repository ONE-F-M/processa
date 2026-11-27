"""Native Submit, Cancel and Delete are withdrawn from DocTypes Processa runs."""

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.boot import boot_session
from processa.processa_engine.triggers import guard_bpmn_document

CONTROLLED = "processa.processa_engine.instances.listing.get_processa_controlled_doctypes"


def _doc(doctype="Note"):
	return frappe._dict(doctype=doctype, name="PROBE-0001")


class TestNativeActionGuard(FrappeTestCase):
	def test_submit_and_cancel_are_blocked_without_a_live_instance(self):
		with patch(CONTROLLED, return_value=["Note"]):
			for method in ("before_submit", "before_cancel", "before_workflow_action"):
				with self.assertRaises(frappe.ValidationError):
					guard_bpmn_document(_doc(), method)

	def test_engine_action_is_allowed(self):
		frappe.flags.bpmn_engine_action = True
		self.addCleanup(setattr, frappe.flags, "bpmn_engine_action", False)
		with patch(CONTROLLED, return_value=["Note"]):
			guard_bpmn_document(_doc(), "before_submit")

	def test_doctype_outside_processa_is_unaffected(self):
		with patch(CONTROLLED, return_value=["Blog Post"]):
			guard_bpmn_document(_doc(), "before_submit")

	def test_patches_are_allowed(self):
		frappe.flags.in_patch = True
		self.addCleanup(setattr, frappe.flags, "in_patch", False)
		with patch(CONTROLLED, return_value=["Note"]):
			guard_bpmn_document(_doc(), "before_submit")


class TestListActionsContract(FrappeTestCase):
	def test_boot_carries_the_controlled_doctypes(self):
		bootinfo = frappe._dict()
		with patch("processa.boot.get_processa_controlled_doctypes", return_value=["Note"]):
			boot_session(bootinfo)
		self.assertEqual(bootinfo.processa_doctypes, ["Note"])

	def test_list_script_removes_the_three_native_items_and_is_loaded(self):
		app = Path(frappe.get_app_path("processa"))
		source = (app / "public" / "js" / "bpmn_list_actions.js").read_text()
		self.assertIn('["Submit", "Cancel", "Delete"]', source)
		self.assertIn("frappe.boot.processa_doctypes", source)
		self.assertIn("bpmn_list_actions.js", (app / "hooks.py").read_text())

	def test_list_script_defers_to_frappe_outside_processa(self):
		"""A DocType Processa does not run keeps Frappe's own menu, workflow items included.

		Each of the three overrides has to hand back to the original, so a doctype that carries a
		Frappe Workflow and no process implementation behaves exactly as it did before this script.
		"""
		source = (
			Path(frappe.get_app_path("processa")) / "public" / "js" / "bpmn_list_actions.js"
		).read_text()
		self.assertIn("if (!is_processa_doctype(this.doctype)) return items;", source)
		self.assertIn("return _original_get_workflow_action_menu_items.call(this);", source)
		self.assertIn("return _original_toggle_workflow_actions.call(this);", source)

	def test_controlled_doctypes_need_an_active_model(self):
		"""The gate the script reads lists only doctypes an active model runs, so a doctype whose
		model is inactive keeps its native behaviour."""
		from processa.processa_engine.instances import listing

		rows = [frappe._dict(parent="MODEL-OFF", doctype_name="Note")]
		with (
			patch.object(frappe, "get_all", side_effect=[rows, [], []]),
			patch.object(frappe.cache(), "get_value", return_value=None),
			patch.object(frappe.cache(), "set_value"),
		):
			self.assertEqual(listing.get_processa_controlled_doctypes(), [])
