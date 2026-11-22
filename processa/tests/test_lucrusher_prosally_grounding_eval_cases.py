# Copyright (c) 2026, one-fm and contributors
"""The five grounding cases in LuCrusher Baseline: what each asks and that seeding twice adds no row."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import seed_lucrusher_eval_suite as suite_seed
from processa.patches.v1_0 import seed_lucrusher_prosally_grounding_eval_cases as seed
from processa.patches.v1_0 import seed_lucrusher_workflow_modelling_eval_cases as modelling_seed


class TestGroundingEvalCases(FrappeTestCase):
	def test_five_cases_each_read_the_code_then_draft(self):
		self.assertEqual(len(seed.CASES), 5)
		self.assertEqual(len({c["title"] for c in seed.CASES}), 5)
		for case in seed.CASES:
			tools = [(c["tool_name"], c["argument"], c["expected_value"]) for c in case["calls"]]
			self.assertEqual(tools[0][0], "read_doctype_logic", case["title"])
			self.assertEqual(tools[1], ("finalize", "intent", "PROSALLY_PROMPT_DRAFT"), case["title"])
			self.assertIn("llm_judge", [a["assertion_type"] for a in case["assertions"]], case["title"])

	def test_the_lanes_case_offers_a_lucidchart_lane_the_workflow_lacks(self):
		case = next(c for c in seed.CASES if c["title"].startswith("Lanes come from"))
		doc = next(iter(case["context"]["session_state"].values()))
		self.assertIn("Event Creator", doc["swimlanes"])

	def test_the_size_case_has_more_processes_than_one_call_may_draft(self):
		case = next(c for c in seed.CASES if c["title"].startswith("Four processes"))
		state = case["context"]["conversation_messages"][2]["metadata"]
		self.assertEqual(state["topology"]["total_processes"], 4)
		self.assertGreater(len(state["migration_tasks"]["processes"]), 2)

	def test_seeding_twice_adds_each_case_once(self):
		frappe.set_user("Administrator")
		suite_seed.execute()
		suite = frappe.db.get_value("AI Eval Suite", {"title": suite_seed.SUITE_TITLE})
		if not suite:
			self.skipTest("LuCrusher is not on this site")
		seed.execute()
		seed.execute()
		for case in seed.CASES:
			rows = frappe.get_all("AI Eval Case", {"suite": suite, "title": case["title"]}, pluck="name")
			self.assertEqual(len(rows), 1, case["title"])
			doc = frappe.get_doc("AI Eval Case", rows[0])
			self.assertEqual(json.loads(doc.input_context), case["context"])
			self.assertEqual(doc.expected_tool_calls[0].tool_name, "read_doctype_logic")


class TestWorkflowModellingEvalCases(FrappeTestCase):
	def test_state_and_document_sit_where_build_context_reads_them(self):
		for case in modelling_seed.CASES:
			state = case["context"]["session_state"]
			self.assertEqual(len(case["context"]["conversation_messages"]), 2, case["title"])
			self.assertIn("summary", state[f"lucid_doc:{suite_seed.LUCID_DOC_ID}"], case["title"])
			self.assertIn("intent", state, case["title"])

	def test_one_case_checks_approve_and_accept_and_one_checks_the_signal(self):
		topology, signal = modelling_seed.CASES
		self.assertEqual(topology["calls"][-1]["expected_value"], "TOPOLOGY_PROPOSAL")
		self.assertIn(
			"Approve and Accept are NOT proposed as separate processes", topology["assertions"][-1]["value"]
		)
		finalize = [c for c in signal["calls"] if c["tool_name"] == "finalize"]
		self.assertEqual({c["call_order"] for c in finalize}, {2})
		pattern = next(c["expected_value"] for c in finalize if c["argument"] == "prosally_prompts")
		drawn = "C:\\n4. IntermediateThrowEvent | Unfit (signal medical_unfit)\\n7. BoundaryEvent | signal medical_unfit\\nD:"
		scripted = "C:\\n4. ScriptTask | Broadcast unfit signal\\n5. IntermediateThrowEvent | x signal\\n6. IntermediateCatchEvent | x signal"
		self.assertRegex(drawn, pattern)
		self.assertNotRegex(scripted, pattern)

	def test_seeding_twice_adds_each_case_once(self):
		frappe.set_user("Administrator")
		suite = frappe.db.get_value("AI Eval Suite", {"title": suite_seed.SUITE_TITLE})
		if not suite:
			self.skipTest("LuCrusher is not on this site")
		modelling_seed.execute()
		modelling_seed.execute()
		for case in modelling_seed.CASES:
			rows = frappe.get_all("AI Eval Case", {"suite": suite, "title": case["title"]}, pluck="name")
			self.assertEqual(len(rows), 1, case["title"])
