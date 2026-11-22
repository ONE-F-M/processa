import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api import instances


class TestOldPathOverrides(FrappeTestCase):
	def test_the_helpdesk_ticket_calls_reach_processa(self):
		for name in ("get_active_bpmn_tasks", "complete_task"):
			target = frappe.override_whitelisted_method(f"one_bpmn.api.instance_api.{name}")
			self.assertEqual(target, f"processa.api.instances.{name}")
			self.assertIs(frappe.get_attr(target), getattr(instances, name))
			self.assertIn(getattr(instances, name), frappe.whitelisted)
