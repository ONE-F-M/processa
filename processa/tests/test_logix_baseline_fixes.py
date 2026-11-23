# Copyright (c) 2026, one-fm and contributors
"""Logix's finalize explains a refusal, the writer gets DocType fields and Baseline judges use an enabled model."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_baseline_judges_use_an_enabled_model as judges
from processa.patches.v1_0 import logix_finalize_explains_a_writer_refusal as refusal
from processa.patches.v1_0 import logix_writer_reads_doctype_fields as fields

FINALIZE = (
	'_MISSING = (\n    "ask"\n)\nif x:\n    pass\n'
	+ refusal.EMPTY_OLD
	+ '            "original_script": None,\n        }, done=True)\n'
)


class TestLogixBaselineFixes(FrappeTestCase):
	def test_finalize_answers_a_refusal(self):
		code = refusal.explains_refusal(FINALIZE)
		self.assertIn("_REFUSED = (", code)
		self.assertIn('"error_code": "MODEL_REFUSED"', code)
		self.assertNotIn(refusal.EMPTY_OLD, code)
		self.assertEqual(refusal.explains_refusal("no anchors here"), "no anchors here")

	def test_build_context_loads_fields_once(self):
		code = fields.build_context(fields.IMPORT_OLD + "set_turn(c, {\n" + fields.SPREAD_OLD + "})\n")
		self.assertIn('doctype_inputs(task_data.get("user_text")', code)
		self.assertEqual(fields.build_context(code), code)

	def test_the_writer_prompt_lists_fields_only_in_write_script(self):
		xml = (
			'<bpmn:serviceTask id="write_script" p="{% if turn.violations %}"></bpmn:serviceTask>'
			'<bpmn:serviceTask id="clarify" p="{% if turn.violations %}"></bpmn:serviceTask>'
		)
		out = fields.writer_prompt(xml)
		self.assertEqual(out.count("turn.doctype_fields"), 2)
		self.assertNotIn("doctype_fields", out.split('id="clarify"')[1])
		self.assertEqual(fields.writer_prompt(out), out)

	def test_a_judge_on_a_disabled_model_moves_to_the_given_model(self):
		case = frappe._dict(
			assertions=[
				frappe._dict(assertion_type="llm_judge", judge_model="old", judge_provider="X"),
				frappe._dict(assertion_type="llm_judge", judge_model="live", judge_provider="X"),
			]
		)
		with patch.object(judges, "_enabled", side_effect=lambda m: m == "live"):
			self.assertTrue(judges.move_disabled_judges(case, "new", "Anthropic"))
		self.assertEqual(
			[(a.judge_model, a.judge_provider) for a in case.assertions],
			[("new", "Anthropic"), ("live", "X")],
		)
