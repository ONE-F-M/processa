# Copyright (c) 2026, one-fm and contributors
"""Logix's script writer sees the library scripts on the map.

Build Context keeps the turn's library_scripts, and the write_script prompt lists them.
"""

import frappe

MODEL_NAME = "Logix \u2013 Script Task Agent"
BUILD_CONTEXT = "Logix \u2013 Build Context"
TURN_ANCHOR = '    "process_context": task_data.get("process_context") or {},\n'
TURN_LINE = '    "library_scripts": task_data.get("library_scripts") or [],\n'
WRITER_ANCHOR = "{% if turn.violations %}"
WRITER_BLOCK = (
	"{% if turn.library_scripts %}**LIBRARY SCRIPTS ON THIS MAP** (call one with "
	"lib = import_script(&quot;&lt;library name&gt;&quot;), then lib.&lt;function&gt;(...)):&#10;"
	"{% for lib in turn.library_scripts %}- {{ lib.name }}: {{ lib.functions | join(&quot;, &quot;) }}&#10;"
	"{% if lib.code %}```python&#10;{{ lib.code }}&#10;```&#10;{% endif %}{% endfor %}&#10;{% endif %}"
)


def execute():
	code = frappe.db.get_value("Server Script", BUILD_CONTEXT, "script")
	if code and build_context(code) != code:
		frappe.db.set_value(
			"Server Script", BUILD_CONTEXT, "script", build_context(code), update_modified=False
		)
	elif code and TURN_LINE not in code:
		frappe.log_error(title="logix_writer_sees_library_scripts: anchor not found", message=BUILD_CONTEXT)
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if xml and writer_prompt(xml) == xml and "turn.library_scripts" not in xml:
		frappe.log_error(title="logix_writer_sees_library_scripts: anchor not found", message=MODEL_NAME)
	if writer_prompt(xml) != xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", writer_prompt(xml))
		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)


def build_context(code: str) -> str:
	"""Build Context with library_scripts kept in the turn, or the input when done or the anchor is missing."""
	if TURN_LINE in code or code.count(TURN_ANCHOR) != 1:
		return code
	return code.replace(TURN_ANCHOR, TURN_ANCHOR + TURN_LINE)


def writer_prompt(xml: str) -> str:
	"""The map with the library list in write_script's prompt, or the input when done or the anchor is missing."""
	start = xml.find('<bpmn:serviceTask id="write_script"')
	end = xml.find("</bpmn:serviceTask>", start)
	anchor = xml.find(WRITER_ANCHOR, start)
	if start < 0 or anchor < 0 or anchor > end or "turn.library_scripts" in xml[start:end]:
		return xml
	return xml[:anchor] + WRITER_BLOCK + xml[anchor:]
