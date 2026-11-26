"""ProsAlly finds the step or subprocess a request names and draws subprocesses into the diagram."""

import re
from xml.etree import ElementTree as ET


from processa.ai_agent_registry.definitions.prosally.helpers import (
	NS,
	register_namespaces,
)

SUBPROCESS_KEPT_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("incoming", "outgoing", "extensionElements", "documentation")
)
ID_REF_ATTRS = ("id", "sourceRef", "targetRef", "bpmnElement", "default", "attachedToRef")

SUBPROCESS_REQUEST = re.compile(r"sub[\s-]?process\s+(?:for|of|on)\s+(?:the\s+)?(?:step\s+)?([^:,.;\n]+)", re.I)
BECOME_SUBPROCESS = re.compile(
	r"([^:,.;\n]+?)\s+(?:should\s+be|must\s+be|needs?\s+to\s+be|to\s+be|become|becomes|into|as|a|an)\s+(?:a\s+|an\s+)?(?:expanded\s+)?sub[\s-]?process",
	re.I,
)

RECENT_REPLIES = 10
DEFINITE_SUBPROCESS = re.compile(r"(?<!new\s)\b(?:the|that|this|my|your)\s+sub[\s-]?p(?:ro|or)ces{1,2}\b", re.I)
TYPO_SIMILARITY = 0.75
POSITION_WORDS = (
	r"\b(?:after|before|following|preceding|then|next\s+to|beside|alongside|near|adjacent\s+to|above|below)\s+(?:the\s+|a\s+)?$"
)
CALL_ACTIVITY_CONVERSION = re.compile(
	r"\b(?:as|into|to)\s+(?:a\s+|an\s+)?call[\s-]?activit|\b(?:make|turn|convert|change)\b[^.:]{0,80}\bcall[\s-]?activit", re.I
)
EXPANDED_PAD = 24
EXPANDED_HEADER = 36

NODE_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag
	for tag in (
		"task",
		"userTask",
		"serviceTask",
		"scriptTask",
		"manualTask",
		"businessRuleTask",
		"sendTask",
		"receiveTask",
		"subProcess",
		"callActivity",
		"startEvent",
		"endEvent",
		"intermediateCatchEvent",
		"intermediateThrowEvent",
		"exclusiveGateway",
		"parallelGateway",
		"inclusiveGateway",
		"eventBasedGateway",
	)
)
INSERT_GAP = 50
SUBPROCESS_SIZE = (100, 80)
LIBRARIES_GAP = 60


def add_flow_references(scope: ET.Element) -> None:
	"""Give each step of scope the incoming and outgoing flow references the editor and its linter read."""
	bpmn = "{" + NS["bpmn"] + "}"
	steps = {e.get("id"): e for e in scope if e.get("id") and e.tag != bpmn + "sequenceFlow"}
	for flow in scope.findall(bpmn + "sequenceFlow"):
		for ref, tag in ((flow.get("sourceRef"), "outgoing"), (flow.get("targetRef"), "incoming")):
			step = steps.get(ref)
			if step is not None and flow.get("id") not in [c.text for c in step.findall(bpmn + tag)]:
				ET.SubElement(step, bpmn + tag).text = flow.get("id")


def take_out_libraries(xml: str) -> tuple[str, list]:
	"""(xml without its Libraries boxes, the boxes with their drawing), so a change to the flow never touches them."""
	if 'scriptLibrary="true"' not in (xml or ""):
		return xml, []
	register_namespaces()
	try:
		root = ET.fromstring(xml)
	except ET.ParseError:
		return xml, []
	bpmn, bpmndi = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}"
	libraries = []
	for process in root.iter(bpmn + "process"):
		for box in [child for child in process if is_libraries_box(child)]:
			ids = {e.get("id") for e in box.iter() if e.get("id")}
			process.remove(box)
			for lane in root.iter(bpmn + "lane"):
				for ref in [r for r in lane.findall(bpmn + "flowNodeRef") if (r.text or "").strip() in ids]:
					lane.remove(ref)
			shapes = []
			for plane in root.iter(bpmndi + "BPMNPlane"):
				for drawn in [d for d in plane if d.get("bpmnElement") in ids]:
					plane.remove(drawn)
					shapes.append(ET.tostring(drawn, encoding="unicode"))
			libraries.append(
				{
					"process": process.get("id"),
					"element": ET.tostring(box, encoding="unicode"),
					"shapes": shapes,
				}
			)
	return (_serialize(root), libraries) if libraries else (xml, [])


def put_back_libraries(xml: str, libraries: list) -> str:
	"""xml with each Libraries box back in its process, drawn below everything else and aligned to the left edge."""
	if not libraries or not xml:
		return xml
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn, bpmndi, dc = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}", "{" + NS["dc"] + "}"
	processes = {p.get("id"): p for p in root.iter(bpmn + "process")}
	plane = next(root.iter(bpmndi + "BPMNPlane"), None)
	for library in libraries:
		process = processes.get(library["process"]) or next(iter(processes.values()))
		box = ET.fromstring(library["element"])
		process.append(box)
		shapes = [ET.fromstring(s) for s in library["shapes"]]
		own = next((s for s in shapes if s.get("bpmnElement") == box.get("id")), None)
		if plane is None or own is None:
			continue
		bounds = list(plane.iter(dc + "Bounds"))
		left = min((float(b.get("x")) for b in bounds), default=0)
		bottom = max((float(b.get("y")) + float(b.get("height")) for b in bounds), default=0)
		box_bounds = own.find(dc + "Bounds")
		dx = left - float(box_bounds.get("x"))
		dy = bottom + LIBRARIES_GAP - float(box_bounds.get("y"))
		for shape in shapes:
			_shift(shape, dx, dy, lambda px, py: (px, py))
			plane.append(shape)
	return _serialize(root)


def is_libraries_box(element: ET.Element) -> bool:
	return (
		element.tag == "{" + NS["bpmn"] + "}adHocSubProcess"
		and element.get("{" + NS["spiffworkflow"] + "}scriptLibrary") == "true"
	)


def _serialize(root: ET.Element) -> str:
	text = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', text)


def _squash(text: str) -> str:
	return re.sub(r"[^a-z0-9]", "", text.lower())


def _extent(drawing: ET.Element) -> tuple:
	"""The left, top, right and bottom edges of everything drawn under drawing."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	xs, ys = [], []
	for b in drawing.iter(dc + "Bounds"):
		xs += [float(b.get("x")), float(b.get("x")) + float(b.get("width"))]
		ys += [float(b.get("y")), float(b.get("y")) + float(b.get("height"))]
	for p in drawing.iter(di + "waypoint"):
		xs.append(float(p.get("x")))
		ys.append(float(p.get("y")))
	return min(xs), min(ys), max(xs), max(ys)


def _make_room(plane: ET.Element, step_shape: ET.Element, edges: tuple, dw: float, dh: float) -> None:
	"""Move what is right of the step by dw and what is below it by dh; widen and heighten the lanes and pool."""
	dc, bpmndi = "{" + NS["dc"] + "}", "{" + NS["bpmndi"] + "}"
	right, bottom, centre = edges
	horizontal = [s for s in plane.findall(bpmndi + "BPMNShape") if s.get("isHorizontal") == "true"]
	containing = []
	for lane in horizontal:
		b = lane.find(dc + "Bounds")
		if float(b.get("y")) <= centre <= float(b.get("y")) + float(b.get("height")):
			containing.append(float(b.get("y")) + float(b.get("height")))
	lane_bottom = min(containing) if containing else None
	for drawn in plane:
		if drawn is step_shape:
			continue
		if drawn in horizontal:
			b = drawn.find(dc + "Bounds")
			b.set("width", coordinate_text(float(b.get("width")) + dw))
			top, height = float(b.get("y")), float(b.get("height"))
			if top <= centre <= top + height:
				b.set("height", coordinate_text(height + dh))
			elif lane_bottom is not None and top >= lane_bottom:
				b.set("y", coordinate_text(top + dh))
			continue
		_shift(drawn, 0, 0, lambda px, py: (px + dw if px >= right else px, py + dh if py >= bottom else py))


def _shift(drawn: ET.Element, dx: float, dy: float, rule) -> None:
	"""Move a shape, with its label, or an edge point by point: each point moves as rule says, then by dx and dy."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	own = drawn.find(dc + "Bounds")
	pinned = None if own is None else _offset(own, rule)
	for b in drawn.iter(dc + "Bounds"):
		ox, oy = pinned or _offset(b, rule)
		b.set("x", coordinate_text(float(b.get("x")) + ox + dx))
		b.set("y", coordinate_text(float(b.get("y")) + oy + dy))
	for p in drawn.iter(di + "waypoint"):
		ox, oy = _offset(p, rule)
		p.set("x", coordinate_text(float(p.get("x")) + ox + dx))
		p.set("y", coordinate_text(float(p.get("y")) + oy + dy))


def _offset(point: ET.Element, rule) -> tuple:
	x, y = float(point.get("x")), float(point.get("y"))
	new_x, new_y = rule(x, y)
	return new_x - x, new_y - y


def coordinate_text(value: float) -> str:
	return str(int(value)) if value == int(value) else str(round(value, 2))


def insert_after(xml: str, after_name: str | None, element: ET.Element, inner: tuple) -> dict | None:
	"""xml with element placed on the arrow that leaves the step named after_name, or the last step before the end.

	None when that step is not found, is not unique, or does not leave by exactly one arrow.
	"""
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + NS["bpmn"] + "}"
	anchor = _anchor(root, after_name)
	if anchor is None:
		return None
	parent = next(p for p in root.iter() if anchor in list(p))
	leaving = [f for f in parent.findall(bpmn + "sequenceFlow") if f.get("sourceRef") == anchor.get("id")]
	if len(leaving) != 1:
		return None
	taken = {e.get("id") for e in root.iter() if e.get("id")}
	new_id = _free_id(taken, "Activity")
	element.set("id", new_id)
	start, end, flow = inner or (None, None, None)
	if inner:
		start.set("id", _free_id(taken, "StartEvent"))
		end.set("id", _free_id(taken, "EndEvent"))
		flow.attrib.update(
			{"id": _free_id(taken, "Flow"), "sourceRef": start.get("id"), "targetRef": end.get("id")}
		)
		add_flow_references(element)
	old_flow = leaving[0]
	target = old_flow.get("targetRef")
	old_flow.set("targetRef", new_id)
	new_flow = ET.Element(
		bpmn + "sequenceFlow", {"id": _free_id(taken, "Flow"), "sourceRef": new_id, "targetRef": target}
	)
	position = list(parent).index(anchor) + 1
	parent.insert(position, element)
	parent.append(new_flow)
	add_flow_references(parent)
	for lane in root.iter(bpmn + "lane"):
		if any((ref.text or "").strip() == anchor.get("id") for ref in lane.findall(bpmn + "flowNodeRef")):
			ET.SubElement(lane, bpmn + "flowNodeRef").text = new_id
	_draw_inserted(root, anchor.get("id"), new_id, old_flow.get("id"), new_flow.get("id"), target)
	if inner:
		_draw_collapsed_inside(root, new_id, start.get("id"), end.get("id"), flow.get("id"))
	added = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return {
		"xml": re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', added),
		"name": element.get("name"),
		"after": anchor.get("name") or anchor.get("id"),
	}


def _anchor(root: ET.Element, after_name: str | None) -> ET.Element | None:
	"""The step named after_name, or the one step that leads into the end event."""
	bpmn = "{" + NS["bpmn"] + "}"
	if after_name:
		return named_node(root, after_name.strip())
	ends = [
		e
		for e in root.iter(bpmn + "endEvent")
		if any(p.tag == bpmn + "process" and e in list(p) for p in root.iter())
	]
	if len(ends) != 1:
		return None
	sources = [
		f.get("sourceRef")
		for f in root.iter(bpmn + "sequenceFlow")
		if f.get("targetRef") == ends[0].get("id")
	]
	if len(sources) != 1:
		return None
	return next((e for e in root.iter() if e.get("id") == sources[0]), None)


def named_node(root: ET.Element, name: str) -> ET.Element | None:
	"""The one flow node whose name is name, ignoring case, spaces and punctuation."""
	wanted = _squash(name)
	found = [
		e
		for e in root.iter()
		if e.get("name") and e.get("id") and _squash(e.get("name")) == wanted and e.tag in NODE_TAGS
	]
	return found[0] if len(found) == 1 else None


def _free_id(taken: set, prefix: str) -> str:
	"""An id that starts with prefix and is in no use, recorded in taken."""
	n = 1
	while f"{prefix}_{n}" in taken:
		n += 1
	taken.add(f"{prefix}_{n}")
	return f"{prefix}_{n}"


def _draw_inserted(
	root: ET.Element, anchor_id: str, new_id: str, old_flow_id: str, new_flow_id: str, target_id: str
) -> None:
	"""Draw the new step right of its anchor, push the rest right, and route both arrows straight."""
	dc, di, bpmndi = "{" + NS["dc"] + "}", "{" + NS["di"] + "}", "{" + NS["bpmndi"] + "}"
	plane = next(
		(p for p in root.iter(bpmndi + "BPMNPlane") if any(s.get("bpmnElement") == anchor_id for s in p)),
		None,
	)
	if plane is None:
		return
	anchor_shape = next(s for s in plane.findall(bpmndi + "BPMNShape") if s.get("bpmnElement") == anchor_id)
	b = anchor_shape.find(dc + "Bounds")
	x, y, w, h = (float(b.get(k)) for k in ("x", "y", "width", "height"))
	width, height = SUBPROCESS_SIZE
	_make_room(plane, anchor_shape, (x + w, y + h, y + h / 2), width + INSERT_GAP, 0)
	new_x, new_y = x + w + INSERT_GAP, y + h / 2 - height / 2
	shape = ET.SubElement(plane, bpmndi + "BPMNShape", {"id": new_id + "_di", "bpmnElement": new_id})
	ET.SubElement(
		shape,
		dc + "Bounds",
		{
			"x": coordinate_text(new_x),
			"y": coordinate_text(new_y),
			"width": coordinate_text(width),
			"height": coordinate_text(height),
		},
	)
	target_shape = next(
		(s for s in plane.findall(bpmndi + "BPMNShape") if s.get("bpmnElement") == target_id), None
	)
	old_edge = next(
		(e for e in plane.findall(bpmndi + "BPMNEdge") if e.get("bpmnElement") == old_flow_id), None
	)
	if old_edge is not None:
		for point in old_edge.findall(di + "waypoint"):
			old_edge.remove(point)
		ET.SubElement(
			old_edge, di + "waypoint", {"x": coordinate_text(x + w), "y": coordinate_text(y + h / 2)}
		)
		ET.SubElement(
			old_edge, di + "waypoint", {"x": coordinate_text(new_x), "y": coordinate_text(y + h / 2)}
		)
	if target_shape is not None:
		tb = target_shape.find(dc + "Bounds")
		edge = ET.SubElement(
			plane, bpmndi + "BPMNEdge", {"id": new_flow_id + "_di", "bpmnElement": new_flow_id}
		)
		ET.SubElement(
			edge, di + "waypoint", {"x": coordinate_text(new_x + width), "y": coordinate_text(y + h / 2)}
		)
		ET.SubElement(
			edge,
			di + "waypoint",
			{"x": tb.get("x"), "y": coordinate_text(float(tb.get("y")) + float(tb.get("height")) / 2)},
		)


def _draw_collapsed_inside(root: ET.Element, sub_id: str, start_id: str, end_id: str, flow_id: str) -> None:
	"""Give a collapsed sub-process its own drawing, holding its start, its end and the arrow between them."""
	dc, di, bpmndi = "{" + NS["dc"] + "}", "{" + NS["di"] + "}", "{" + NS["bpmndi"] + "}"
	diagram = ET.SubElement(root, bpmndi + "BPMNDiagram", {"id": sub_id + "_diagram"})
	plane = ET.SubElement(diagram, bpmndi + "BPMNPlane", {"id": sub_id + "_plane", "bpmnElement": sub_id})
	for element_id, x in ((start_id, 180), (end_id, 332)):
		shape = ET.SubElement(
			plane, bpmndi + "BPMNShape", {"id": element_id + "_di", "bpmnElement": element_id}
		)
		ET.SubElement(shape, dc + "Bounds", {"x": str(x), "y": "82", "width": "36", "height": "36"})
	edge = ET.SubElement(plane, bpmndi + "BPMNEdge", {"id": flow_id + "_di", "bpmnElement": flow_id})
	ET.SubElement(edge, di + "waypoint", {"x": "216", "y": "100"})
	ET.SubElement(edge, di + "waypoint", {"x": "332", "y": "100"})
