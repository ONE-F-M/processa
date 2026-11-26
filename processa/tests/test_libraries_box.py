# Copyright (c) 2026, one-fm and contributors
"""A Libraries box: an ad-hoc sub-process marked spiffworkflow:scriptLibrary that holds library script tasks."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from processa.ai_agent_registry.definitions.logix.tools import _reviewer_system
from processa.patches.v1_0 import logix_library_script_contract as contract_patch
from processa.processa_engine import engine
from processa.processa_engine.compiler.extensions import extract_script_task_config

LIBRARIES_MAP = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:startEvent id="start"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="end" />
    <bpmn:endEvent id="end"><bpmn:incoming>f1</bpmn:incoming></bpmn:endEvent>
    <bpmn:adHocSubProcess id="libraries" name="Libraries" spiffworkflow:scriptLibrary="true">
      <bpmn:scriptTask id="lib" name="Replies" spiffworkflow:serverScript="P: Lib Replies" />
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""


class TestLibrariesBoxRun(FrappeTestCase):
	def test_instance_completes_without_running_a_library(self):
		spec_dict, subprocess_specs = engine.parse_bpmn(LIBRARIES_MAP, "P1")
		wf = engine.create_workflow(spec_dict, subprocess_specs)
		wf.do_engine_steps()

		self.assertTrue(wf.is_completed())
		ran = {t.task_spec.name for t in wf.get_tasks(state=TaskState.COMPLETED)}
		self.assertNotIn("lib", ran)
		self.assertNotIn("libraries", ran)

	def test_library_in_the_box_is_still_known_to_import_script(self):
		config = extract_script_task_config(LIBRARIES_MAP)
		self.assertEqual(config["lib"]["serverScript"], "P: Lib Replies")


class TestLogixLibraryContract(FrappeTestCase):
	def test_reviewer_uses_the_library_contract_only_for_a_library(self):
		with patch("frappe.db.get_value", side_effect=lambda doctype, name, field: f"[{name}]"):
			self.assertIn("[bpmn-library-script-contract]", _reviewer_system({}, "script_task", True))
			self.assertIn("[bpmn-script-task-contract]", _reviewer_system({}, "script_task", False))
			self.assertIn("[bpmn-agent-tool-contract]", _reviewer_system({}, "agent_tool", False))

	def test_writer_prompt_edits_apply_once(self):
		xml = (
			'<bpmn:serviceTask id="classify_intent" aiUserPrompt="**Shape kind:** {{ shape_kind }}&#10;" />'
			'<bpmn:serviceTask id="write_script" aiSystemPrompt="script_task, or `x` when it says agent_tool. Never"'
			' aiUserPrompt="**Shape kind:** {{ shape_kind }}&#10;**Script Task:**"></bpmn:serviceTask>'
		)
		once = contract_patch.writer_prompt(xml)
		self.assertIn("load `bpmn-library-script-contract` instead", once)
		self.assertIn("{% if turn.process_context.is_library %}**Is library:** yes.", once)
		self.assertEqual(once.count("**Is library:**"), 1)
		self.assertTrue(
			once.startswith(
				'<bpmn:serviceTask id="classify_intent" aiUserPrompt="**Shape kind:** {{ shape_kind }}&#10;" />'
			)
		)
		self.assertEqual(contract_patch.writer_prompt(once), once)
		self.assertEqual(contract_patch.writer_prompt("<bpmn:definitions />"), "<bpmn:definitions />")

	def test_review_script_skips_the_dry_run_for_a_library(self):
		script = (
			'_contract_skill = "bpmn-agent-tool-contract" if shape_kind == "agent_tool" else "bpmn-script-task-contract"\n'
			'if _valid and shape_kind == "script_task":\n'
			"    dry_run(code, turn)\n"
		)
		once = contract_patch.review_script(script)
		self.assertIn('_is_library = bool((turn.get("process_context") or {}).get("is_library"))', once)
		self.assertIn('"bpmn-library-script-contract" if _is_library else', once)
		self.assertIn('if _valid and shape_kind == "script_task" and not _is_library:', once)
		self.assertEqual(contract_patch.review_script(once), once)

	def test_review_script_without_the_contract_line_is_unchanged(self):
		script = 'if _valid and shape_kind == "script_task":\n    dry_run(code, turn)\n'
		self.assertEqual(contract_patch.review_script(script), script)
