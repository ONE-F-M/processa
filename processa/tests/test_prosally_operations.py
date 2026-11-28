# Copyright (c) 2026, one-fm and contributors
"""A short list of operations edits a map's IR and leaves everything it does not name as it was."""

import copy
import re
import unittest

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_pipeline
from processa.tests.library import library

apply_operations = library("prosally_lib_ir.py").apply_operations
transfer_properties = library("prosally_lib_map_xml.py").transfer_properties
map_xml = library("prosally_lib_map_xml.py")
compile_ir = library("prosally_lib_layout.py").compile_ir
describe_changes = library("prosally_lib_replies.py").describe_changes


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
		("s", "t1"),
		("t1", "t2"),
		("t2", "t3"),
		("t3", "g"),
		("g", "t4"),
		("g", "t5"),
		("t5", "r"),
		("t4", "t6"),
		("t6", "t7"),
		("t7", "t8"),
		("t8", "t9"),
		("t9", "e"),
	]
	flows = [{"id": f"f_{a}_{b}", "from": a, "to": b} for a, b in pairs]
	flows[4].update({"name": "Yes", "condition": "approved == True"})
	flows[5].update({"name": "No", "default": True})
	return {"name": "Nine", "lanes": lanes, "nodes": nodes, "flows": flows}


def expense_claim_map() -> dict:
	"""Submit, review and decide; Approved pays out in Finance, Rejected notifies the Employee."""
	lanes = [
		{"id": "employee", "name": "Employee"},
		{"id": "manager", "name": "Manager"},
		{"id": "finance", "name": "Finance"},
	]
	nodes = [
		{"id": "start", "name": "Claim Initiated", "type": "startEvent", "lane": "employee"},
		{"id": "submit", "name": "Submit Claim", "type": "task", "lane": "employee"},
		{"id": "review", "name": "Review Claim", "type": "task", "lane": "manager"},
		{"id": "gw", "name": "Approved?", "type": "exclusiveGateway", "lane": "manager"},
		{"id": "pay", "name": "Pay Out", "type": "task", "lane": "finance"},
		{"id": "notify", "name": "Notify Employee", "type": "task", "lane": "employee"},
		{"id": "paid", "name": "Claim Paid", "type": "endEvent", "lane": "finance"},
		{"id": "rejected", "name": "Claim Rejected", "type": "endEvent", "lane": "employee"},
	]
	flows = [
		{"id": "f1", "from": "start", "to": "submit", "name": "Begin"},
		{"id": "f2", "from": "submit", "to": "review", "name": "Submitted"},
		{"id": "f3", "from": "review", "to": "gw", "name": "Reviewed"},
		{"id": "f4", "from": "gw", "to": "pay", "name": "Approved", "condition": "action == 'Approve'"},
		{"id": "f5", "from": "gw", "to": "notify", "name": "Rejected", "default": True},
		{"id": "f6", "from": "pay", "to": "paid", "name": "Done"},
		{"id": "f7", "from": "notify", "to": "rejected", "name": "Done"},
	]
	return {"name": "Expense Claim Test", "executable": False, "lanes": lanes, "nodes": nodes, "flows": flows}


def drawing_clashes(xml: str) -> list:
	"""Every line that runs through a step it does not join, and every pair of lines that cross."""
	drawing = map_xml._drawing(xml)
	lines = {flow: map_xml._points(drawing["bodies"][flow]) for flow in drawing["edges"]}
	clashes = [
		(flow, step)
		for flow, points in lines.items()
		for a, b in map_xml._pairs(points)
		for step in drawing["nodes"]
		if step not in drawing["flows"][flow] and map_xml._through(a, b, drawing["shapes"][step])
	]
	names = sorted(lines)
	for i, first in enumerate(names):
		for second in names[i + 1 :]:
			if any(
				map_xml._crosses(a, b, c, d)
				for a, b in map_xml._pairs(lines[first])
				for c, d in map_xml._pairs(lines[second])
			):
				clashes.append((first, second))
	return clashes


def compiled(ir: dict) -> str:
	"""ir drawn by the node pipeline; skips the test when node is not there."""
	result = compile_ir(ir)
	if not result.get("ok"):
		raise unittest.SkipTest("node or pipeline.mjs unavailable")
	return result["xml"]


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
			({"op": "paint", "id": "t1"}, "not one of add, remove, rename, reconnect"),
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
		compiled = library("prosally_lib_layout.py").compile_ir(nine_task_map())
		if not compiled.get("ok"):
			raise unittest.SkipTest("node or pipeline.mjs unavailable")
		current = compiled["xml"].replace(
			'<bpmn:userTask id="t7"',
			'<bpmn:userTask id="t7" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" spiffworkflow:assignee="kept"',
			1,
		)

		edited, problem = apply_operations(library("prosally_lib_map_xml.py").xml_to_ir(current), DELETE_THREE_AND_A_GATEWAY)
		new_xml, removed = transfer_properties(current, library("prosally_lib_layout.py").compile_ir(edited)["xml"])

		self.assertEqual(problem, "")
		names = tools_pipeline.element_names(new_xml)
		for kept in ("t1", "t4", "t6", "t7", "t9", "e", "f_t4_t6", "f_t9_e"):
			self.assertEqual(names[kept], tools_pipeline.element_names(current)[kept])
		for gone in ("t2", "t3", "t5", "g", "r"):
			self.assertNotIn(gone, names)
		self.assertIn('assignee="kept"', new_xml)
		self.assertEqual(removed, [])


class TestTheDiagramIsReadAsItIs(FrappeTestCase):
	def test_a_gateways_default_path_survives_the_read(self):
		ir = map_xml.xml_to_ir(compiled(nine_task_map()))
		flows = {f["id"]: f for f in ir["flows"]}
		self.assertTrue(flows["f_g_t5"].get("default"))
		self.assertNotIn("default", flows["f_g_t4"])

	def test_a_name_held_only_by_the_pool_survives_an_edit(self):
		xml = re.sub(r'(<bpmn:process\b[^>]*?) name="[^"]*"', r"\1", compiled(expense_claim_map()))
		edited, _problem = apply_operations(
			map_xml.xml_to_ir(xml), [{"op": "rename", "id": "pay", "name": "Pay"}]
		)
		self.assertIn('name="Expense Claim Test"', compiled(edited))


class TestRetypeMoveAndCondition(FrappeTestCase):
	def test_retype_move_and_condition_change_only_what_they_name(self):
		ir = nine_task_map()
		edited, problem = apply_operations(
			ir,
			[
				{"op": "retype", "id": "t6", "type": "serviceTask"},
				{"op": "move", "id": "t7", "lane": "staff"},
				{"op": "set_condition", "id": "f_g_t4", "condition": "action == 'Approve'"},
			],
		)
		self.assertEqual(problem, "")
		nodes = {n["id"]: n for n in edited["nodes"]}
		self.assertEqual((nodes["t6"]["type"], nodes["t7"]["lane"]), ("serviceTask", "staff"))
		self.assertEqual(
			next(f for f in edited["flows"] if f["id"] == "f_g_t4")["condition"], "action == 'Approve'"
		)
		untouched = [n for n in ir["nodes"] if n["id"] not in ("t6", "t7")]
		self.assertEqual([n for n in edited["nodes"] if n["id"] not in ("t6", "t7")], untouched)

	def test_a_default_path_replaces_the_one_the_gateway_had(self):
		edited, _problem = apply_operations(
			nine_task_map(), [{"op": "set_condition", "id": "f_g_t4", "default": True}]
		)
		flows = {f["id"]: f for f in edited["flows"]}
		self.assertTrue(flows["f_g_t4"]["default"])
		self.assertNotIn("condition", flows["f_g_t4"])
		self.assertNotIn("default", flows["f_g_t5"])

	def test_each_new_operation_says_why_it_cannot_be_made(self):
		for ir, operation, reason in (
			(nine_task_map(), {"op": "retype", "id": "t6", "type": "teleport"}, "not a kind of step"),
			(
				nine_task_map(),
				{"op": "retype", "id": "t6", "type": "subProcess"},
				"a sub-process holds steps of its own",
			),
			(expense_claim_map(), {"op": "retype", "id": "review", "type": "userTask"}, "non-executable"),
			(
				nine_task_map(),
				{"op": "move", "id": "t6", "lane": "finance"},
				"not one of the diagram's lanes",
			),
			(nine_task_map(), {"op": "move", "id": "nobody", "lane": "hr"}, "no step with the id nobody"),
			(nine_task_map(), {"op": "set_condition", "id": "f_g_t4"}, "the condition is empty"),
			(nine_task_map(), {"op": "resize", "id": "t6"}, "retype, move, set_condition"),
		):
			with self.subTest(operation=operation):
				edited, problem = apply_operations(ir, [operation])
				self.assertIsNone(edited)
				self.assertIn(reason, problem)


class TestUntouchedShapesKeepTheirPlace(FrappeTestCase):
	def _edit(self, ir, operations):
		before = compiled(ir)
		edited, problem = apply_operations(map_xml.xml_to_ir(before), operations)
		self.assertEqual(problem, "")
		after, _removed = transfer_properties(before, compiled(edited), positions=True)
		return map_xml._drawing(before), map_xml._drawing(after), after

	def test_an_added_step_leaves_every_other_shape_where_it_was(self):
		before, after, xml = self._edit(
			nine_task_map(),
			[
				{"op": "add", "type": "userTask", "id": "t10", "name": "Extra Check", "lane": "hr"},
				{"op": "reconnect", "id": "f_t9_e", "to": "t10"},
				{"op": "add", "type": "sequenceFlow", "id": "f_t10_e", "from": "t10", "to": "e"},
			],
		)
		kept = set(before["nodes"]) & set(after["nodes"])
		self.assertEqual({k: after["shapes"][k] for k in kept}, {k: before["shapes"][k] for k in kept})
		box = after["shapes"]["t10"]
		self.assertFalse(any(map_xml._overlap(box, after["shapes"][k]) for k in kept))
		lane = after["shapes"]["hr"]
		self.assertTrue(lane[1] <= box[1] and box[1] + box[3] <= lane[1] + lane[3])
		self.assertEqual(before["bodies"]["f_s_t1"], after["bodies"]["f_s_t1"])
		self.assertNotEqual(before["bodies"]["f_t9_e"], after["bodies"]["f_t9_e"])
		self.assertEqual(set(drawing_clashes(xml)) - set(drawing_clashes(compiled(nine_task_map()))), set())

	def test_a_step_moved_to_another_lane_is_the_only_shape_that_moves(self):
		before, after, _xml = self._edit(nine_task_map(), [{"op": "move", "id": "t2", "lane": "hr"}])
		moved = {k for k in before["nodes"] if before["shapes"][k] != after["shapes"][k]}
		self.assertEqual(moved, {"t2"})
		lane = after["shapes"]["hr"]
		self.assertTrue(lane[1] <= after["shapes"]["t2"][1] <= lane[1] + lane[3])

	def test_a_step_moved_up_to_a_decision_lane_crosses_no_line_and_covers_none(self):
		before, after, xml = self._edit(
			expense_claim_map(), [{"op": "move", "id": "notify", "lane": "manager"}]
		)
		self.assertEqual(drawing_clashes(xml), [])
		self.assertEqual(
			{k for k in before["nodes"] if before["shapes"][k] != after["shapes"][k]}, {"notify"}
		)

	def test_a_rename_and_a_retype_move_nothing(self):
		before, after, _xml = self._edit(
			nine_task_map(),
			[
				{"op": "rename", "id": "t1", "name": "First"},
				{"op": "retype", "id": "t6", "type": "serviceTask"},
			],
		)
		self.assertEqual(before["shapes"], after["shapes"])

	def test_a_lane_change_keeps_the_fresh_layout(self):
		before = compiled(nine_task_map())
		edited, _problem = apply_operations(
			map_xml.xml_to_ir(before), [{"op": "add", "type": "lane", "id": "fin", "name": "Finance"}]
		)
		self.assertIsNone(map_xml.keep_positions(before, compiled(edited)))


class TestTheReplyListsTheOperations(FrappeTestCase):
	def test_each_operation_gets_one_line_in_the_words_of_the_diagram(self):
		xml = compiled(nine_task_map())
		text = describe_changes(
			xml,
			xml,
			[
				{"op": "retype", "id": "t6", "type": "serviceTask"},
				{"op": "move", "id": "t7", "lane": "staff"},
				{"op": "set_condition", "id": "f_g_t4", "condition": "action == 'Approve'"},
				{"op": "rename", "id": "t1", "name": "First"},
				{"op": "add", "type": "userTask", "id": "t10", "name": "Extra Check", "lane": "hr"},
				{"op": "reconnect", "id": "f_t9_e", "to": "t10"},
				{"op": "remove", "id": "t5"},
			],
		)
		for line in (
			'- Changed the step "Step 6" to a service task.',
			'- Moved the step "Step 7" to the lane "Staff".',
			'- Set the condition on the path from "Approved?" to "Step 4" to: action == \'Approve\'',
			'- Renamed the step "Step 1" to "First".',
			'- Added the step "Extra Check".',
			'- Rerouted the path from "Step 9" to "Done": it is now the path from "Step 9" to "Extra Check".',
			'- Removed the step "Step 5".',
		):
			self.assertIn(line, text)

	def test_a_change_already_on_the_diagram_is_not_claimed(self):
		xml = compiled(nine_task_map())
		text = describe_changes(
			xml,
			xml,
			[
				{"op": "set_condition", "id": "f_g_t5", "default": True},
				{"op": "move", "id": "t6", "lane": "hr"},
				{"op": "retype", "id": "t6", "type": "userTask"},
			],
		)
		for line in (
			'- No change: the path from "Approved?" to "Step 5" was already the default path.',
			'- No change: the step "Step 6" was already in the lane "HR Officer".',
			'- No change: the step "Step 6" was already a user task.',
		):
			self.assertIn(line, text)
		self.assertNotIn("Made", text)
