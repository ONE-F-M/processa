# Copyright (c) 2026, one-fm and contributors
"""A short list of operations edits a map's IR and leaves everything it does not name as it was."""

import copy
import unittest

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_pipeline, tools_review
from processa.ai_agent_registry.definitions.prosally.tools_operations import apply_operations
from processa.ai_agent_registry.definitions.prosally.tools_properties import transfer_properties


def nine_task_map() -> dict:
	"""s, t1 to t3, then a decision g: Yes runs t4 and t6 to t9 to the end, No runs t5 to a Rejected end."""
	lanes = [{"id": "staff", "name": "Staff"}, {"id": "hr", "name": "HR Officer"}]
	tasks = [
		{"id": f"t{i}", "name": f"Step {i}", "type": "userTask", "lane": "staff" if i < 5 else "hr"}
		for i in range(1, 10)
	]
	nodes = [
		{"id": "s", "name": "Asked", "type": "startEvent", "lane": "staff"},
		*tasks,
		{"id": "g", "name": "Approved?", "type": "exclusiveGateway", "lane": "staff"},
		{"id": "e", "name": "Done", "type": "endEvent", "lane": "hr"},
		{"id": "r", "name": "Rejected", "type": "endEvent", "lane": "hr"},
	]
	pairs = [
		("s", "t1"), ("t1", "t2"), ("t2", "t3"), ("t3", "g"), ("g", "t4"), ("g", "t5"), ("t5", "r"),
		("t4", "t6"), ("t6", "t7"), ("t7", "t8"), ("t8", "t9"), ("t9", "e"),
	]  # fmt: skip
	flows = [{"id": f"f_{a}_{b}", "from": a, "to": b} for a, b in pairs]
	flows[4].update({"name": "Yes", "condition": "approved == True"})
	flows[5].update({"name": "No", "default": True})
	return {"name": "Nine", "lanes": lanes, "nodes": nodes, "flows": flows}


DELETE_THREE_AND_A_GATEWAY = [
	{"op": "remove", "id": "t2"},
	{"op": "remove", "id": "t3"},
	{"op": "remove", "id": "t5"},
	{"op": "remove", "id": "g"},
	{"op": "remove", "id": "r"},
	{"op": "add", "type": "sequenceFlow", "id": "f_t1_t4", "from": "t1", "to": "t4"},
]


class TestApplyOperations(FrappeTestCase):
	def test_deleting_three_tasks_and_a_gateway_changes_nothing_else(self):
		ir = nine_task_map()

		edited, problem = apply_operations(ir, DELETE_THREE_AND_A_GATEWAY)

		self.assertEqual(problem, "")
		gone = {"t2", "t3", "t5", "g", "r"}
		self.assertEqual(edited["nodes"], [n for n in ir["nodes"] if n["id"] not in gone])
		untouched = [f for f in ir["flows"] if not {f["from"], f["to"]} & gone]
		self.assertEqual(
			[f for f in edited["flows"] if f["id"] != "f_t1_t4" and f["id"] != "f_t1_t2"], untouched
		)
		self.assertIn({"id": "f_t1_t4", "from": "t1", "to": "t4"}, edited["flows"])
		self.assertEqual(edited["lanes"], ir["lanes"])

	def test_a_step_on_a_single_path_is_taken_out_and_the_path_closes_up(self):
		edited, _problem = apply_operations(nine_task_map(), [{"op": "remove", "id": "t8"}])

		self.assertIn({"id": "f_t7_t8", "from": "t7", "to": "t9"}, edited["flows"])
		self.assertNotIn("f_t8_t9", [f["id"] for f in edited["flows"]])

	def test_a_failed_operation_names_itself_and_changes_nothing(self):
		ir = nine_task_map()
		before = copy.deepcopy(ir)

		edited, problem = apply_operations(
			ir, [{"op": "rename", "id": "t1", "name": "Fill the form"}, {"op": "remove", "id": "t99"}]
		)

		self.assertIsNone(edited)
		self.assertIn("Change 2 (remove", problem)
		self.assertIn("t99", problem)
		self.assertEqual(ir, before)

	def test_rename_and_reconnect_touch_only_what_they_name(self):
		edited, problem = apply_operations(
			nine_task_map(),
			[
				{"op": "rename", "id": "t1", "name": "Fill the form"},
				{"op": "reconnect", "id": "f_t9_e", "from": "t8"},
			],
		)

		self.assertEqual(problem, "")
		self.assertEqual(edited["nodes"][1]["name"], "Fill the form")
		self.assertIn({"id": "f_t9_e", "from": "t8", "to": "e"}, edited["flows"])

	def test_each_wrong_operation_says_why(self):
		cases = [
			({"op": "move", "id": "t1"}, "not one of add, remove, rename or reconnect"),
			({"op": "add", "type": "userTask", "id": "t1", "name": "x", "lane": "hr"}, "not used yet"),
			({"op": "add", "type": "userTask", "id": "n", "name": "x"}, "needs one of the diagram's lanes"),
			(
				{"op": "add", "type": "sequenceFlow", "id": "n", "from": "t1", "to": "nowhere"},
				"nowhere is not one",
			),
			({"op": "remove", "id": "staff"}, "still has steps"),
			({"op": "add", "type": "boundaryEvent", "id": "n"}, "not a kind of element"),
		]
		for operation, why in cases:
			with self.subTest(operation=operation):
				self.assertIn(why, apply_operations(nine_task_map(), [operation])[1])

	def test_a_diagram_without_lanes_takes_a_step_without_a_lane(self):
		ir = {
			"name": "Flat",
			"lanes": [],
			"nodes": [{"id": "s", "name": "", "type": "startEvent"}],
			"flows": [],
		}

		edited, problem = apply_operations(ir, [{"op": "add", "type": "task", "id": "t", "name": "Check"}])

		self.assertEqual(problem, "")
		self.assertIn(
			"the diagram has no lanes",
			apply_operations(ir, [{"op": "add", "type": "task", "id": "t", "lane": "x"}])[1],
		)
		self.assertEqual(edited["nodes"][-1], {"id": "t", "name": "Check", "type": "task"})


class TestOperationsThroughThePipeline(FrappeTestCase):
	"""Needs node to compile."""

	def test_the_edited_map_keeps_ids_names_conditions_and_configured_properties(self):
		compiled = tools_pipeline.compile_ir(nine_task_map())
		if not compiled.get("ok"):
			raise unittest.SkipTest("node or pipeline.mjs unavailable")
		current = compiled["xml"].replace(
			'<bpmn:userTask id="t7"',
			'<bpmn:userTask id="t7" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" spiffworkflow:assignee="kept"',
			1,
		)

		edited, problem = apply_operations(tools_review.xml_to_ir(current), DELETE_THREE_AND_A_GATEWAY)
		new_xml, removed = transfer_properties(current, tools_pipeline.compile_ir(edited)["xml"])

		self.assertEqual(problem, "")
		names = tools_pipeline.element_names(new_xml)
		for kept in ("t1", "t4", "t6", "t7", "t9", "e", "f_t4_t6", "f_t9_e"):
			self.assertEqual(names[kept], tools_pipeline.element_names(current)[kept])
		for gone in ("t2", "t3", "t5", "g", "r"):
			self.assertNotIn(gone, names)
		self.assertIn('assignee="kept"', new_xml)
		self.assertEqual(removed, [])
