# Copyright (c) 2026, one-fm and contributors
"""The Frontend Agent's prompt names processa and its frontend folder instead of the one_bpmn app."""

import frappe

MODEL_NAME = "Frontend Agent v1"
REPLACEMENTS = (
	("under one_bpmn/spiff/src", "under processa/frontend/src"),
	(
		"spiff/ lives inside one_bpmn, so target_app is one_bpmn.",
		"frontend/ lives inside processa, so target_app is processa.",
	),
	("one_fm, one_bpmn, onefm_mcp", "one_fm, processa, onefm_mcp"),
)


def execute():
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if not xml or renamed(xml) == xml:
		return
	# db.set_value skips the production editability gate, as a trusted content migration.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", renamed(xml))
	from processa.api.deploy import compile_process_model

	compile_process_model(MODEL_NAME)


def renamed(xml: str) -> str:
	"""The map with each old phrase replaced; a phrase that is not there is left alone."""
	for old, new in REPLACEMENTS:
		xml = xml.replace(old, new)
	return xml
