# Copyright (c) 2026, one-fm and contributors
"""Logix's clarifier gets the trigger DocType's workflow states with their doc status."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import helpers
from processa.patches.v1_0 import logix_clarifier_names_the_doc_status as p

MAP = (
	'<bpmn:serviceTask id="clarify" aiUserPrompt="User request: {{ user_request }}"></bpmn:serviceTask>'
	'<bpmn:serviceTask id="other" aiUserPrompt="User request: {{ user_request }}"></bpmn:serviceTask>'
)


class TestLogixClarifierNamesTheDocStatus(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_build_context_passes_the_states_on(self):
		code = p.build_context(p.KEYS_OLD + "\n")
		self.assertIn("'workflow_states'", code)
		self.assertEqual(p.build_context(code), code)

	def test_only_the_clarify_prompt_lists_the_states(self):
		xml = p.clarify_prompt(MAP)
		self.assertEqual(xml.count("workflow_states"), 2)
		self.assertNotIn("workflow_states", xml.split('id="other"')[1])
		self.assertEqual(p.clarify_prompt(xml), xml)

	def test_the_states_of_the_trigger_doctype_workflow_carry_their_doc_status(self):
		workflow = frappe.get_doc(
			{
				"doctype": "Workflow",
				"workflow_name": "Logix Doc Status Test",
				"document_type": "ToDo",
				"is_active": 1,
				"workflow_state_field": "workflow_state",
				"states": [
					{"state": "Draft", "doc_status": "0", "allow_edit": "System Manager"},
					{"state": "Approved", "doc_status": "0", "allow_edit": "System Manager"},
				],
				"transitions": [
					{
						"state": "Draft",
						"action": "Approve",
						"next_state": "Approved",
						"allowed": "System Manager",
					}
				],
			}
		)
		for state in ("Draft", "Approved"):
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert()
		if not frappe.db.exists("Workflow Action Master", "Approve"):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": "Approve"}).insert()
		workflow.insert()
		model = frappe.new_doc("BPMN Process Model")
		model.update(
			{
				"name": "Doc Status Map - v1",
				"title": "Doc Status Map - v1",
				"process_id": "doc_status_map",
				"version": 1,
			}
		)
		model.trigger_doctype = "ToDo"
		model.bpmn_xml = (
			'<?xml version="1.0" encoding="UTF-8"?>'
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
			'<bpmn:process id="doc_status_map" isExecutable="true" /></bpmn:definitions>'
		)
		model.insert()
		self.assertEqual(
			helpers.workflow_states("Doc Status Map - v1"),
			["Draft (doc status 0)", "Approved (doc status 0)"],
		)
		self.assertEqual(helpers.workflow_states(None), [])
