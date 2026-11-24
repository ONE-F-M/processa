# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's map edits: operations applied to a map's IR, and the single edits it makes on the XML."""

import copy
import re
from xml.etree import ElementTree as ET

from frappe import _

from processa.ai_agent_registry.definitions.prosally.helpers import (
	IR_NODE_TYPES,
	NS,
	quoted,
	register_namespaces,
)
from processa.ai_agent_registry.definitions.prosally.tools_subprocess import (
	NODE_TAGS,
	add_flow_references,
	coordinate_text,
	insert_after,
	named_node,
)


def apply_operations(ir: dict, operations: list) -> tuple[dict | None, str]:
	"""(ir with every operation applied, "") or (None, which operation failed and why); ir itself never changes."""
	edited = copy.deepcopy(ir)
	for number, operation in enumerate(operations, 1):
		problem = _apply(edited, operation) if isinstance(operation, dict) else _("it is not an operation")
		if problem:
			return None, _('Change {0} ({1} "{2}") could not be made: {3}.').format(
				number,
				operation.get("op", "") if isinstance(operation, dict) else "",
				_label(operation),
				problem,
			)
	return edited, ""


def _apply(ir: dict, operation: dict) -> str:
	handler = {"add": _add, "remove": _remove, "rename": _rename, "reconnect": _reconnect}.get(
		operation.get("op")
	)
	if handler is None:
		return _("it is not one of add, remove, rename or reconnect")
	return handler(ir, operation)


def _add(ir: dict, operation: dict) -> str:
	kind, new_id = operation.get("type"), operation.get("id")
	if not new_id:
		return _("the new element needs an id that is not used yet")
	if _element(ir, new_id):
		return _("the new element needs an id that is not used yet")
	if kind == "sequenceFlow":
		ends = _ends_problem(ir, operation.get("from"), operation.get("to"))
		if ends:
			return ends
		flow = {"id": new_id, "from": operation["from"], "to": operation["to"]}
		flow.update({key: operation[key] for key in ("name", "condition", "default") if operation.get(key)})
		ir["flows"].append(flow)
	elif kind == "lane":
		if not ir["lanes"]:
			return _("the diagram has no lanes, so a lane cannot be added to it")
		ir["lanes"].append({"id": new_id, "name": operation.get("name") or new_id})
	elif kind in IR_NODE_TYPES:
		lane = _lane_problem(ir, operation.get("lane"))
		if lane:
			return lane
		node = {"id": new_id, "name": operation.get("name") or "", "type": kind}
		if operation.get("lane"):
			node["lane"] = operation["lane"]
		ir["nodes"].append(node)
	else:
		return _("{0} is not a kind of element the diagram can hold").format(kind)
	return ""


def _remove(ir: dict, operation: dict) -> str:
	target = operation.get("id")
	node = _by_id(ir["nodes"], target)
	if node:
		into = [f for f in ir["flows"] if f["to"] == target]
		out = [f for f in ir["flows"] if f["from"] == target]
		ir["nodes"].remove(node)
		# A step on a single path is taken out of it, and the path closes up behind it.
		on_one_path = len(into) == 1 and len(out) == 1
		if on_one_path and into[0] is not out[0]:
			into[0]["to"] = out[0]["to"]
			ir["flows"].remove(out[0])
		else:
			ir["flows"] = [f for f in ir["flows"] if target not in (f["from"], f["to"])]
		return ""
	flow = _by_id(ir["flows"], target)
	if flow:
		ir["flows"].remove(flow)
		return ""
	lane = _by_id(ir["lanes"], target)
	if lane:
		if any(n.get("lane") == target for n in ir["nodes"]):
			return _("the lane still has steps in it")
		ir["lanes"].remove(lane)
		return ""
	return _missing(target)


def _rename(ir: dict, operation: dict) -> str:
	element = _element(ir, operation.get("id"))
	if not element:
		return _missing(operation.get("id"))
	if not operation.get("name"):
		return _("the new name is empty")
	element["name"] = operation["name"]
	return ""


def _reconnect(ir: dict, operation: dict) -> str:
	flow = _by_id(ir["flows"], operation.get("id"))
	if not flow:
		return _("there is no arrow with the id {0}").format(operation.get("id"))
	source, target = operation.get("from") or flow["from"], operation.get("to") or flow["to"]
	ends = _ends_problem(ir, source, target)
	if ends:
		return ends
	flow["from"], flow["to"] = source, target
	return ""


def _ends_problem(ir: dict, source: str | None, target: str | None) -> str:
	for end in (source, target):
		if not _by_id(ir["nodes"], end):
			return _("an arrow can only join steps on the diagram, and {0} is not one").format(end)
	return ""


def _lane_problem(ir: dict, lane: str | None) -> str:
	if ir["lanes"] and not _by_id(ir["lanes"], lane):
		return _("a new step needs one of the diagram's lanes: {0}").format(
			", ".join(lane["id"] for lane in ir["lanes"])
		)
	if lane and not ir["lanes"]:
		return _("the diagram has no lanes, so the step cannot go in one")
	return ""


def _element(ir: dict, element_id: str | None) -> dict | None:
	return (
		_by_id(ir["nodes"], element_id) or _by_id(ir["flows"], element_id) or _by_id(ir["lanes"], element_id)
	)


def _by_id(items: list, element_id: str | None) -> dict | None:
	return next((item for item in items if element_id and item.get("id") == element_id), None)


def _missing(element_id: str | None) -> str:
	return _("there is no step, arrow or lane called {0} on the diagram").format(element_id)


def _label(operation) -> str:
	return (
		(operation.get("name") or operation.get("id") or "")
		if isinstance(operation, dict)
		else str(operation)
	)


ADD_SUBPROCESS = re.compile(
	r"^\s*(?:please\s+)?add\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?[\"']?(?P<name>[^\"',.;:\n]+?)[\"']?\s+sub[\s-]?process"
	r"(?:\s+(?:after|following)\s+(?:the\s+)?[\"']?(?P<after>[^\"'.;:\n]+?)[\"']?)?\s*[.!]?\s*$",
	re.I,
)
ADD_WORKFLOW_STATE = re.compile(
	r"^\s*(?:please\s+)?add\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:workflow\s+state\s+[\"']?(?P<state>[^\"',.;:\n]+?)[\"']?"
	r"|[\"']?(?P<state2>[^\"',.;:\n]+?)[\"']?\s+workflow\s+state)"
	r"(?:\s+(?:after|following)\s+(?:the\s+)?[\"']?(?P<after>[^\"'.;:\n]+?)[\"']?)?\s*[.!]?\s*$",
	re.I,
)


def add_subprocess_output(xml: str, text: str) -> dict | None:
	"""The reply to "add a <name> sub-process [after <step>]": a new collapsed sub-process in the flow, or None."""
	match = ADD_SUBPROCESS.match(text or "")
	if not match:
		return None
	name = match["name"].strip()
	# Naming a step that exists asks to turn that step into a sub-process, which another route does.
	if named_node(ET.fromstring(xml), name) is not None:
		return None
	bpmn = "{" + NS["bpmn"] + "}"
	sub = ET.Element(bpmn + "subProcess", {"name": name})
	start = ET.SubElement(sub, bpmn + "startEvent", {"id": "", "name": _("Start")})
	end = ET.SubElement(sub, bpmn + "endEvent", {"id": "", "name": _("End")})
	inner = ET.SubElement(sub, bpmn + "sequenceFlow", {"id": "", "sourceRef": "", "targetRef": ""})
	added = insert_after(xml, match["after"], sub, (start, end, inner))
	if not added:
		return None
	return _inserted_reply(
		added, "ADD_SUBPROCESS", _("I added the sub-process {0} after {1}. Open it to draw its steps.")
	)


def add_workflow_state_output(xml: str, text: str) -> dict | None:
	"""The reply to "add the workflow state <state> [after <step>]": an Apply Workflow step in the flow, or None."""
	match = ADD_WORKFLOW_STATE.match(text or "")
	if not match:
		return None
	state = (match["state"] or match["state2"]).strip()
	bpmn, spiff = "{" + NS["bpmn"] + "}", "{" + NS["spiffworkflow"] + "}"
	task = ET.Element(
		bpmn + "serviceTask",
		{
			"name": _("Set Workflow State {0}").format(state),
			spiff + "serviceType": "apply_workflow",
			spiff + "workflowState": state,
		},
	)
	added = insert_after(xml, match["after"], task, ())
	if not added:
		return None
	return _inserted_reply(
		added,
		"ADD_WORKFLOW_STATE",
		_("I added the step {0} after {1}. Pick the role allowed to edit in that state on the step."),
	)


def _inserted_reply(added: dict, action: str, message: str) -> dict:
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": action,
		"bpmn_xml": added["xml"],
		"response": message.format(quoted(added["name"]), quoted(added["after"]))
		+ " "
		+ _("Every other step, arrow and setting is kept. Review it on the canvas."),
		"options": [],
	}


GATEWAY_KINDS = {
	"parallel": "parallelGateway",
	"exclusive": "exclusiveGateway",
	"inclusive": "inclusiveGateway",
}
SWITCH_ALL_GATEWAYS = re.compile(
	r"\b(?:make|change|switch|convert|turn|replace)\b\s+(?:every|all|each)\s+(?:of\s+the\s+|the\s+)?"
	r"(?P<old>parallel|exclusive|inclusive)\s+gateways?\s+(?:(?:to|into|with)\s+(?:an?\s+)?)?"
	r"(?P<new>parallel|exclusive|inclusive)\b",
	re.I,
)
SWITCH_NAMED_GATEWAY = re.compile(
	r"\b(?:make|change|switch|convert|turn)\b\s+(?:the\s+)?(?:gateway\s+)?[\"']?(?P<name>[^\"'.;:\n]+?)[\"']?\s+"
	r"(?:gateway\s+)?(?:to|into)\s+(?:an?\s+)?(?P<new>parallel|exclusive|inclusive)(?:\s+gateway)?\b",
	re.I,
)
REROUTE = re.compile(
	r"\b(?:reroute|redirect|move|point|change|connect)\b\s+(?:the\s+)?(?:arrow|flow|line|connection)?\s*from\s+[\"']?(?P<source>[^\"'\n]+?)[\"']?\s+"
	r"to\s+[\"']?(?P<old>[^\"'\n]+?)[\"']?\s+(?:so\s+(?:that\s+)?it\s+goes\s+|to\s+go\s+|and\s+point\s+it\s+|instead\s+)?to\s+[\"']?(?P<new>[^\"'.;\n]+?)[\"']?\s*[.!]?\s*$",
	re.I,
)
REROUTE_INSTEAD = re.compile(
	r"\b(?:reroute|redirect|move|point|change|connect)\b\s+(?:the\s+)?(?:arrow|flow|line|connection)?\s*from\s+[\"']?(?P<source>[^\"'\n]+?)[\"']?\s+"
	r"to\s+[\"']?(?P<new>[^\"'\n]+?)[\"']?\s+instead\s+of\s+[\"']?(?P<old>[^\"'.;\n]+?)[\"']?\s*[.!]?\s*$",
	re.I,
)


def switch_gateways_output(xml: str, text: str) -> dict | None:
	"""The reply to "make every parallel gateway exclusive" or "change <gateway> to exclusive", or None."""
	every = SWITCH_ALL_GATEWAYS.search(text or "")
	named = None if every else SWITCH_NAMED_GATEWAY.search(text or "")
	if not (every or named):
		return None
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + NS["bpmn"] + "}"
	if every:
		old, new = every["old"].lower(), every["new"].lower()
		gateways = list(root.iter(bpmn + GATEWAY_KINDS[old]))
	else:
		gateway = named_node(root, named["name"])
		if gateway is None or not gateway.tag.endswith("Gateway"):
			return None
		new = named["new"].lower()
		gateways = [gateway]
	gateways = [g for g in gateways if g.tag != bpmn + GATEWAY_KINDS[new]]
	if not gateways:
		return {
			"intent": "CLARIFY",
			"response": _("Every gateway you named is already {0}, so I changed nothing.").format(new),
		}
	to_ask = []
	for gateway in gateways:
		to_ask += _switch_gateway(root, gateway, bpmn + GATEWAY_KINDS[new])
	reply = _("I made {0} gateway(s) {1}. Every step and arrow is kept.").format(len(gateways), new)
	if to_ask:
		reply += " " + _(
			"An exclusive gateway takes one path, so I made the first path of each the default. "
			"Tell me when each of these other paths should be taken: {0}."
		).format(", ".join(to_ask))
	return _edited_reply(root, "SWITCH_GATEWAYS", reply + " " + _("Review it on the canvas."))


def _switch_gateway(root: ET.Element, gateway: ET.Element, new_tag: str) -> list[str]:
	"""Change gateway to new_tag in place; the paths that now need a condition from the person, by name."""
	bpmn = "{" + NS["bpmn"] + "}"
	gateway.tag = new_tag
	leaving = [f for f in root.iter(bpmn + "sequenceFlow") if f.get("sourceRef") == gateway.get("id")]
	if new_tag.endswith("parallelGateway"):
		gateway.attrib.pop("default", None)
		for flow in leaving:
			for condition in flow.findall(bpmn + "conditionExpression"):
				flow.remove(condition)
		return []
	if len(leaving) < 2:
		return []
	unconditioned = [f for f in leaving if f.find(bpmn + "conditionExpression") is None]
	if unconditioned and not gateway.get("default"):
		gateway.set("default", unconditioned[0].get("id"))
	names = _node_names(root)
	return [
		quoted(f.get("name") or _("to {0}").format(names.get(f.get("targetRef"), f.get("targetRef"))))
		for f in unconditioned
		if f.get("id") != gateway.get("default")
	]


def reroute_arrow_output(xml: str, text: str) -> dict | None:
	"""The reply to "reroute the arrow from A to B so it goes to C", or None."""
	match = REROUTE_INSTEAD.search(text or "") or REROUTE.search(text or "")
	if not match:
		return None
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + NS["bpmn"] + "}"
	source, old, new = (named_node(root, match[key]) for key in ("source", "old", "new"))
	if source is None or old is None or new is None:
		return None
	flows = [
		f
		for f in root.iter(bpmn + "sequenceFlow")
		if f.get("sourceRef") == source.get("id") and f.get("targetRef") == old.get("id")
	]
	if len(flows) != 1:
		return None
	flow = flows[0]
	flow.set("targetRef", new.get("id"))
	for node in (old, new):
		for ref in node.findall(bpmn + "incoming"):
			node.remove(ref)
	for parent in root.iter():
		if parent.find(bpmn + "sequenceFlow") is not None:
			add_flow_references(parent)
	_redraw_edge(root, flow.get("id"), source.get("id"), new.get("id"))
	return _edited_reply(
		root,
		"REROUTE_ARROW",
		_(
			"The arrow from {0} now goes to {1} instead of {2}. Everything else is kept. Review it on the canvas."
		).format(quoted(source.get("name")), quoted(new.get("name")), quoted(old.get("name"))),
	)


def _redraw_edge(root: ET.Element, flow_id: str, source_id: str, target_id: str) -> None:
	"""Draw the arrow flow_id straight from the right of source_id to the left of target_id."""
	dc, di, bpmndi = "{" + NS["dc"] + "}", "{" + NS["di"] + "}", "{" + NS["bpmndi"] + "}"
	shapes = {s.get("bpmnElement"): s.find(dc + "Bounds") for s in root.iter(bpmndi + "BPMNShape")}
	edge = next((e for e in root.iter(bpmndi + "BPMNEdge") if e.get("bpmnElement") == flow_id), None)
	if edge is None or shapes.get(source_id) is None or shapes.get(target_id) is None:
		return
	for point in edge.findall(di + "waypoint"):
		edge.remove(point)
	sb, tb = shapes[source_id], shapes[target_id]
	ET.SubElement(
		edge,
		di + "waypoint",
		{
			"x": coordinate_text(float(sb.get("x")) + float(sb.get("width"))),
			"y": coordinate_text(float(sb.get("y")) + float(sb.get("height")) / 2),
		},
	)
	ET.SubElement(
		edge,
		di + "waypoint",
		{"x": tb.get("x"), "y": coordinate_text(float(tb.get("y")) + float(tb.get("height")) / 2)},
	)


def _node_names(root: ET.Element) -> dict:
	return {e.get("id"): e.get("name") or e.get("id") for e in root.iter() if e.tag in NODE_TAGS}


def _edited_reply(root: ET.Element, action: str, response: str) -> dict:
	edited = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": action,
		"bpmn_xml": re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', edited),
		"response": response,
		"options": [],
	}
