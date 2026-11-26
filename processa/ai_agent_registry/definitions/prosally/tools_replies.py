"""ProsAlly's replies that say what a redraw changed, or why nothing changed."""

import html
import re
from xml.etree import ElementTree as ET

from frappe import _

from processa.ai_agent_registry.definitions.prosally.helpers import (
	REQUEST_STOPWORDS,
	quoted,
)
from processa.ai_agent_registry.definitions.prosally.tools_pipeline import (
	check_topology,
	flow_pairs_from_xml,
)

# Plain words for the element types a designer sees in a change list.
_ELEMENT_WORDS = {
	"startEvent": "the start",
	"endEvent": "the end",
	"exclusiveGateway": "the decision",
	"inclusiveGateway": "the decision",
	"eventBasedGateway": "the decision",
	"parallelGateway": "the parallel split",
	"sequenceFlow": "the path",
	"subProcess": "the sub-process",
	"intermediateCatchEvent": "the event",
	"intermediateThrowEvent": "the event",
	"boundaryEvent": "the event",
	"userTask": "the step",
	"serviceTask": "the step",
	"scriptTask": "the step",
	"manualTask": "the step",
	"sendTask": "the step",
	"receiveTask": "the step",
	"businessRuleTask": "the step",
	"callActivity": "the step",
	"task": "the step",
}


def _lanes(xml: str) -> dict:
	"""{lane name: set of step ids} in diagram order; empty when the diagram has no lanes."""
	lanes = {}
	for attrs, body in re.findall(r"<bpmn:lane\s([^>]*)>(.*?)</bpmn:lane>", xml or "", re.S):
		values = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
		lanes[values.get("name") or values.get("id")] = set(re.findall(r"<bpmn:flowNodeRef>([^<]+)</bpmn:flowNodeRef>", body))
	return lanes


def _settings(xml: str) -> dict:
	"""{element id: its prefixed attributes such as spiffworkflow:workflowState} for elements that have any."""
	found = {}
	for attrs in re.findall(r"<bpmn:\w+\s([^>]*?)/?>", xml or ""):
		values = dict(re.findall(r'([\w.-]+:[\w.-]+)="([^"]*)"', attrs))
		values = {key: html.unescape(val) for key, val in values.items() if not key.startswith("xmlns")}
		elem_id = re.search(r'\bid="([^"]+)"', attrs)
		if values and elem_id:
			found[elem_id.group(1)] = values
	return found


# Element kinds a request can rule out ("no script tasks"), and the BPMN tags each one covers.
NO_ELEMENT_KINDS = {
	"script task": ("scriptTask",),
	"service task": ("serviceTask",),
	"user task": ("userTask",),
	"gateway": ("exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway"),
	"decision": ("exclusiveGateway", "inclusiveGateway", "eventBasedGateway"),
	"lane": ("lane",),
	"timer": ("timerEventDefinition",),
	"sub-process": ("subProcess",),
}
RULE_OUT = r"\b(?:no|without|avoid|never (?:use|add)|do not (?:use|add)|don'?t (?:use|add))\s+(?:any\s+|new\s+|extra\s+)?"
ONLY_WHAT_IS_NAMED = re.compile(
	r"\b(?:do not|don'?t|never)\s+(?:change|touch|modify|move|alter)\s+(?:anything|any other|the rest|other)"
	r"|\bnothing else\b|\bleave (?:the rest|everything else)\b|\bonly (?:change|edit|update|rename|add|remove)\b",
	re.I,
)
ASKS_FOR_A_GATEWAY = re.compile(
	r"\b(?:gateway|decision|condition|split|join|merge|parallel|branch|if|whether|either|otherwise)\b", re.I
)


def _named_in(name: str, text: str) -> bool:
	"""True when a significant word of name appears in text, matched on its first five letters."""
	asked = {word[:5] for word in re.findall(r"[a-z]{4,}", (text or "").lower())}
	words = [
		word[:5] for word in re.findall(r"[a-z]{4,}", (name or "").lower()) if word not in REQUEST_STOPWORDS
	]
	return bool(words) and any(word in asked for word in words)


def _element_label(kind: str, name: str) -> str:
	return _ELEMENT_WORDS.get(kind, "the element") + (" " + quoted(name) if name else "")


CROSSING_NOTE = "One crossing line is unavoidable"


NO_STAGE_REPLY = "NO_STAGE_REPLY"


def layout_change_summary(before: dict, after: dict, asks: list[str]) -> str:
	"""The measured change for each layout ask, each sentence led by a space."""
	said = ""
	if "crossings" in asks or before["crossings"] != after["crossings"]:
		said += " " + _("Crossing lines: {0} before, {1} now.").format(
			before["crossings"], after["crossings"]
		)
	if before["throughShape"] != after["throughShape"]:
		said += " " + _("Lines through a shape: {0} before, {1} now.").format(
			before["throughShape"], after["throughShape"]
		)
	if before["overlaps"] != after["overlaps"]:
		said += " " + _("Lines on top of each other: {0} before, {1} now.").format(
			before["overlaps"], after["overlaps"]
		)
	if "spacing" in asks:
		said += " " + _("The gaps between columns and lanes are sized to the lines they carry.")
	if "alignment" in asks:
		said += " " + _("Every step sits on the layout grid of columns and lanes.")
	if "convergence" in asks:
		said += " " + _("Lines that join meet at one point before the step they lead to.")
	return said


def layout_limits(xml: str, audit: dict, asks: list[str]) -> str:
	"""Why a layout that came out the same cannot meet each ask, each sentence led by a space."""
	said = ""
	if audit["crossings"]:
		topology = check_topology(flow_pairs_from_xml(xml))
		if topology["planar"] is False:
			names = {
				e.get("id"): e.get("name") or e.get("id") for e in ET.fromstring(xml).iter() if e.get("id")
			}
			who = ", ".join(quoted(names.get(n, n)) for n in topology["obstruction"][:5])
			said += " " + _(
				"{0} crossing line(s) stay because the paths through {1} cannot all be laid flat."
			).format(audit["crossings"], who)
		else:
			said += " " + _("I could not draw it with fewer than {0} crossing line(s).").format(
				audit["crossings"]
			)
	elif "crossings" in asks:
		said += " " + _("No lines cross.")
	if "spacing" in asks:
		said += " " + _(
			"I cannot set a gap of my own: the gaps are sized to the lines each column and lane carries."
		)
	if "alignment" in asks:
		said += " " + _("Every step already sits on the layout grid.")
	if "convergence" in asks:
		said += " " + _("Lines that join already meet where they join.")
	return said


LAYOUT_ASKS = (
	(
		"spacing",
		re.compile(r"\b(?:spac(?:e|ed|ing)|spread|cramped|crowded|squashed|too close|apart|gaps?)\b", re.I),
	),
	(
		"alignment",
		re.compile(r"\b(?:align\w*|misaligned|line[sd]? (?:them )?up|lined up|straighten\w*)\b", re.I),
	),
	(
		"crossings",
		re.compile(r"\b(?:cross(?:ing|es|ed)?|criss-?cross\w*|tangl\w*|untangle|overlap\w*)\b", re.I),
	),
	("convergence", re.compile(r"\b(?:converg\w*|come together|meet at)\b", re.I)),
)


def layout_is_automatic() -> str:
	"""What a person can do about the layout, since no single arrow, label or colour is placed by hand."""
	return _(
		"Layout is computed automatically, so I cannot place one arrow, label or colour by hand. "
		"You can drag shapes on the canvas, or change the flow structure and I will lay it out again."
	)
