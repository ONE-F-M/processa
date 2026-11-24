# Copyright (c) 2026, one-fm and contributors
"""The Frontend Agent prompt stops naming one_bpmn."""

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import frontend_agent_names_processa as p

PROMPT = (
	'<bpmn:serviceTask id="build_change" spiffworkflow:aiSystemPrompt="the Processa Vue application '
	"under one_bpmn/spiff/src, Frappe desk JavaScript. a folder inside an app is not an app: spiff/ lives "
	'inside one_bpmn, so target_app is one_bpmn.   Ours &#8212; one_fm, one_bpmn, onefm_mcp, frappe_agile" />'
)


class TestFrontendAgentNamesProcessa(FrappeTestCase):
	def test_every_one_bpmn_phrase_is_replaced(self):
		xml = p.renamed(PROMPT)
		self.assertNotIn("one_bpmn", xml)
		self.assertIn("under processa/frontend/src", xml)
		self.assertIn("frontend/ lives inside processa, so target_app is processa.", xml)
		self.assertIn("one_fm, processa, onefm_mcp", xml)

	def test_a_renamed_map_is_left_alone(self):
		xml = p.renamed(PROMPT)
		self.assertEqual(p.renamed(xml), xml)
