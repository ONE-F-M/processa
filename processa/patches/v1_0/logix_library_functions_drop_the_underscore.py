# Copyright (c) 2026, one-fm and contributors
"""When Logix moves a function into a library it drops a leading underscore, so import_script can hand it over."""

import frappe

MODEL_NAME = "Logix \u2013 Script Task Agent"
OLD = "copy the function in as written."
NEW = "copy the function in, dropping a leading underscore from its name so other scripts can call it."


def execute():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if writer_prompt(xml) == xml:
		return
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", writer_prompt(xml))
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def writer_prompt(xml: str) -> str:
	"""The map with the move-into-a-library sentence in write_script updated, or the input when not there once."""
	start = xml.find('<bpmn:serviceTask id="write_script"')
	end = xml.find("</bpmn:serviceTask>", start)
	if start < 0 or xml.count(OLD, start, end) != 1:
		return xml
	return xml[:start] + xml[start:end].replace(OLD, NEW) + xml[end:]
