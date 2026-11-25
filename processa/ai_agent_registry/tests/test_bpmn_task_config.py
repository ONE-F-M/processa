# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Task configuration on a generated diagram.

A generated Service Task used to carry a name and nothing else, so the value of
this module is entirely in what it writes onto the canvas and what it refuses to
write. These tests are shaped around the ways that goes wrong: a state that does
not exist, a setting borrowed from a different Service Type, a document status
the model asserted rather than looked up.
"""

import json
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.provisioning.bpmn_task_config import (
	normalise_task_actions,
	resolve_ir_config,
	resolve_node_attrs,
)

# A workflow shaped like the real Visa Request one, so the derivation tests do
# not depend on that record still existing.
VISA_STATES = [
	{"state": "Draft", "doc_status": "0", "allow_edit": "Recruiter"},
	{"state": "Pending GRD Manager Approval", "doc_status": "0", "allow_edit": "GRD Manager"},
	{"state": "Completed", "doc_status": "1", "allow_edit": "Recruiter"},
]


def _service(config, node_id="task_1"):
	return {"id": node_id, "type": "serviceTask", "name": "A step", "config": config}


def _user(config, node_id="task_u"):
	return {"id": node_id, "type": "userTask", "name": "A step", "config": config}


class ConfigCase(FrappeTestCase):
	def setUp(self):
		self._states = patch(
			"processa.ai_agent_registry.provisioning.bpmn_task_config.workflow_states", return_value=VISA_STATES
		)
		self._states.start()
		self.addCleanup(self._states.stop)


class TestApplyWorkflow(ConfigCase):
	def test_it_writes_the_attributes_the_panel_reads(self):
		attrs, problems = resolve_node_attrs(_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Pending GRD Manager Approval",
		}))
		self.assertEqual(problems, [])
		self.assertEqual(attrs["serviceType"], "apply_workflow")
		self.assertEqual(attrs["serviceTargetDoctype"], "Visa Request")
		self.assertEqual(attrs["workflowState"], "Pending GRD Manager Approval")

	def test_document_status_is_read_off_the_workflow_not_the_model(self):
		"""The status of a state is a fact about the workflow. Asking a model to
		restate it is how a diagram ends up saying Draft is submitted."""
		attrs, _ = resolve_node_attrs(_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Completed",
		}))
		self.assertEqual(attrs["docStatus"], "1")
		self.assertEqual(attrs["onlyAllowEdit"], "Recruiter")

	def test_a_model_supplied_status_is_overridden(self):
		attrs, _ = resolve_node_attrs(_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Draft",
			"docStatus": "2",
			"onlyAllowEdit": "Whoever",
		}))
		self.assertEqual(attrs["docStatus"], "0")
		self.assertEqual(attrs["onlyAllowEdit"], "Recruiter")

	def test_an_invented_state_is_reported_with_the_real_ones(self):
		"""The repair loop can only fix what it is told, so the message has to
		carry the states that do exist."""
		attrs, problems = resolve_node_attrs(_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Pending GRD Approval",
		}))
		self.assertEqual(len(problems), 1)
		self.assertIn("Pending GRD Manager Approval", problems[0]["message"])
		self.assertEqual(problems[0]["elementId"], "task_1")
		self.assertNotIn("docStatus", attrs)

	def test_a_doctype_with_no_workflow_and_no_workflow_state_field_is_named(self):
		with patch("processa.ai_agent_registry.provisioning.bpmn_task_config.workflow_states", return_value=[]):
			_, problems = resolve_node_attrs(_service({
				"serviceType": "apply_workflow",
				"serviceTargetDoctype": "ToDo",
				"workflowState": "Draft",
			}))
		self.assertEqual(len(problems), 1)
		self.assertIn("ToDo has no active Workflow and no workflow_state field", problems[0]["message"])

	def test_a_state_that_is_not_a_workflow_state_is_reported(self):
		with patch("processa.ai_agent_registry.provisioning.bpmn_task_config.workflow_states", return_value=[]):
			_, problems = resolve_node_attrs(_service({
				"serviceType": "apply_workflow",
				"serviceTargetDoctype": "Workflow Action",
				"workflowState": "Nowhere State",
			}))
		self.assertIn("'Nowhere State' is not a Workflow State", problems[0]["message"])

	def test_a_doctype_that_does_not_exist_is_reported(self):
		with patch("processa.ai_agent_registry.provisioning.bpmn_task_config.workflow_states", return_value=[]):
			_, problems = resolve_node_attrs(_service({
				"serviceType": "apply_workflow",
				"serviceTargetDoctype": "Some DocType",
				"workflowState": "Anything",
			}))
		self.assertIn("'Some DocType' is not a DocType", problems[0]["message"])


class TestUpdateFieldValues(ConfigCase):
	def _rows(self, rows):
		return resolve_node_attrs(_service({
			"serviceType": "update_field",
			"updateFieldDoctype": "ToDo",
			"updateFieldRows": rows,
		}))

	def test_a_select_value_outside_the_options_is_left_out_with_the_options(self):
		attrs, problems = self._rows([{"field": "status", "value": "Pre-Start"}, {"field": "priority", "value": "High"}])
		self.assertEqual(json.loads(attrs["updateFieldRows"]), [{"field": "priority", "value": "High"}])
		self.assertEqual(len(problems), 1)
		self.assertIn("'Pre-Start' is not an option of status on ToDo", problems[0]["message"])
		self.assertIn("Open, Closed, Cancelled", problems[0]["message"])

	def test_a_description_of_a_value_points_at_a_script_task(self):
		attrs, problems = self._rows([{"field": "date", "value": "computed"}])
		self.assertNotIn("updateFieldRows", attrs)
		self.assertIn("Script Task", problems[0]["message"])

	def test_a_link_value_that_is_not_a_record_is_left_out(self):
		_, problems = self._rows([{"field": "allocated_to", "value": "routed_if_empty"}])
		self.assertIn("'routed_if_empty' is not a User", problems[0]["message"])

	def test_the_readiness_check_warns_with_the_step_field_and_value(self):
		from processa.api.process_maps import validate_bpmn_readiness

		rows = json.dumps([{"field": "status", "value": "Fail"}]).replace('"', "&quot;")
		xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
			'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">'
			'<bpmn:process id="p" isExecutable="true"><bpmn:serviceTask id="mark" name="Mark Failed" '
			f'spiffworkflow:serviceType="update_field" spiffworkflow:updateFieldDoctype="ToDo" spiffworkflow:updateFieldRows="{rows}" />'
			"</bpmn:process></bpmn:definitions>"
		)
		values = next(c for c in validate_bpmn_readiness(xml)["categories"] if c["label"] == "Field Values")
		self.assertEqual(values["items"][0]["name"], "Mark Failed")
		self.assertEqual(values["items"][0]["type"], "warning")
		self.assertIn("'Fail' is not an option of status on ToDo", values["items"][0]["detail"])

	def test_rows_that_are_not_a_list_are_dropped_and_reported(self):
		attrs, problems = self._rows({"field": "status", "value": "Open"})
		self.assertNotIn("updateFieldRows", attrs)
		self.assertIn("must be a list", problems[0]["message"])

	def test_a_reference_to_a_name_the_render_lacks_is_left_out(self):
		attrs, problems = self._rows([{"field": "description", "value": "{{ sla_trigger_time }}"}])
		self.assertNotIn("updateFieldRows", attrs)
		self.assertIn("Write {{ doc.sla_trigger_time }}", problems[0]["message"])

	def test_a_literal_a_reference_and_now_are_written(self):
		rows = [
			{"field": "status", "value": "Closed"},
			{"field": "allocated_to", "value": "{{ doc.owner }}"},
			{"field": "date", "value": "now"},
		]
		attrs, problems = self._rows(rows)
		self.assertEqual(problems, [])
		self.assertEqual(json.loads(attrs["updateFieldRows"]), rows)


class TestServiceTypeBoundaries(ConfigCase):
	def test_an_unknown_service_type_writes_nothing(self):
		attrs, problems = resolve_node_attrs(_service({"serviceType": "teleport"}))
		self.assertEqual(attrs, {})
		self.assertIn("apply_workflow", problems[0]["message"])

	def test_a_setting_from_another_service_type_is_dropped(self):
		"""emailSubject is real, just not here — writing it would put a setting
		on the canvas that the panel will never show."""
		attrs, problems = resolve_node_attrs(_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Draft",
			"emailSubject": "Hello",
		}))
		self.assertNotIn("emailSubject", attrs)
		self.assertTrue(any("emailSubject" in p["message"] for p in problems))

	def test_a_nearly_right_key_is_told_the_right_one(self):
		_, problems = resolve_node_attrs(_service({
			"serviceType": "apply_workflow", "doctype": "Visa Request",
		}))
		self.assertTrue(any("serviceTargetDoctype" in p["message"] for p in problems))

	def test_each_service_type_keeps_its_own_settings(self):
		attrs, problems = resolve_node_attrs(_service({
			"serviceType": "send_email",
			"emailSubject": "Visa approved",
			"emailTo": "a@b.com",
			"emailUseDoctype": True,
		}))
		self.assertEqual(problems, [])
		self.assertEqual(attrs["emailSubject"], "Visa approved")
		# Checkboxes are stored as the string the panel reads back.
		self.assertEqual(attrs["emailUseDoctype"], "true")


class TestUserTaskAssignment(ConfigCase):
	def test_assignment_and_actions_are_written(self):
		attrs, problems = resolve_node_attrs(_user({
			"targetDoctype": "Visa Request",
			"assigneeMode": "DocField",
			"assigneeDocfield": "grd_manager",
			"taskActions": [
				{"action": "Approve", "confirmTransition": True, "requireDigitalSignature": True},
				{"action": "Reject", "confirmTransition": True},
			],
		}))
		self.assertEqual(problems, [])
		self.assertEqual(attrs["assigneeMode"], "DocField")
		self.assertEqual(
			attrs["taskActions"],
			'[{"action":"Approve","confirmTransition":"true","requireDigitalSignature":"true"},'
			'{"action":"Reject","confirmTransition":"true"}]',
		)

	def test_a_mode_without_its_field_is_reported(self):
		"""DocField with no fieldname assigns the task to nobody, and that is
		only discovered when someone is waiting for it at runtime."""
		_, problems = resolve_node_attrs(_user({
			"targetDoctype": "Visa Request", "assigneeMode": "DocField",
		}))
		self.assertTrue(any("assigneeDocfield" in p["message"] for p in problems))

	def test_an_unknown_mode_is_reported(self):
		_, problems = resolve_node_attrs(_user({"assigneeMode": "Whoever Is Free"}))
		self.assertTrue(any("Round Robin" in p["message"] for p in problems))

	def test_round_robin_needs_no_companion_field(self):
		_, problems = resolve_node_attrs(_user({"assigneeMode": "Round Robin"}))
		self.assertEqual(problems, [])


class TestTaskActionShapes(FrappeTestCase):
	def test_plain_names_become_rows(self):
		self.assertEqual(
			normalise_task_actions(["Approve", "Reject"]),
			'[{"action":"Approve"},{"action":"Reject"}]',
		)

	def test_a_comma_separated_string_is_accepted(self):
		"""The panel's own legacy format, so a modify turn that reads one back
		out of an existing diagram round-trips."""
		self.assertEqual(
			normalise_task_actions("Approve, Reject"),
			'[{"action":"Approve"},{"action":"Reject"}]',
		)

	def test_nothing_in_nothing_out(self):
		for empty in (None, "", [], "   "):
			self.assertEqual(normalise_task_actions(empty), "")

	def test_a_nameless_action_is_dropped(self):
		self.assertEqual(normalise_task_actions([{"confirmTransition": True}]), "")


class TestIrResolution(ConfigCase):
	def test_config_becomes_attrs_and_the_compiler_never_sees_config(self):
		ir = {"nodes": [_service({
			"serviceType": "apply_workflow",
			"serviceTargetDoctype": "Visa Request",
			"workflowState": "Draft",
		})]}
		problems = resolve_ir_config(ir)
		self.assertEqual(problems, [])
		self.assertNotIn("config", ir["nodes"][0])
		self.assertEqual(ir["nodes"][0]["attrs"]["docStatus"], "0")

	def test_a_node_without_config_is_left_alone(self):
		"""Every diagram generated before this existed still has to compile."""
		ir = {"nodes": [{"id": "t", "type": "serviceTask", "name": "A step"}]}
		self.assertEqual(resolve_ir_config(ir), [])
		self.assertNotIn("attrs", ir["nodes"][0])

	def test_attrs_returned_by_a_repair_pass_are_checked_again(self):
		ir = {"nodes": [{"id": "t", "type": "serviceTask", "name": "Move to Draft", "attrs": {
			"serviceType": "apply_workflow", "serviceTargetDoctype": "ToDo", "workflowState": "Draft",
		}}]}
		with patch("processa.ai_agent_registry.provisioning.bpmn_task_config.workflow_states", return_value=[]):
			problems = resolve_ir_config(ir)
		self.assertIn("ToDo has no active Workflow and no workflow_state field", problems[0]["message"])
		self.assertEqual(ir["nodes"][0]["attrs"]["workflowState"], "Draft")

	def test_attrs_from_a_resolved_workflow_step_resolve_to_the_same(self):
		ir = {"nodes": [_service({
			"serviceType": "apply_workflow", "serviceTargetDoctype": "Visa Request", "workflowState": "Completed",
		})]}
		resolve_ir_config(ir)
		first = dict(ir["nodes"][0]["attrs"])
		self.assertEqual(resolve_ir_config(ir), [])
		self.assertEqual(ir["nodes"][0]["attrs"], first)

	def test_config_on_a_gateway_is_refused(self):
		ir = {"nodes": [{"id": "gw", "type": "exclusiveGateway", "name": "?",
		                 "config": {"serviceType": "apply_workflow"}}]}
		problems = resolve_ir_config(ir)
		self.assertTrue(problems)
		self.assertNotIn("attrs", ir["nodes"][0])


class TestStartEventTrigger(ConfigCase):
	def _start(self, config):
		return {"id": "start", "type": "startEvent", "name": "Raised", "config": config}

	def test_the_trigger_is_written(self):
		attrs, problems = resolve_node_attrs(self._start({
			"triggerDoctype": "Visa Request", "triggerType": "After Insert",
		}))
		self.assertEqual(problems, [])
		self.assertEqual(attrs, {"triggerDoctype": "Visa Request", "triggerType": "After Insert"})

	def test_an_unknown_trigger_type_is_refused_not_written(self):
		"""A trigger type the panel has no option for looks configured and
		matches nothing, so it must not reach the canvas."""
		attrs, problems = resolve_node_attrs(self._start({
			"triggerDoctype": "Visa Request", "triggerType": "On Submit",
		}))
		self.assertNotIn("triggerType", attrs)
		self.assertTrue(any("After Insert" in p["message"] for p in problems))

	def test_a_trigger_without_a_doctype_is_reported(self):
		_, problems = resolve_node_attrs(self._start({"triggerType": "After Insert"}))
		self.assertTrue(any("triggerDoctype" in p["message"] for p in problems))

	def test_a_manually_started_process_needs_no_trigger(self):
		attrs, problems = resolve_node_attrs(self._start({}))
		self.assertEqual((attrs, problems), ({}, []))
