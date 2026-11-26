# Copyright (c) 2026, one-fm and contributors
"""The ProsAlly map XML helpers moved into 'ProsAlly: Lib Map XML', with xml.etree approved by the patch."""

import copy
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import (
	tools_lint,
	tools_prompts,
	tools_properties,
	tools_replies,
	tools_review,
	tools_subprocess,
	validators,
)
from processa.ai_agent_security.code_checks.script_gate import collect_script_security_violations
from processa.ai_agent_security.code_checks.script_validator import runs_code_on_import, validate_script
from processa.patches.v1_0 import prosally_ir_move_to_library as ir
from processa.patches.v1_0 import prosally_map_xml_move_to_library as move
from processa.patches.v1_0 import prosally_replies_move_to_library as replies
from processa.processa_engine.compiler.extensions import extract_script_task_config
from processa.processa_engine.engine.script_engine import make_import_script
from processa.tests.test_prosally_convert_step import HEAD, _diagram

PROCESS = "ProsAlly Map XML Test"
P = "processa.ai_agent_registry.definitions.prosally"
SCRIPTS = {
	"classify_intent": "ProsAlly XML Test Classify Intent",
	"confirm": "ProsAlly XML Test Confirm",
	"generate_process": "ProsAlly XML Test Generate Process",
	"modify_process": "ProsAlly XML Test Modify Process",
}
OLD_SCRIPTS = {
	"classify_intent": f"from {P}.tools_subprocess import find_missing_target, resolve_scope, resolve_step\nx = resolve_scope(xml, [])\n",
	"confirm": f"from {P}.tools_review import none_tasks_output\nout = none_tasks_output(xml)\n",
	"generate_process": f"from {P}.validators import validate_bpmn_xml\nfound = validate_bpmn_xml(xml)\n",
	"modify_process": (
		f"from {P}.tools_subprocess import splice_subprocess, take_out_libraries, put_back_libraries\n"
		f"from {P}.tools_properties import describe_task_config, transfer_properties\n"
		"xml, kept = take_out_libraries(xml)\n"
	),
}
CHILD = (
	f'{HEAD}<bpmn:process id="C" isExecutable="true"><bpmn:startEvent id="cs" name="Begin" />'
	'<bpmn:userTask id="ct" name="Check payslip" /><bpmn:endEvent id="ce" name="Finish" />'
	'<bpmn:sequenceFlow id="cf1" sourceRef="cs" targetRef="ct" /><bpmn:sequenceFlow id="cf2" sourceRef="ct" targetRef="ce" />'
	'</bpmn:process><bpmndi:BPMNDiagram id="cd"><bpmndi:BPMNPlane id="cp" bpmnElement="C">'
	'<bpmndi:BPMNShape id="cs_di" bpmnElement="cs"><dc:Bounds x="100" y="100" width="36" height="36"/></bpmndi:BPMNShape>'
	'<bpmndi:BPMNShape id="ct_di" bpmnElement="ct"><dc:Bounds x="200" y="80" width="100" height="80"/></bpmndi:BPMNShape>'
	'<bpmndi:BPMNShape id="ce_di" bpmnElement="ce"><dc:Bounds x="350" y="100" width="36" height="36"/></bpmndi:BPMNShape>'
	"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
)


def _map_xml():
	tasks = "".join(
		f'<bpmn:scriptTask id="{task_id}" name="{task_id}" spiffworkflow:serverScript="{name}" />'
		for task_id, name in SCRIPTS.items()
	)
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{task_id}_di" bpmnElement="{task_id}"><dc:Bounds x="{100 + 150 * i}" y="100" '
		'width="100" height="80" /></bpmndi:BPMNShape>'
		for i, task_id in enumerate(SCRIPTS)
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		f'<bpmn:process id="prosally_xml_test" isExecutable="true">{tasks}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d"><bpmndi:BPMNPlane id="p" bpmnElement="prosally_xml_test">{shapes}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestProsAllyMapXMLLibraryCode(FrappeTestCase):
	def test_the_library_only_defines_functions_and_needs_xml_etree(self):
		code = (replies.DATA / "prosally_lib_map_xml.py").read_text()
		self.assertFalse(runs_code_on_import(code))
		found = {f["name"] for f in validate_script(code).get("findings") or []}
		self.assertEqual(
			found,
			{
				"xml.etree.ElementTree",
				"processa.processa_engine.compiler.deploy_warnings.gateway_condition_gaps",
			},
		)


class TestProsAllyMapXMLLibraryOnTheMap(FrappeTestCase):
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
		for task_id, name in SCRIPTS.items():
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True)
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": frappe.scrub(name),
					"script": OLD_SCRIPTS[task_id],
				}
			).db_insert()
		if frappe.db.exists("BPMN Process Model", replies.MODEL_NAME):
			frappe.delete_doc("BPMN Process Model", replies.MODEL_NAME, force=True)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"name": replies.MODEL_NAME,
				"title": replies.MODEL_NAME,
				"process_id": "prosally_xml_test",
				"version": 1,
				"bpmn_xml": _map_xml(),
				"process_name": PROCESS,
			}
		).db_insert()
		with patch("processa.api.deploy.compile_process_model"):
			replies.execute()
			ir.execute()
			move.execute()
			move.execute()
		self.xml = frappe.db.get_value("BPMN Process Model", replies.MODEL_NAME, "bpmn_xml")
		load = make_import_script(
			frappe._dict(process_model=replies.MODEL_NAME), extract_script_task_config(self.xml)
		)
		self.lib = load(move.LIBRARY)
		self.diagram = _diagram()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def assertSame(self, name, backend, *args):
		lib_args, backend_args = copy.deepcopy(args), copy.deepcopy(args)
		self.assertEqual(getattr(self.lib, name)(*lib_args), backend(*backend_args), name)
		self.assertEqual(lib_args, backend_args, name)

	def test_the_box_holds_three_libraries_and_the_map_needs_no_approval(self):
		self.assertEqual(self.xml.count(f'id="{replies.BOX_ID}"'), 1)
		scripts = replies.task_scripts(self.xml)
		self.assertEqual(scripts["lib_map_xml"], move.LIBRARY)
		self.assertEqual(collect_script_security_violations(self.xml, PROCESS), [])
		approved = frappe.get_all(
			"Script Approval Request",
			filters={"process_name": PROCESS, "source": "Shipped by patch", "status": "Approved"},
			pluck="script_task",
		)
		self.assertEqual(sorted(approved), sorted(move.APPROVED_TASKS))

	def test_the_scripts_import_none_of_the_moved_functions(self):
		for name in SCRIPTS.values():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertEqual(script.count(move.LOAD), 1, name)
			for line in script.splitlines():
				if " import " in line:
					imported = {n.strip() for n in line.split(" import ", 1)[1].split(",")}
					self.assertFalse(imported & set(move.MOVED), line)

	def test_reading_helpers_through_import_script(self):
		texts = ["Turn Complete Payroll Clearance into a sub-process", "Make Audit Trail a sub-process"]
		self.assertSame("find_missing_target", tools_subprocess.find_missing_target, self.diagram, texts[1:])
		self.assertSame("resolve_scope", tools_subprocess.resolve_scope, self.diagram, texts)
		self.assertSame("resolve_step", tools_subprocess.resolve_step, self.diagram, texts[:1])
		self.assertSame("xml_to_ir", tools_review.xml_to_ir, CHILD)
		self.assertSame("validate_bpmn_xml", validators.validate_bpmn_xml, self.diagram)
		self.assertSame("validate_bpmn_xml", validators.validate_bpmn_xml, CHILD)
		self.assertSame("describe_task_config", tools_properties.describe_task_config, self.diagram)
		self.assertSame(
			"describe_task_config", tools_properties.describe_task_config, self.diagram, CHILD, []
		)
		self.assertSame("overwrite_warning", tools_properties.overwrite_warning, self.diagram)
		issues = [{"id": "below", "rule": "no-disconnected", "message": "not connected", "category": "error"}]
		self.assertSame("lint_findings", tools_lint.lint_findings, self.diagram, issues)

	def test_diagram_edits_through_import_script(self):
		self.assertSame(
			"convert_step_to_subprocess",
			tools_subprocess.convert_step_to_subprocess,
			self.diagram,
			"conv",
			CHILD,
		)
		converted = tools_subprocess.convert_step_to_subprocess(self.diagram, "conv", CHILD)
		self.assertSame("splice_subprocess", tools_subprocess.splice_subprocess, converted, CHILD, "conv")
		self.assertSame(
			"restore_call_activities", tools_subprocess.restore_call_activities, self.diagram, CHILD
		)
		self.assertSame("transfer_properties", tools_properties.transfer_properties, self.diagram, CHILD)
		self.assertSame(
			"transfer_properties", tools_properties.transfer_properties, self.diagram, self.diagram, ("prep",)
		)
		self.assertSame(
			"describe_flow_references", tools_replies.describe_flow_references, self.diagram, converted
		)
		self.assertSame("describe_links", tools_replies.describe_links, self.diagram, CHILD)
		ir_dict = {"nodes": [], "flows": []}
		self.assertSame(
			"keep_process_kind",
			tools_review.keep_process_kind,
			ir_dict,
			self.diagram.replace('isExecutable="true"', 'isExecutable="false"'),
		)
		self.assertSame("none_tasks_output", tools_review.none_tasks_output, self.diagram)
		self.assertSame("none_tasks_output", tools_review.none_tasks_output, "")
		self.assertSame(
			"compare_output",
			tools_review.compare_output,
			self.diagram,
			["1. Prepare\n2. Approve payslip\n3. Pay out"],
		)

	def test_libraries_box_and_prompt_through_import_script(self):
		boxed = self.xml
		self.assertSame("take_out_libraries", tools_subprocess.take_out_libraries, boxed)
		rest, kept = tools_subprocess.take_out_libraries(boxed)
		self.assertSame("put_back_libraries", tools_subprocess.put_back_libraries, rest, kept)
		cfg = {"sub_prompts": {"modify": {"prompt": "Change the diagram."}}}
		self.assertSame(
			"stage_system_prompt",
			tools_prompts.stage_system_prompt,
			cfg,
			"modify",
			"",
			{"current_xml": boxed},
		)
