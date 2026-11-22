# Copyright (c) 2026, one-fm and contributors
"""Logix's script writer gets the map's library scripts in its prompt."""

from frappe.tests.utils import FrappeTestCase
from jinja2 import Template

from processa.patches.v1_0 import logix_writer_sees_library_scripts as p

BUILD_CONTEXT = (
	"set_turn(conversation_id, {\n"
	'    "user_text": task_data.get("user_text", "") or "",\n'
	'    "process_context": task_data.get("process_context") or {},\n'
	"})\n"
)
MAP = (
	'<bpmn:serviceTask id="other">{% if turn.violations %}</bpmn:serviceTask>'
	'<bpmn:serviceTask id="write_script" aiUserPrompt="Request{% if turn.violations %}x{% endif %}">'
	"</bpmn:serviceTask>"
)
LIBRARIES = [{"name": "Demo: Lib HTTP", "functions": ["post_json(url, body)"]}]


class TestLogixWriterSeesLibraryScripts(FrappeTestCase):
	def test_build_context_keeps_the_library_scripts(self):
		code = p.build_context(BUILD_CONTEXT)
		namespace = {"task_data": {"library_scripts": LIBRARIES}, "conversation_id": "c", "turns": {}}
		exec(code, {**namespace, "set_turn": lambda _c, data: namespace["turns"].update(data)})
		self.assertEqual(namespace["turns"]["library_scripts"], LIBRARIES)
		self.assertEqual(p.build_context(code), code)

	def test_the_writer_prompt_lists_each_library_function(self):
		xml = p.writer_prompt(MAP)
		self.assertEqual(xml.count("turn.library_scripts"), 2)
		self.assertNotIn("turn.library_scripts", xml.split('id="write_script"')[0])
		self.assertEqual(p.writer_prompt(xml), xml)
		block = (
			p.WRITER_BLOCK.replace("&quot;", '"')
			.replace("&lt;", "<")
			.replace("&gt;", ">")
			.replace("&#10;", "\n")
		)
		text = Template(block).render(turn={"library_scripts": LIBRARIES})
		self.assertIn("- Demo: Lib HTTP: post_json(url, body)", text)
		self.assertEqual(Template(block).render(turn={}), "")
