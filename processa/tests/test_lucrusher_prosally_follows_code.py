# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""LuCrusher's ProsAlly drafts follow the code and the Workflow, run against the BA site's scripts."""

import html
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.agent_runtime.tool_bounds import validate_tool_arguments
from processa.patches.v1_0 import lucrusher_prosally_follows_code_and_workflow as p
from processa.patches.v1_0.seed_lucrusher_skills import SKILLS
from processa.ai_agent_security.code_checks.script_validator import deep_inspect_script
from processa.tests.processa_imports import processa_imports
from processa.tests.site_scripts import as_deployed

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
	return (FIXTURES / name).read_text(encoding="utf-8")


def _block(elements, header="C: ELEMENTS"):
	lines = [f"{n}. UserTask | Step {n} | Lane | src=a.py:b" for n in range(1, elements + 1)]
	return "\n".join(["A: HEADER", "B: LANES", header, *lines, "D: SEQUENCE FLOWS", "1. 1 -> 2"])


def _process(elements=5, process_id="p1", **extra):
	return {
		"process_name": "P",
		"process_id": process_id,
		"element_count": elements,
		"prompt_block": _block(elements),
		"source": "Page 1",
		**extra,
	}


class TestSkillEdit(FrappeTestCase):
	def setUp(self):
		body = next(s["body"] for s in SKILLS if s["skill_name"] == p.PROSALLY_SKILL)
		self.body = body.replace("prompt_block}]}", "prompt_block, source}]}")

	def test_skill_gains_the_rules_once(self):
		out = p.with_grounding(self.body)
		for text in ("allowed field", "read_doctype_logic", "at most 25 elements", "## Conflicts", "coverage"):
			self.assertIn(text, out)
		self.assertEqual(p.with_grounding(out), out)

	def test_edited_skill_is_left_alone(self):
		edited = self.body.replace(p.RULE_OLD, "- Edited.")
		self.assertEqual(p.with_grounding(edited), edited)


def _schema_xml(prosally):
	schema = {
		"properties": {
			"intent": {"type": "string"},
			"response": {"type": "string"},
			"prosally_prompts": {"type": "object", "properties": {"processes": prosally}},
		},
		"required": ["intent", "response"],
	}
	params = html.escape(json.dumps(schema), quote=True)
	return f'<bpmn:scriptTask id="finalize" name="finalize" spiffworkflow:aiToolParams="{params}">'


def _checker(omit_coverage=False):
	xml = p.with_prosally_schema(_schema_xml({"type": "array"}))
	schema = json.loads(html.unescape(p.FINALIZE_PARAMS.search(xml).group(1)))

	def check(**prompts):
		if not omit_coverage:
			prompts.setdefault("coverage", [])
		return validate_tool_arguments(
			"finalize",
			schema["properties"],
			schema["required"],
			{"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": prompts},
		)

	return check


class TestFinalizeSchema(FrappeTestCase):
	def test_schema_is_added_once(self):
		before = _schema_xml({"type": "array"})
		xml = p.with_prosally_schema(before)
		self.assertNotEqual(xml, before)
		self.assertEqual(p.with_prosally_schema(xml), xml)

	def test_xml_without_a_finalize_shape_is_left_alone(self):
		self.assertEqual(p.with_prosally_schema("<bpmn:definitions/>"), "<bpmn:definitions/>")

	def test_three_processes_are_rejected_and_two_pass(self):
		check = _checker()
		three = [_process(process_id=f"p{n}") for n in range(3)]
		self.assertIn("processes", check(processes=three))
		self.assertIsNone(check(processes=three[:2]))

	def test_element_count_over_25_is_rejected(self):
		check = _checker()
		self.assertIn("element_count", check(processes=[_process(26)]))
		self.assertIsNone(check(processes=[_process(25)]))

	def test_covered_row_needs_an_element_and_a_gap_does_not(self):
		check = _checker()
		covered = {"behaviour": "wait", "citation": "a.py:b", "status": "Covered"}
		gap = {"behaviour": "wait", "citation": "a.py:b", "status": "Gap"}
		self.assertIsNotNone(check(processes=[_process()], coverage=[covered]))
		self.assertIsNone(check(processes=[_process()], coverage=[{**covered, "element": 3}, gap]))

	def test_a_draft_without_coverage_is_rejected(self):
		self.assertIn("coverage", _checker(omit_coverage=True)(processes=[_process()]))

	def test_conflict_needs_a_topic_and_citation(self):
		check = _checker()
		self.assertIsNotNone(check(processes=[_process()], conflicts=[{"topic": "base date"}]))
		self.assertIsNone(
			check(processes=[_process()], conflicts=[{"topic": "base date", "citation": "a.py:b"}])
		)


def _finalize_script():
	return p.apply_edits(_fixture("lucrusher_finalize_ba.txt"), p.FINALIZE_EDITS, p.FINALIZE_MARKER)


def _run_finalize(prosally_prompts):
	scope = {"task_data": {"prosally_prompts": prosally_prompts}, "context_docname": "x", "result": {}}
	stored = {}
	with (
		patch("processa.processa_engine.agent_runtime.turn_state.get_turn", return_value={}),
		patch("processa.processa_engine.agent_runtime.turn_state.update_turn", side_effect=lambda _n, **kw: stored.update(kw)),
	):
		exec(as_deployed(_finalize_script()), scope, {})  # noqa: S102 - the patched script text under test
	return stored["output"]["prosally_prompts"]


class TestFinalizeScript(FrappeTestCase):
	def test_script_passes_the_script_gate(self):
		self.assertEqual(deep_inspect_script(_finalize_script(), processa_imports(_finalize_script())), [])

	def test_edit_is_applied_once_and_a_moved_anchor_is_left_alone(self):
		original = _fixture("lucrusher_finalize_ba.txt")
		once = _finalize_script()
		self.assertNotEqual(once, original)
		self.assertEqual(p.apply_edits(once, p.FINALIZE_EDITS, p.FINALIZE_MARKER), once)
		self.assertEqual(p.apply_edits("x = 1\n", p.FINALIZE_EDITS, p.FINALIZE_MARKER), "x = 1\n")

	def test_block_over_25_raises_even_when_it_reports_fewer(self):
		with self.assertRaises(ValueError) as caught:
			_run_finalize({"processes": [{**_process(26), "element_count": 20}]})
		self.assertIn("26", str(caught.exception))

	def test_element_count_is_the_counted_one(self):
		out = _run_finalize({"processes": [{**_process(25), "element_count": 3}]})
		self.assertEqual(out["processes"][0]["element_count"], 25)

	def test_confirmation_without_prompts_passes(self):
		self.assertIsNone(_run_finalize(None))


def _run_save_response(previous, new):
	script = p.apply_edits(_fixture("lucrusher_save_response_current_ba.txt"), p.SAVE_EDITS, p.SAVE_MARKER)
	recorded = {}
	message = SimpleNamespace(name="MSG-1", insert=lambda: None)
	output = {"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": new}
	scope = {
		"frappe": SimpleNamespace(new_doc=lambda _doctype: message),
		"task_data": {"conversation_id": "c"},
		"context_docname": "c",
		"result": {},
	}
	with (
		patch("processa.processa_engine.agent_runtime.turn_state.get_turn", return_value={"output": output, "context_state": previous}),
		patch("processa.processa_engine.agent_runtime.turn_state.clear_turn"),
		patch("processa.ai_agent_conversations.session_state.record", side_effect=lambda _c, snap: recorded.update(snap)),
	):
		exec(as_deployed(script), scope)  # noqa: S102 - the patched script text under test, whose helpers read its module names
	return recorded["prosally_prompts"], json.loads(message.metadata)["agent_result"]["prosally_prompts"]


class TestSaveResponseMerge(FrappeTestCase):
	def test_second_call_adds_to_the_first_and_replaces_a_redraft(self):
		first = {"processes": [_process(3, "a"), _process(4, "b")], "remaining": ["c"]}
		second = {"processes": [_process(7, "b"), _process(5, "c")], "remaining": []}
		held, shown = _run_save_response({"prosally_prompts": first}, second)
		for value in (held, shown):
			self.assertEqual(sorted(x["process_id"] for x in value["processes"]), ["a", "b", "c"])
			self.assertEqual({x["process_id"]: x["element_count"] for x in value["processes"]}["b"], 7)
			self.assertEqual(value["remaining"], [])

	def test_first_call_is_kept_as_sent(self):
		first = {"processes": [_process(3, "a")], "remaining": ["b"]}
		held, _ = _run_save_response({}, first)
		self.assertEqual(held, first)

	def test_moved_anchor_is_left_alone(self):
		self.assertEqual(p.apply_edits("x = 1\n", p.SAVE_EDITS, p.SAVE_MARKER), "x = 1\n")


class TestBuildContextLine(FrappeTestCase):
	def test_line_names_the_processes_left(self):
		script = p.apply_edits(_fixture("lucrusher_build_context_ba.txt"), p.CONTEXT_EDITS, p.CONTEXT_MARKER)
		self.assertIn('" remaining: "', script)
		compile(script, "build_context", "exec")
		self.assertEqual(p.apply_edits(script, p.CONTEXT_EDITS, p.CONTEXT_MARKER), script)


PAGES = {"session_state": {"lucid_doc:1": {"pages": [{"page_title": "Client Event"}]}}}
GOOD_PROCESS = {"type": "User Task Driven", "reason": "R1", "shapes": ["s"], "source": "Client Event"}


def _review(task_data, turn=None):
	"""Run the site's Finalize script the way the engine does, in one namespace; (output, raised message)."""
	script = frappe.db.get_value("Server Script", "LuCrusher \u2013 Tool Finalize", "script")
	stored = {}
	scope = {"frappe": frappe, "task_data": task_data, "context_docname": "x", "result": {}}
	with (
		patch(
			"processa.processa_engine.agent_runtime.turn_state.get_turn",
			return_value={**PAGES, **(turn or {})},
		),
		patch(
			"processa.processa_engine.agent_runtime.turn_state.update_turn",
			side_effect=lambda _n, **kw: stored.update(kw),
		),
	):
		try:
			exec(as_deployed(script), scope)
		except ValueError as raised:
			return stored, str(raised)
	return stored["output"], ""


class TestFinalizeSelfReview(FrappeTestCase):
	def setUp(self):
		script = frappe.db.get_value("Server Script", "LuCrusher \u2013 Tool Finalize", "script") or ""
		if "_lcr_review_topology" not in script:
			self.skipTest("the self-reviewing LuCrusher Finalize script is not on this site")

	def _topology(self, *names, **turn):
		processes = [{"process_name": name, **GOOD_PROCESS} for name in names]
		return _review(
			{"intent": "TOPOLOGY_PROPOSAL", "response": "ok", "topology": {"processes": processes}}, turn
		)

	def test_approve_and_accept_on_one_document_go_back_once_as_one_workflow(self):
		stored, raised = self._topology("Approve Client Event", "Accept Client Event")

		self.assertIn("act on the same client event", raised)
		self.assertIn("R7", raised)
		self.assertTrue(stored["finalize_reviewed"])
		self.assertIn("Check before you approve", stored["review_draft"]["response"])

	def test_a_problem_left_after_the_second_finalize_is_flagged_in_the_reply(self):
		output, raised = self._topology("Approve Client Event", "Accept Client Event", finalize_reviewed=True)

		self.assertEqual(raised, "")
		self.assertIn("Check before you approve", output["response"])

	def test_a_clean_draft_passes_untouched(self):
		output, raised = self._topology("Manage Client Event", "Generate Event Schedules")

		self.assertEqual(raised, "")
		self.assertEqual(output["response"], "ok")

	def test_repeats_missing_fields_and_unsourced_processes_are_found(self):
		processes = [
			{"process_name": "Manage Client Event", **GOOD_PROCESS},
			{"process_name": "Manage Client Event", **GOOD_PROCESS},
			{"process_name": "Invented Step", **GOOD_PROCESS, "source": "Somewhere Else", "reason": ""},
		]
		line = "The event is created by the supervisor and approved by the manager."
		_stored, raised = _review(
			{
				"intent": "TOPOLOGY_PROPOSAL",
				"response": line + "\n" + line,
				"topology": {"processes": processes},
			}
		)

		self.assertIn("listed 2 times", raised)
		self.assertIn('"Invented Step" has no reason', raised)
		self.assertIn('source of "Invented Step" is not a page', raised)
		self.assertIn("The reply says", raised)

	def test_a_script_task_standing_in_for_a_signal_goes_back(self):
		block = "\n".join(
			[
				"A: HEADER",
				"B: LANES",
				"C: ELEMENTS",
				"1. StartEvent | Visa requested | Employee",
				"2. ScriptTask | Broadcast unfit signal | GRD | src=visa.py:on_update",
				"3. EndEvent | Visa issued | PRO",
				"D: SEQUENCE FLOWS",
				"1. 1 -> 2",
				"E: ANTI-LINTING",
			]
		)
		prompts = {"processes": [{**_process(), "prompt_block": block, "source": "Client Event"}]}
		_stored, raised = _review(
			{"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": prompts}
		)

		self.assertIn("uses a ScriptTask for a signal", raised)

	def test_elements_numbered_without_a_dot_are_counted_and_checked(self):
		block = "\n".join(
			[
				"A. HEADER",
				"B. LANES",
				"C. ELEMENTS",
				"1 StartEvent 'Asked' lane1",
				"2 ScriptTask 'Broadcast returned signal' lane1 src=a.py:b",
				"D. SEQUENCE FLOWS",
				"E. ANTI-LINTING",
			]
		)
		prompts = {"processes": [{**_process(), "prompt_block": block, "source": "Client Event"}]}
		output, raised = _review(
			{"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": prompts},
			{"finalize_reviewed": True},
		)

		self.assertEqual(raised, "")
		self.assertEqual(output["prosally_prompts"]["processes"][0]["element_count"], 2)
		self.assertIn("uses a ScriptTask for a signal", output["response"])


class TestConfirmationKeepsTheDraft(FrappeTestCase):
	"""Runs the site's Save Response script on a confirmation that echoes a names-only topology."""

	def setUp(self):
		script = frappe.db.get_value("Server Script", "LuCrusher \u2013 Save Response", "script") or ""
		if "_CONFIRMED_DRAFT" not in script:
			self.skipTest(
				"the LuCrusher Save Response script that keeps the confirmed draft is not on this site"
			)
		self.script = script
		patcher = patch("processa.processa_engine.triggers.on_doc_event")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.conversation = (
			frappe.get_doc({"doctype": "Chat Conversation", "title": "confirm probe"}).insert().name
		)

	def _save(self, output, context_state=None):
		recorded = {}
		turn = {"output": output, "context_state": context_state or {}}
		with (
			patch("processa.processa_engine.agent_runtime.turn_state.get_turn", return_value=turn),
			patch("processa.processa_engine.agent_runtime.turn_state.clear_turn"),
			patch(
				"processa.ai_agent_conversations.session_state.record",
				side_effect=lambda _c, snap: recorded.update(snap),
			),
		):
			exec(
				as_deployed(self.script),
				{"frappe": frappe, "task_data": {}, "context_docname": self.conversation, "result": {}},
			)
		saved = frappe.get_all(
			"Chat Message",
			{"conversation": self.conversation, "message_type": "Bot"},
			pluck="metadata",
			order_by="creation desc",
			limit=1,
		)[0]
		return json.loads(saved)["agent_result"], recorded

	def test_a_confirmed_topology_keeps_the_reasons_and_sources_of_the_proposal(self):
		proposal = {
			"processes": [
				{
					"process_name": "Manage Absence Case",
					"type": "User Task Driven",
					"reason": "R7",
					"source": "Action Absence Case",
				}
			]
		}
		self._save({"intent": "TOPOLOGY_PROPOSAL", "response": "proposal", "topology": proposal})

		echoed = {"processes": [{"process_name": "Manage Absence Case"}]}
		result, snapshot = self._save(
			{"intent": "TOPOLOGY_CONFIRMED", "response": "confirmed", "topology": echoed}
		)

		self.assertEqual(result["topology"], proposal)
		self.assertEqual(snapshot["topology"]["processes"][0]["reason"], "R7")
		self.assertEqual(snapshot["topology"]["processes"][0]["source"], "Action Absence Case")

	def test_confirmed_tasks_are_the_draft_held_in_the_state(self):
		held = {
			"processes": [{"process_name": "P", "tasks": [{"task": "Build the map", "references": ["a.py"]}]}]
		}

		result, _snapshot = self._save(
			{
				"intent": "MIGRATION_TASKS_CONFIRMED",
				"response": "ok",
				"migration_tasks": {"processes": [{"process_name": "P"}]},
			},
			{"migration_tasks": held},
		)

		self.assertEqual(result["migration_tasks"], held)

	def test_a_sent_back_draft_is_saved_flagged_when_the_model_does_not_finalize_again(self):
		draft = {
			"intent": "TOPOLOGY_PROPOSAL",
			"response": "proposal\n\n**Check before you approve:**\n- x",
			"topology": {"processes": []},
		}
		recorded = {}
		turn = {"output": None, "review_draft": draft, "context_state": {}}
		with (
			patch("processa.processa_engine.agent_runtime.turn_state.get_turn", return_value=turn),
			patch("processa.processa_engine.agent_runtime.turn_state.clear_turn"),
			patch(
				"processa.ai_agent_conversations.session_state.record",
				side_effect=lambda _c, snap: recorded.update(snap),
			),
		):
			exec(
				as_deployed(self.script),
				{
					"frappe": frappe,
					"task_data": {"ai_result": "proposal as text"},
					"context_docname": self.conversation,
					"result": {},
				},
			)

		self.assertEqual(recorded["intent"], "TOPOLOGY_PROPOSAL")
		saved = frappe.get_all(
			"Chat Message", {"conversation": self.conversation, "message_type": "Bot"}, pluck="text"
		)
		self.assertIn("Check before you approve", saved[0])
