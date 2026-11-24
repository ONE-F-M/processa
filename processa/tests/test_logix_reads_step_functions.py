# Copyright (c) 2026, one-fm and contributors
"""Logix reads the functions inside a map's steps, in its turn and in its prompts."""

import frappe
from frappe.tests.utils import FrappeTestCase
from jinja2 import Template

from processa.api.server_scripts import build_logix_turn_context
from processa.patches.v1_0 import logix_reads_step_functions as p

STEP = "Logix Step Functions Test Chunk"
STEP_CODE = (
	"def _chunk_text(text, size):\n\treturn [text[i:i + size] for i in range(0, len(text), size)]\n\n"
	"result['chunks'] = _chunk_text(task_data.get('text') or '', 5)\n"
)
OPEN = "Logix Step Functions Test Open"
MODEL = "Logix Step Functions Test Map"
STEPS = [
	{
		"step": "Chunk",
		"script": STEP,
		"functions": ["_chunk_text(text, size)"],
		"code": "def _chunk_text(text, size):\n\treturn [text[i:i + size] for i in range(0, len(text), size)]",
	}
]
BUILD_CONTEXT = (
	"set_turn(conversation_id, {\n"
	'    "process_context": task_data.get("process_context") or {},\n'
	'    "library_scripts": task_data.get("library_scripts") or [],\n'
	"})\n"
)
MAP = (
	'<bpmn:serviceTask id="other">{% if turn.violations %}User request: {{ user_request }}</bpmn:serviceTask>'
	'<bpmn:serviceTask id="clarify" aiUserPrompt="Linked&#10;User request: {{ user_request }}"></bpmn:serviceTask>'
	'<bpmn:serviceTask id="write_script" aiUserPrompt="Request{% if turn.violations %}x{% endif %}">'
	"</bpmn:serviceTask>"
)


def _render(block, **context):
	return Template(block.replace("&#10;", "\n")).render(**context)


class TestLogixStepFunctions(FrappeTestCase):
	def setUp(self):
		super().setUp()
		for name, body in ((STEP, STEP_CODE), (OPEN, "result['ok'] = 1")):
			if frappe.db.exists("Server Script", name):
				frappe.db.set_value("Server Script", name, "script", body)
				continue
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": frappe.scrub(name),
					"script": body,
				}
			).insert()
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1)
		model = frappe.new_doc("BPMN Process Model")
		model.update({"name": MODEL, "title": MODEL, "process_id": "logix_step_functions_test", "version": 1})
		model.bpmn_xml = (
			'<?xml version="1.0" encoding="UTF-8"?>'
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
			'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
			'<bpmn:process id="logix_step_functions_test" isExecutable="true">'
			f'<bpmn:scriptTask id="chunk" name="Chunk" spiffworkflow:serverScript="{STEP}">'
			"<bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:scriptTask>"
			f'<bpmn:scriptTask id="open" name="Open" spiffworkflow:serverScript="{OPEN}">'
			"<bpmn:incoming>f2</bpmn:incoming></bpmn:scriptTask>"
			"</bpmn:process></bpmn:definitions>"
		)
		model.insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_function_inside_a_step_reaches_the_turn_and_its_text(self):
		out = build_logix_turn_context({"current_script": OPEN, "process_context": {"process_model": MODEL}})
		self.assertEqual(out["step_functions"], STEPS)
		self.assertIn("FUNCTIONS INSIDE STEPS ON THIS MAP", out["dialog_context"])
		self.assertIn(f"- step Chunk (script {STEP}): _chunk_text(text, size)", out["dialog_context"])
		self.assertNotIn("library_scripts", out)

	def test_the_open_step_is_not_listed_as_its_own_source(self):
		out = build_logix_turn_context({"current_script": STEP, "process_context": {"process_model": MODEL}})
		self.assertNotIn("step_functions", out)

	def test_build_context_keeps_the_step_functions(self):
		code = p.build_context(BUILD_CONTEXT)
		namespace = {"task_data": {"step_functions": STEPS}, "conversation_id": "c", "turns": {}}
		exec(code, {**namespace, "set_turn": lambda _c, data: namespace["turns"].update(data)})
		self.assertEqual(namespace["turns"]["step_functions"], STEPS)
		self.assertEqual(p.build_context(code), code)

	def test_the_writer_and_clarify_prompts_list_the_step_functions_once(self):
		xml = p.prompts(MAP)
		self.assertEqual(p.prompts(xml), xml)
		self.assertNotIn("step_functions", xml.split('id="clarify"')[0])
		writer = _render(p.WRITER_BLOCK, turn={"step_functions": STEPS})
		self.assertIn(f"- step Chunk (script {STEP}): _chunk_text(text, size)", writer)
		self.assertIn("```python\ndef _chunk_text(text, size):", writer)
		self.assertEqual(_render(p.WRITER_BLOCK, turn={}), "")
		turn = frappe._dict(step_functions=STEPS)
		clarify = _render(
			p.CLARIFY_BLOCK, get_turn=lambda _n: turn, instance=frappe._dict(context_docname="c")
		)
		self.assertIn("_chunk_text(text, size) in step Chunk", clarify)
