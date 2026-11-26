"""ProsAlly answers without a redraw: diagnose an error, compare with a spec, tidy the layout, type plain tasks, edit the diagram."""

import html
import re
from xml.etree import ElementTree as ET

import frappe

from processa.ai_agent_registry.definitions.prosally.helpers import (
	NS,
	STEP_TAGS,
	register_namespaces,
)
from processa.ai_agent_registry.definitions.prosally.tools_pipeline import (
	has_lanes,
)

DIAGNOSE_ERROR_CHARS = 3000
DIAGNOSE_ELEMENT_CHARS = 1500
DIAGNOSE_MAX_ELEMENTS = 5
DIAGNOSE_SCRIPT_CHARS = 4000
DIAGNOSE_MIN_NAME_CHARS = 3
DIAGNOSE_ORIGINS = frozenset({"map", "server_script", "unknown"})

IR_SKIPPED_TAGS = frozenset({"laneSet", "extensionElements", "incoming", "outgoing", "documentation"})


DI_ELEMENT = re.compile(
	r'(?P<open><(?P<tag>bpmndi:BPMN(?:Shape|Edge))\b[^>]*?\bbpmnElement="(?P<id>[^"]+)"[^>]*>)(?P<body>.*?)(?P<close></(?P=tag)>)',
	re.S,
)
WAYPOINT = re.compile(r'<di:waypoint\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s*/>')
BOUNDS = re.compile(
	r'<dc:Bounds\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s+width="(-?[\d.]+)"\s+height="(-?[\d.]+)"'
)
LABEL = re.compile(r"<bpmndi:BPMNLabel\b.*?</bpmndi:BPMNLabel>", re.S)
COMPILED_POOL = "Participant_1"


def _route(flow_id: str, flows: dict, drawn: dict, inferred: set) -> list | None:
	"""The points of a flow, run through any gateway the compiler added, which meet at that gateway's centre."""
	source, target = flows[flow_id]
	points = WAYPOINT.findall(drawn[flow_id])
	while source in inferred:
		into = [f for f, ends in flows.items() if ends[1] == source]
		if len(into) != 1 or into[0] not in drawn:
			return None
		points = [*WAYPOINT.findall(drawn[into[0]])[:-1], _centre(drawn[source]), *points[1:]]
		source = flows[into[0]][0]
	while target in inferred:
		out = [f for f, ends in flows.items() if ends[0] == target]
		if len(out) != 1 or out[0] not in drawn:
			return None
		points = [*points[:-1], _centre(drawn[target]), *WAYPOINT.findall(drawn[out[0]])[1:]]
		target = flows[out[0]][1]
	return points


def _centre(body: str) -> tuple[str, str]:
	x, y, width, height = (float(v) for v in BOUNDS.search(body).groups())
	return f"{x + width / 2:g}", f"{y + height / 2:g}"


def _attribute(attrs: str, name: str) -> str:
	return re.search(r"\b" + name + r'="([^"]*)"', attrs)[1]


LIST_ITEM = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|[a-z][.)])\s+(.+?)\s*$", re.I)


def spec_items(text: str) -> list[str]:
	"""The bulleted or numbered lines of text, or dash items run together after a comma or colon, without their markers."""
	plain = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<(?:br|/p|/li|/div)[^>]*>", "\n", text or "")))
	lines = re.sub(r"[,:]\s+(?=[-*\u2022]\s)", "\n", plain).splitlines()
	return [m.group(1) for line in lines if (m := LIST_ITEM.match(line))]


def _mentions(text: str, value: str | None) -> bool:
	"""True when a name or id of at least a few characters appears in the text."""
	return bool(value) and len(value) >= DIAGNOSE_MIN_NAME_CHARS and value in text


def script_task_for_error(xml: str, error_text: str) -> dict | None:
	"""The script task an error names by task id, task name or Server Script, with the script source when readable."""
	if not (xml or "").strip():
		return None
	register_namespaces()
	script_attribute = "{" + NS["spiffworkflow"] + "}serverScript"
	for task in ET.fromstring(xml).iter("{" + NS["bpmn"] + "}scriptTask"):
		script_name = task.get(script_attribute) or ""
		if not any(_mentions(error_text, value) for value in (task.get("id"), task.get("name"), script_name)):
			continue
		readable = frappe.db.exists("Server Script", script_name) and frappe.has_permission(
			"Server Script", "read", doc=script_name
		)
		source = frappe.db.get_value("Server Script", script_name, "script") if readable else ""
		return {
			"id": task.get("id"),
			"name": task.get("name") or "",
			"script_name": script_name,
			"script": (source or "")[:DIAGNOSE_SCRIPT_CHARS],
		}
	return None


LANE_MOVE_VERBS = r"\b(?:move|put|bring|shift|place|drag|relocate)\b"
# Words a move may carry before the lane is named, and after it, without asking for anything else.
LANE_MOVE_LEAD = re.compile(LANE_MOVE_VERBS + r"|\b(?:back|the|and|both|steps?|tasks?|please)\b", re.I)
LANE_MOVE_TAIL = re.compile(r"\b(?:lane|swimlane|swim|please)\b", re.I)


def lane_move(xml: str, text: str) -> dict | None:
	"""The steps and the lane of a message that only asks to move steps on the diagram into one of its lanes."""
	if not has_lanes(xml) or not re.search(LANE_MOVE_VERBS, text, re.I):
		return None
	bpmn = "{" + NS["bpmn"] + "}"
	root = ET.fromstring(xml)
	lanes = [(_name_pattern(e.get("name") or ""), e) for e in root.iter(bpmn + "lane")]
	where = lane = None
	for pattern, candidate in sorted(lanes, key=lambda found: -len(found[0])):
		where = pattern and re.search(r"\b(?:in\s?to|to|under|in)\s+(?:the\s+)?" + pattern, text, re.I)
		if where:
			lane = candidate
			break
	if lane is None:
		return None
	here = {(ref.text or "").strip() for ref in lane.findall(bpmn + "flowNodeRef")}
	asked = text[: where.start()]
	steps = []
	# Only top-level steps sit in a lane; a step inside a sub-process moves with it.
	named = [(_name_pattern(e.get("name") or ""), e) for p in root.iter(bpmn + "process") for e in p if e.tag in STEP_TAGS]
	for pattern, step in sorted(named, key=lambda found: -len(found[0])):
		if not pattern:
			continue
		# A step whose own name runs into the lane phrase makes the message read two ways.
		if any(m.start() < where.end() and m.end() > where.start() for m in re.finditer(pattern, text, re.I)):
			return None
		asked, found = re.subn(pattern, " ", asked, flags=re.I)
		if not found:
			continue
		if sum(1 for other, _elem in named if other == pattern) > 1:
			return None
		if step.get("id") not in here:
			steps.append({"id": step.get("id"), "name": step.get("name")})
	# Anything else the message asks for is a change to the process, which this move would drop.
	rest = LANE_MOVE_LEAD.sub(" ", asked) + " " + LANE_MOVE_TAIL.sub(" ", text[where.end() :])
	if not steps or re.search(r"\w", rest):
		return None
	return {"steps": steps, "lane": {"id": lane.get("id"), "name": lane.get("name")}}


def _name_pattern(name: str) -> str:
	"""A pattern for name as a person types it, whole words only; empty when name has no letter or digit."""
	words = [re.escape(word) for word in re.split(r"[\W_]+", name) if word]
	return r"\b" + r"[\s\-]*".join(words) + r"\b" if words else ""


NONE_TASK_KEPT_ATTRIBUTES = ("id", "name", "default")
NONE_TASK_KEPT_CHILDREN = ("incoming", "outgoing", "documentation")


