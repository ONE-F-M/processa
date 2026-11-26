# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Gateway conditions test a value a step of the same map sets, written in Python."""

from processa.tests.library import library
import xml.etree.ElementTree as ET

from frappe.tests.utils import FrappeTestCase

describe_task_config = library("prosally_lib_map_xml.py").describe_task_config
from processa.api.process_maps import validate_bpmn_readiness
from processa.processa_engine.compiler.deploy_warnings import gateway_condition_gaps

MAP = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="conditions" isExecutable="true">
		<bpmn:startEvent id="start" spiffworkflow:triggerDoctype="ToDo" />
		{step}
		<bpmn:exclusiveGateway id="gw" name="Decision" default="no" />
		<bpmn:endEvent id="end_yes" />
		<bpmn:endEvent id="end_no" />
		<bpmn:sequenceFlow id="f0" sourceRef="start" targetRef="step" />
		<bpmn:sequenceFlow id="f1" sourceRef="step" targetRef="gw" />
		<bpmn:sequenceFlow id="yes" sourceRef="gw" targetRef="end_yes">
			<bpmn:conditionExpression>{condition}</bpmn:conditionExpression>
		</bpmn:sequenceFlow>
		<bpmn:sequenceFlow id="no" sourceRef="gw" targetRef="end_no" />
	</bpmn:process>
</bpmn:definitions>"""

REVIEW = (
	'<bpmn:userTask id="step" name="Review" spiffworkflow:targetDoctype="ToDo" '
	'spiffworkflow:taskActions="[{&quot;action&quot;:&quot;Approve&quot;},{&quot;action&quot;:&quot;Reject&quot;}]" />'
)
REVIEW_WITHOUT_ACTIONS = '<bpmn:userTask id="step" name="Review" />'
CHECK_INLINE = (
	'<bpmn:scriptTask id="step" name="Validate Overlap">'
	'<bpmn:script>result["has_overlap"] = False</bpmn:script></bpmn:scriptTask>'
)
CHECK_UNBOUND = '<bpmn:scriptTask id="step" name="Validate Overlap" />'


def _gaps(step: str, condition: str) -> list:
	return [message for _id, message in gateway_condition_gaps(ET.fromstring(MAP.format(step=step, condition=condition).encode()))]


class TestAfterAUserTask(FrappeTestCase):
	def test_an_action_of_the_task_routes(self):
		self.assertEqual(_gaps(REVIEW, "action == 'Approve'"), [])

	def test_an_action_the_task_lacks_is_named_with_its_actions(self):
		self.assertEqual(_gaps(REVIEW, "action == 'Approved'"), ["'Approved' is not an action of Review. Its actions: Approve, Reject."])

	def test_a_flag_no_step_sets_asks_for_the_action(self):
		self.assertIn('"approved == True" does not test the action taken on Review', _gaps(REVIEW, "approved == True")[0])

	def test_a_task_without_actions_is_named(self):
		self.assertIn("Review has no actions, so action is never set", _gaps(REVIEW_WITHOUT_ACTIONS, "action == 'Approve'")[0])

	def test_a_field_of_the_document_routes(self):
		self.assertEqual(_gaps(REVIEW, "status == 'Open'"), [])


class TestAfterAScriptTask(FrappeTestCase):
	def test_a_key_the_script_sets_routes(self):
		self.assertEqual(_gaps(CHECK_INLINE, "has_overlap == True"), [])

	def test_a_key_the_script_never_sets_is_named(self):
		self.assertIn('never sets result["limit_exceeded"]', _gaps(CHECK_INLINE, "limit_exceeded == True")[0])

	def test_a_script_that_does_not_parse_is_named(self):
		step = '<bpmn:scriptTask id="step" name="Validate Overlap"><bpmn:script>result["x" = 1</bpmn:script></bpmn:scriptTask>'
		self.assertIn("Its script is not valid Python", _gaps(step, "x == True")[0])

	def test_a_task_with_no_script_says_which_key_it_must_set(self):
		self.assertIn('Its script must set result["has_overlap"]', _gaps(CHECK_UNBOUND, "has_overlap == True")[0])


class TestPython(FrappeTestCase):
	def test_javascript_spellings_are_named(self):
		self.assertIn("uses true, which Python does not know", _gaps(REVIEW, "action == 'Approve' and true")[0])

	def test_doc_is_named_with_the_field_to_write(self):
		self.assertIn("for example status", _gaps(REVIEW, "doc.status == 'Open'")[0])

	def test_an_expression_that_does_not_parse_is_named(self):
		self.assertIn("is not a Python expression", _gaps(REVIEW, "action == 'Approve' &amp;&amp; x")[0])


class TestCheckSteps(FrappeTestCase):
	def test_a_check_with_no_decision_after_it_is_named(self):
		xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d"><bpmn:process id="p">'
			'<bpmn:scriptTask id="v" name="Validate Daily Limit" /><bpmn:endEvent id="e" />'
			'<bpmn:sequenceFlow id="f" sourceRef="v" targetRef="e" name="Within Daily Limit" /></bpmn:process></bpmn:definitions>'
		)
		gaps = gateway_condition_gaps(ET.fromstring(xml.encode()))
		self.assertEqual(gaps[0][0], "v")
		self.assertIn("no decision follows it", gaps[0][1])

	def test_a_check_followed_by_a_decision_is_fine(self):
		self.assertEqual(_gaps(CHECK_INLINE, "has_overlap == True"), [])


class TestWhereItShows(FrappeTestCase):
	def test_the_readiness_check_warns_naming_the_gateway(self):
		result = validate_bpmn_readiness(MAP.format(step=REVIEW, condition="approved == true"))
		conditions = next(c for c in result["categories"] if c["label"] == "Gateway Conditions")
		self.assertEqual(conditions["items"][0]["name"], "Decision")
		self.assertEqual(conditions["items"][0]["type"], "warning")
		self.assertIn("uses true", conditions["items"][0]["detail"])

	def test_the_reply_names_a_new_gap_and_not_one_already_there(self):
		xml = MAP.format(step=REVIEW, condition="action == 'Approved'")
		self.assertIn("- Decision: 'Approved' is not an action of Review.", describe_task_config(xml))
		self.assertNotIn("Decision:", describe_task_config(xml, xml))
