# Copyright (c) 2026, one-fm and contributors
"""A layout instruction is laid out again or refused in words, and the crossing note is said once per conversation."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_replies, tools_review
from processa.patches.v1_0 import seed_prosally_layout_regression_cases as seed

NODES = [{"id": "g1", "name": "Recruiter Action?"}, {"id": "g2", "name": "Requester Action?"}]
NOT_PLANAR = {"planar": False, "obstruction": ["g1", "g2"]}
TWO_THINGS = ("drag shapes on the canvas", "change the flow structure")


class TestCrossingNote(FrappeTestCase):
	def setUp(self):
		patcher = patch("processa.processa_engine.triggers.on_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.conversation = (
			frappe.get_doc({"doctype": "Chat Conversation", "title": "crossing probe"}).insert().name
		)

	def _bot_said(self, text):
		frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation,
				"message_type": "Bot",
				"text": text,
			}
		).insert()

	def test_a_planar_layout_gets_no_note(self):
		self.assertEqual(tools_replies.crossing_line_note(NODES, {"planar": True}, self.conversation), "")

	def test_the_first_crossing_is_explained_with_the_steps_on_it(self):
		note = tools_replies.crossing_line_note(NODES, NOT_PLANAR, self.conversation)

		self.assertIn("One crossing line is unavoidable", note)
		self.assertIn("Recruiter Action?, Requester Action?", note)

	def test_the_note_is_not_repeated_in_the_same_conversation(self):
		self._bot_said(
			"I've updated the process. One crossing line is unavoidable: the paths through X cannot all be laid flat."
		)

		self.assertEqual(tools_replies.crossing_line_note(NODES, NOT_PLANAR, self.conversation), "")

	def test_another_conversation_hears_it_again(self):
		self._bot_said("One crossing line is unavoidable: the paths through X cannot all be laid flat.")
		other = frappe.get_doc({"doctype": "Chat Conversation", "title": "other"}).insert().name

		self.assertIn(
			"One crossing line is unavoidable", tools_replies.crossing_line_note(NODES, NOT_PLANAR, other)
		)


CLEAN = {"crossings": 0, "throughShape": 0, "overlaps": 0}


class TestRelayoutReply(FrappeTestCase):
	def _reply(self, relaid, audits, text=""):
		with (
			patch.object(tools_review, "relayout", return_value=relaid),
			patch.object(tools_review, "audit_layout", side_effect=audits),
		):
			return tools_review.relayout_output("<old />", text)

	def test_a_redrawn_diagram_says_what_the_person_can_do_about_layout(self):
		out = self._reply(("<xml />", ""), [CLEAN, CLEAN])

		self.assertEqual(out["action_intent"], "RELAYOUT")
		self.assertIn("Layout is computed automatically", out["response"])
		for thing in TWO_THINGS:
			self.assertIn(thing, out["response"])

	def test_an_unchanged_layout_still_names_the_two_things(self):
		out = self._reply((None, "same"), [CLEAN])

		self.assertEqual(out["intent"], "CLARIFY")
		self.assertIn("came out where it already is", out["response"])
		for thing in TWO_THINGS:
			self.assertIn(thing, out["response"])

	def test_each_ask_is_answered_with_what_was_measured(self):
		out = self._reply(
			("<xml />", ""),
			[{**CLEAN, "crossings": 4}, {**CLEAN, "crossings": 1}],
			"Fix the spacing, align the steps, untangle the crossing lines and make the lines converge",
		)

		self.assertIn("Crossing lines: 4 before, 1 now.", out["response"])
		self.assertIn("sized to the lines they carry", out["response"])
		self.assertIn("layout grid", out["response"])
		self.assertIn("meet at one point", out["response"])

	def test_a_layout_with_more_crossings_is_not_shown(self):
		out = self._reply(
			("<xml />", ""), [{**CLEAN, "crossings": 2}, {**CLEAN, "crossings": 9}], "fewer crossings"
		)

		self.assertEqual(out["intent"], "CLARIFY")
		self.assertNotIn("bpmn_xml", out)
		self.assertIn("9 crossing line(s) where yours has 2", out["response"])

	def test_an_unchanged_layout_says_why_each_ask_cannot_be_met(self):
		out = self._reply((None, "same"), [{**CLEAN, "crossings": 3}], "more space between the steps please")

		self.assertIn("fewer than 3 crossing line(s)", out["response"])
		self.assertIn("cannot set a gap of my own", out["response"])

	def test_only_layout_words_count_as_layout_asks(self):
		self.assertEqual(tools_replies.layout_asks("Add a review step after approval"), [])
		self.assertEqual(tools_replies.layout_asks("Line them up"), ["alignment"])
		self.assertEqual(tools_replies.layout_asks("the lines criss-cross"), ["crossings"])

	def test_a_change_with_a_layout_ask_reports_it_and_one_without_says_nothing(self):
		with patch.object(tools_replies, "audit_layout", side_effect=[{**CLEAN, "crossings": 2}, CLEAN]):
			note = tools_replies.layout_note("<old />", "<new />", "add a step and remove the crossing lines")

		self.assertEqual(note, " Crossing lines: 2 before, 0 now.")
		self.assertEqual(tools_replies.layout_note("<old />", "<new />", "add a step"), "")


class TestConvergingLines(FrappeTestCase):
	def test_lines_through_an_added_gateway_meet_at_its_centre(self):
		def edge(*points):
			return "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in points)

		flows = {"a": ("t1", "g"), "b": ("t2", "g"), "c": ("g", "t3")}
		drawn = {
			"a": edge((0, 0), (90, 0), (90, 25), (100, 25)),
			"b": edge((0, 50), (100, 50)),
			"c": edge((150, 25), (200, 25)),
			"g": '<dc:Bounds x="100" y="0" width="50" height="50" />',
		}

		route = tools_review._route("a", flows, drawn, {"g"})

		self.assertEqual(route, [("0", "0"), ("90", "0"), ("90", "25"), ("125", "25"), ("200", "25")])


class TestRegressionCases(FrappeTestCase):
	def _suite(self):
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		suite = agent and frappe.db.get_value(
			"AI Eval Suite", {"agent_configuration": agent, "title": ["like", seed.SUITE_TITLE_LIKE]}, "name"
		)
		if not suite:
			self.skipTest("ProsAlly and its Regressions suite are not on this site")
		return suite

	def test_each_instruction_expects_relayout_and_no_drawing_tool(self):
		suite = self._suite()

		seed.execute()
		seed.execute()

		titles = [t for t, _p in seed.PROMPTS]
		cases = frappe.get_all(
			"AI Eval Case", filters={"suite": suite, "title": ["in", titles]}, fields=["name", "title"]
		)
		self.assertEqual(sorted(c.title for c in cases), sorted(titles))
		case = frappe.get_doc("AI Eval Case", cases[0].name)
		self.assertEqual([a.assertion_type for a in case.assertions], ["regex", "no_tool_call"])
		self.assertRegex("Shall I lay the diagram out again?", case.assertions[0].value)
		self.assertNotRegex("Shall I add the step?", case.assertions[0].value)
		self.assertIn("modify_process", case.assertions[1].value)
		self.assertEqual([c.tool_name for c in case.expected_tool_calls], ["classify_intent"])
		self.assertIn("current_xml", case.input_context)
