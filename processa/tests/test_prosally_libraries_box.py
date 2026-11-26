# Copyright (c) 2026, one-fm and contributors
"""ProsAlly keeps a map's Libraries box through a change, a re-layout and a regenerate, and tells its stages about it."""

from processa.tests.library import library
import re
from xml.etree import ElementTree as ET

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally.helpers import NS
compile_ir = library("prosally_lib_layout.py").compile_ir
library_scripts_block = library("prosally_lib_map_xml.py").library_scripts_block
transfer_properties = library("prosally_lib_map_xml.py").transfer_properties
relayout = library("prosally_lib_layout.py").relayout
xml_to_ir = library("prosally_lib_map_xml.py").xml_to_ir
from processa.ai_agent_registry.definitions.prosally.tools_subprocess import (
	put_back_libraries,
	take_out_libraries,
)
from processa.patches.v1_0.add_prosally_library_question_case import library_map
from processa.patches.v1_0.seed_prosally_route_and_constraint_cases import MAP_XML

BPMN, BPMNDI, DC = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}", "{" + NS["dc"] + "}"
SPIFF = "{" + NS["spiffworkflow"] + "}"
BOX_IDS = {"Libraries_1", "Lib_Replies", "Lib_Dates"}


def _box(xml):
	return next(e for e in ET.fromstring(xml).iter(BPMN + "adHocSubProcess") if e.get("id") == "Libraries_1")


def _bounds(xml):
	"""Each drawn element's (x, y, right, bottom), keyed by its bpmnElement."""
	out = {}
	for shape in ET.fromstring(xml).iter(BPMNDI + "BPMNShape"):
		b = shape.find(DC + "Bounds")
		x, y = float(b.get("x")), float(b.get("y"))
		out[shape.get("bpmnElement")] = (x, y, x + float(b.get("width")), y + float(b.get("height")))
	return out


class TestLibrariesBoxKept(FrappeTestCase):
	def test_take_out_removes_the_box_and_its_drawing(self):
		rest, libraries = take_out_libraries(library_map())
		self.assertEqual(len(libraries), 1)
		self.assertNotIn("scriptLibrary", rest)
		self.assertFalse(BOX_IDS & set(_bounds(rest)))

	def test_put_back_keeps_ids_names_scripts_and_the_mark(self):
		rest, libraries = take_out_libraries(library_map())
		box = _box(put_back_libraries(rest, libraries))
		self.assertEqual(box.get(SPIFF + "scriptLibrary"), "true")
		self.assertEqual(
			{
				(t.get("id"), t.get("name"), t.get(SPIFF + "serverScript"))
				for t in box.iter(BPMN + "scriptTask")
			},
			{("Lib_Replies", "Replies", "Leave: Lib Replies"), ("Lib_Dates", "Dates", "Leave: Lib Dates")},
		)

	def test_the_box_sits_below_the_flow_and_holds_its_tasks(self):
		rest, libraries = take_out_libraries(library_map())
		bounds = _bounds(put_back_libraries(rest, libraries))
		box = bounds.pop("Libraries_1")
		tasks = [bounds.pop("Lib_Replies"), bounds.pop("Lib_Dates")]
		self.assertGreater(box[1], max(b[3] for b in bounds.values()))
		self.assertEqual(box[0], min(b[0] for b in bounds.values()))
		for x, y, right, bottom in tasks:
			self.assertTrue(box[0] <= x and right <= box[2] and box[1] <= y and bottom <= box[3])

	def test_no_sequence_flow_touches_the_box(self):
		rest, libraries = take_out_libraries(library_map())
		root = ET.fromstring(put_back_libraries(rest, libraries))
		for flow in root.iter(BPMN + "sequenceFlow"):
			self.assertFalse({flow.get("sourceRef"), flow.get("targetRef")} & BOX_IDS)

	def test_a_map_without_a_box_is_unchanged(self):
		self.assertEqual(take_out_libraries(MAP_XML), (MAP_XML, []))
		self.assertEqual(put_back_libraries(MAP_XML, []), MAP_XML)

	def test_nothing_is_reported_removed_when_the_box_is_set_aside(self):
		rest, _libraries = take_out_libraries(library_map())
		_merged, removed = transfer_properties(rest, rest)
		self.assertFalse(removed)

	def test_relayout_keeps_the_box_instead_of_refusing(self):
		ir = xml_to_ir(MAP_XML)
		if not compile_ir(ir).get("ok"):
			self.skipTest("node or pipeline.mjs unavailable")
		step = ir["nodes"][1]["id"]
		messy = re.sub(
			rf'(<bpmndi:BPMNShape id="[^"]*" bpmnElement="{step}">\s*<dc:Bounds x=")[\d.]+',
			r"\g<1>9999",
			library_map(),
		)
		moved, why = relayout(messy)
		self.assertEqual(why, "")
		self.assertNotIn('x="9999"', moved)
		self.assertEqual(_box(moved).get(SPIFF + "scriptLibrary"), "true")
		bounds = _bounds(moved)
		box = bounds.pop("Libraries_1")
		self.assertGreater(box[1], max(b[3] for k, b in bounds.items() if k not in BOX_IDS))


class TestLibraryScriptsBlock(FrappeTestCase):
	def test_lists_each_library_with_its_server_script(self):
		block = library_scripts_block({"current_xml": library_map()})
		self.assertIn("- Replies: Server Script Leave: Lib Replies", block)
		self.assertIn("- Dates: Server Script Leave: Lib Dates", block)
		self.assertIn("Never connect them", block)

	def test_empty_without_a_box(self):
		self.assertEqual(library_scripts_block({"current_xml": MAP_XML}), "")
		self.assertEqual(library_scripts_block(None), "")
