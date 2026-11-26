# Copyright (c) 2026, one-fm and contributors
"""Generate Process and Modify Process may call the Libraries box helpers once the patch has run."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.patches.v1_0 import prosally_libraries_box_approval as move

PROCESS = "ProsAlly Box Test"
IMPORT = "from processa.ai_agent_registry.definitions.prosally.tools_subprocess import put_back_libraries, take_out_libraries\n"
SCRIPTS = {"generate_process": move.GENERATE_SCRIPT, "modify_process": move.MODIFY_SCRIPT}


def _map_xml():
	tasks = "".join(
		f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{name}" />'
		for task_id, name in SCRIPTS.items()
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		f'<bpmn:process id="prosally_box_test" isExecutable="true">{tasks}</bpmn:process></bpmn:definitions>'
	)


class TestProsAllyLibrariesBoxApproval(FrappeTestCase):
	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": "x",
					"process_owner": "Administrator",
				}
			).insert()
		for name in SCRIPTS.values():
			if frappe.db.exists("Server Script", name):
				frappe.db.set_value(
					"Server Script", name, "script", IMPORT + "xml, kept = take_out_libraries(xml)\n"
				)
			else:
				frappe.get_doc(
					{
						"doctype": "Server Script",
						"name": name,
						"script_type": "API",
						"api_method": frappe.scrub(name),
						"script": IMPORT + "xml, kept = take_out_libraries(xml)\n",
					}
				).db_insert()
		if frappe.db.exists("BPMN Process Model", move.MODEL_NAME):
			frappe.db.set_value(
				"BPMN Process Model", move.MODEL_NAME, {"bpmn_xml": _map_xml(), "process_name": PROCESS}
			)
		else:
			frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"name": move.MODEL_NAME,
					"title": move.MODEL_NAME,
					"process_id": "prosally_box_test",
					"version": 1,
					"bpmn_xml": _map_xml(),
					"process_name": PROCESS,
				}
			).db_insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_helpers_need_no_approval_after_the_patch_and_a_second_run_adds_nothing(self):
		self.assertTrue(collect_script_security_violations(_map_xml(), PROCESS))
		move.execute()
		move.execute()
		self.assertEqual(collect_script_security_violations(_map_xml(), PROCESS), [])
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertEqual(sorted(approved), sorted(SCRIPTS))
