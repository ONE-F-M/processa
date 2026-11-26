# ProsAlly layout: compile the diagram IR with the node pipeline, lay it out again and describe the layout.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _ns():
	return {
		"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
		"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
		"dc": "http://www.omg.org/spec/DD/20100524/DC",
		"di": "http://www.omg.org/spec/DD/20100524/DI",
		"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
		"custom": "http://custom/text-style",
		"camunda": "http://camunda.org/schema/1.0/bpmn",
	}


def _step_tags():
	return tuple(
		"{" + _ns()["bpmn"] + "}" + tag
		for tag in ("task", "userTask", "scriptTask", "serviceTask", "manualTask", "businessRuleTask")
	)


def _ir_node_types():
	return frozenset(
		{
			"startEvent",
			"endEvent",
			"intermediateThrowEvent",
			"intermediateCatchEvent",
			"task",
			"userTask",
			"scriptTask",
			"serviceTask",
			"manualTask",
			"businessRuleTask",
			"exclusiveGateway",
			"parallelGateway",
			"inclusiveGateway",
			"subProcess",
			"callActivity",
		}
	)


def _add_subprocess():
	import re

	return re.compile(
		r"^\s*(?:please\s+)?add\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?[\"']?(?P<name>[^\"',.;:\n]+?)[\"']?\s+sub[\s-]?process"
		r"(?:\s+(?:after|following)\s+(?:the\s+)?[\"']?(?P<after>[^\"'.;:\n]+?)[\"']?)?\s*[.!]?\s*$",
		re.I,
	)


def _add_workflow_state():
	import re

	return re.compile(
		r"^\s*(?:please\s+)?add\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:workflow\s+state\s+[\"']?(?P<state>[^\"',.;:\n]+?)[\"']?"
		r"|[\"']?(?P<state2>[^\"',.;:\n]+?)[\"']?\s+workflow\s+state)"
		r"(?:\s+(?:after|following)\s+(?:the\s+)?[\"']?(?P<after>[^\"'.;:\n]+?)[\"']?)?\s*[.!]?\s*$",
		re.I,
	)


def _gateway_kinds():
	return {
		"parallel": "parallelGateway",
		"exclusive": "exclusiveGateway",
		"inclusive": "inclusiveGateway",
	}


def _switch_all_gateways():
	import re

	return re.compile(
		r"\b(?:make|change|switch|convert|turn|replace)\b\s+(?:every|all|each)\s+(?:of\s+the\s+|the\s+)?"
		r"(?P<old>parallel|exclusive|inclusive)\s+gateways?\s+(?:(?:to|into|with)\s+(?:an?\s+)?)?"
		r"(?P<new>parallel|exclusive|inclusive)\b",
		re.I,
	)


def _switch_named_gateway():
	import re

	return re.compile(
		r"\b(?:make|change|switch|convert|turn)\b\s+(?:the\s+)?(?:gateway\s+)?[\"']?(?P<name>[^\"'.;:\n]+?)[\"']?\s+"
		r"(?:gateway\s+)?(?:to|into)\s+(?:an?\s+)?(?P<new>parallel|exclusive|inclusive)(?:\s+gateway)?\b",
		re.I,
	)


def _reroute():
	import re

	return re.compile(
		r"\b(?:reroute|redirect|move|point|change|connect)\b\s+(?:the\s+)?(?:arrow|flow|line|connection)?\s*from\s+[\"']?(?P<source>[^\"'\n]+?)[\"']?\s+"
		r"to\s+[\"']?(?P<old>[^\"'\n]+?)[\"']?\s+(?:so\s+(?:that\s+)?it\s+goes\s+|to\s+go\s+|and\s+point\s+it\s+|instead\s+)?to\s+[\"']?(?P<new>[^\"'.;\n]+?)[\"']?\s*[.!]?\s*$",
		re.I,
	)


def _reroute_instead():
	import re

	return re.compile(
		r"\b(?:reroute|redirect|move|point|change|connect)\b\s+(?:the\s+)?(?:arrow|flow|line|connection)?\s*from\s+[\"']?(?P<source>[^\"'\n]+?)[\"']?\s+"
		r"to\s+[\"']?(?P<new>[^\"'\n]+?)[\"']?\s+instead\s+of\s+[\"']?(?P<old>[^\"'.;\n]+?)[\"']?\s*[.!]?\s*$",
		re.I,
	)


def _layout_asks():
	import re

	return (
		(
			"spacing",
			re.compile(
				r"\b(?:spac(?:e|ed|ing)|spread|cramped|crowded|squashed|too close|apart|gaps?)\b", re.I
			),
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


def _ir_skipped_tags():
	return frozenset({"laneSet", "extensionElements", "incoming", "outgoing", "documentation"})


def _di_element():
	import re

	return re.compile(
		r'(?P<open><(?P<tag>bpmndi:BPMN(?:Shape|Edge))\b[^>]*?\bbpmnElement="(?P<id>[^"]+)"[^>]*>)(?P<body>.*?)(?P<close></(?P=tag)>)',
		re.S,
	)


def _waypoint():
	import re

	return re.compile(r'<di:waypoint\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s*/>')


def _bounds():
	import re

	return re.compile(
		r'<dc:Bounds\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s+width="(-?[\d.]+)"\s+height="(-?[\d.]+)"'
	)


def _label():
	import re

	return re.compile(r"<bpmndi:BPMNLabel\b.*?</bpmndi:BPMNLabel>", re.S)


def _compiled_pool():
	return "Participant_1"


def _lane_move_verbs():
	return r"\b(?:move|put|bring|shift|place|drag|relocate)\b"


def _lane_move_lead():
	import re

	return re.compile(_lane_move_verbs() + r"|\b(?:back|the|and|both|steps?|tasks?|please)\b", re.I)


def _lane_move_tail():
	import re

	return re.compile(r"\b(?:lane|swimlane|swim|please)\b", re.I)


def _node_tags():
	return tuple(
		"{" + _ns()["bpmn"] + "}" + tag
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


def _insert_gap():
	return 50


def _subprocess_size():
	return (100, 80)


def _libraries_gap():
	return 60


def _service_task_keys():
	return {
		"apply_workflow": ("serviceTargetDoctype", "workflowState", "docStatus", "onlyAllowEdit"),
		"send_email": (
			"emailAccount",
			"emailUseDoctype",
			"emailDoctype",
			"emailSubject",
			"emailTo",
			"emailToDocFields",
			"emailToTableField",
			"emailToTableUserField",
			"emailToRoles",
			"emailCc",
			"emailBcc",
			"emailBody",
			"emailLayout",
			"emailSubjectAr",
			"emailHeadingEn",
			"emailHeadingAr",
			"emailMessageEn",
			"emailMessageAr",
			"emailShowStatus",
			"emailFacts",
			"emailDetails",
			"emailAttachments",
			"emailArabicEdited",
		),
		"update_field": ("updateFieldDoctype", "updateFieldRows"),
		"google_chat": (
			"gchatType",
			"gchatRecipientBasis",
			"gchatEmail",
			"gchatDoctype",
			"gchatDocField",
			"gchatTableField",
			"gchatTableUserField",
			"gchatSpaceId",
			"gchatMessage",
		),
		"push_notification": (
			"pushDoctype",
			"pushTitle",
			"pushToUsers",
			"pushToDocFields",
			"pushToRoles",
			"pushMessage",
			"pushToTableField",
			"pushToTableUserField",
			"pushLinkToDocument",
			"pushFallbackInApp",
		),
		# Connector parameters are manifest-driven, so the params blob is passed
		# through as given rather than checked key by key here.
		"connector": ("connectorId", "connectorParams"),
	}


def _user_task_keys():
	return (
		"targetDoctype",
		"assigneeMode",
		"assigneeUser",
		"assigneeUsers",
		"assigneeDocfield",
		"assigneeTableField",
		"assigneeTableUserField",
		"taskActions",
		"notifyAssignee",
		"notifyAssigneeAccount",
		"notifyAssigneeSubject",
		"notifyAssigneeBody",
		"notifyAssigneeTemplate",
		"notifyLayout",
		"notifySubjectAr",
		"notifyQuestionEn",
		"notifyQuestionAr",
		"notifyFacts",
		"notifyDetails",
		"notifyAttachments",
		"notifyActions",
		"notifyConversation",
		"notifyTokenHours",
		"notifyArabicEdited",
	)


def _start_event_keys():
	return ("triggerDoctype", "triggerType")


def _trigger_types():
	return ("After Insert",)


def _date_fieldtypes():
	return ("Date", "Datetime", "Time")


def _number_fieldtypes():
	return ("Int", "Float", "Currency", "Percent", "Check")


def _template_names():
	return ("doc", "instance", "frappe")


def _assignee_modes():
	return ("User", "DocField", "Round Robin", "Load Balancing", "Table Field")


def _mode_requires():
	return {
		"User": "assigneeUser",
		"DocField": "assigneeDocfield",
		"Table Field": "assigneeTableField",
	}


def _misnamed():
	return {
		"doctype": "serviceTargetDoctype (Service Task) or targetDoctype (User Task)",
		"docType": "serviceTargetDoctype (Service Task) or targetDoctype (User Task)",
		"documentStatus": "docStatus",
		"nextWorkflowState": "workflowState",
		"state": "workflowState",
		"assignmentMode": "assigneeMode",
		"actions": "taskActions",
		"assignee": "assigneeUser",
	}


def _bool_keys():
	return frozenset({"emailUseDoctype", "notifyAssignee"})


def _js_words():
	return {"true": "True", "false": "False", "null": "None"}


def _quoted():
	import re

	return re.compile(r"(\"[^\"]*\"|'[^']*')")


def _action_cutoff():
	return 0.8


def _none_task_sources():
	return frozenset({"userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask"})


def quoted(name: str) -> str:
	return '"' + name + '"'


def register_namespaces() -> None:
	from xml.etree import ElementTree as ET

	for prefix, uri in _ns().items():
		ET.register_namespace(prefix, uri)


def add_subprocess_output(xml: str, text: str) -> dict | None:
	"""The reply to "add a <name> sub-process [after <step>]": a new collapsed sub-process in the flow, or None."""
	from xml.etree import ElementTree as ET

	match = _add_subprocess().match(text or "")
	if not match:
		return None
	name = match["name"].strip()
	# Naming a step that exists asks to turn that step into a sub-process, which another route does.
	if named_node(ET.fromstring(xml), name) is not None:
		return None
	bpmn = "{" + _ns()["bpmn"] + "}"
	sub = ET.Element(bpmn + "subProcess", {"name": name})
	start = ET.SubElement(sub, bpmn + "startEvent", {"id": "", "name": frappe._("Start")})
	end = ET.SubElement(sub, bpmn + "endEvent", {"id": "", "name": frappe._("End")})
	inner = ET.SubElement(sub, bpmn + "sequenceFlow", {"id": "", "sourceRef": "", "targetRef": ""})
	added = insert_after(xml, match["after"], sub, (start, end, inner))
	if not added:
		return None
	return _inserted_reply(
		added, "ADD_SUBPROCESS", frappe._("I added the sub-process {0} after {1}. Open it to draw its steps.")
	)


def add_workflow_state_output(xml: str, text: str) -> dict | None:
	"""The reply to "add the workflow state <state> [after <step>]": an Apply Workflow step in the flow, or None."""
	from xml.etree import ElementTree as ET

	match = _add_workflow_state().match(text or "")
	if not match:
		return None
	state = (match["state"] or match["state2"]).strip()
	bpmn, spiff = "{" + _ns()["bpmn"] + "}", "{" + _ns()["spiffworkflow"] + "}"
	task = ET.Element(
		bpmn + "serviceTask",
		{
			"name": frappe._("Set Workflow State {0}").format(state),
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
		frappe._("I added the step {0} after {1}. Pick the role allowed to edit in that state on the step."),
	)


def _inserted_reply(added: dict, action: str, message: str) -> dict:
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": action,
		"bpmn_xml": added["xml"],
		"response": message.format(quoted(added["name"]), quoted(added["after"]))
		+ " "
		+ frappe._("Every other step, arrow and setting is kept. Review it on the canvas."),
		"options": [],
	}


def switch_gateways_output(xml: str, text: str) -> dict | None:
	"""The reply to "make every parallel gateway exclusive" or "change <gateway> to exclusive", or None."""
	from xml.etree import ElementTree as ET

	every = _switch_all_gateways().search(text or "")
	named = None if every else _switch_named_gateway().search(text or "")
	if not (every or named):
		return None
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + _ns()["bpmn"] + "}"
	if every:
		old, new = every["old"].lower(), every["new"].lower()
		gateways = list(root.iter(bpmn + _gateway_kinds()[old]))
	else:
		gateway = named_node(root, named["name"])
		if gateway is None or not gateway.tag.endswith("Gateway"):
			return None
		new = named["new"].lower()
		gateways = [gateway]
	gateways = [g for g in gateways if g.tag != bpmn + _gateway_kinds()[new]]
	if not gateways:
		return {
			"intent": "CLARIFY",
			"response": frappe._("Every gateway you named is already {0}, so I changed nothing.").format(new),
		}
	to_ask = []
	for gateway in gateways:
		to_ask += _switch_gateway(root, gateway, bpmn + _gateway_kinds()[new])
	reply = frappe._("I made {0} gateway(s) {1}. Every step and arrow is kept.").format(len(gateways), new)
	if to_ask:
		reply += " " + frappe._(
			"An exclusive gateway takes one path, so I made the first path of each the default. "
			"Tell me when each of these other paths should be taken: {0}."
		).format(", ".join(to_ask))
	return _edited_reply(root, "SWITCH_GATEWAYS", reply + " " + frappe._("Review it on the canvas."))


def _switch_gateway(root: "ET.Element", gateway: "ET.Element", new_tag: str) -> list[str]:
	"""Change gateway to new_tag in place; the paths that now need a condition from the person, by name."""
	from xml.etree import ElementTree as ET

	bpmn = "{" + _ns()["bpmn"] + "}"
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
		quoted(f.get("name") or frappe._("to {0}").format(names.get(f.get("targetRef"), f.get("targetRef"))))
		for f in unconditioned
		if f.get("id") != gateway.get("default")
	]


def reroute_arrow_output(xml: str, text: str) -> dict | None:
	"""The reply to "reroute the arrow from A to B so it goes to C", or None."""
	from xml.etree import ElementTree as ET

	match = _reroute_instead().search(text or "") or _reroute().search(text or "")
	if not match:
		return None
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + _ns()["bpmn"] + "}"
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
		frappe._(
			"The arrow from {0} now goes to {1} instead of {2}. Everything else is kept. Review it on the canvas."
		).format(quoted(source.get("name")), quoted(new.get("name")), quoted(old.get("name"))),
	)


def _redraw_edge(root: "ET.Element", flow_id: str, source_id: str, target_id: str) -> None:
	"""Draw the arrow flow_id straight from the right of source_id to the left of target_id."""
	from xml.etree import ElementTree as ET

	dc, di, bpmndi = "{" + _ns()["dc"] + "}", "{" + _ns()["di"] + "}", "{" + _ns()["bpmndi"] + "}"
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


def _node_names(root: "ET.Element") -> dict:
	from xml.etree import ElementTree as ET

	return {e.get("id"): e.get("name") or e.get("id") for e in root.iter() if e.tag in _node_tags()}


def _edited_reply(root: "ET.Element", action: str, response: str) -> dict:
	import re
	from xml.etree import ElementTree as ET

	edited = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": action,
		"bpmn_xml": re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', edited),
		"response": response,
		"options": [],
	}


def _pipeline_path() -> str:
	"""Absolute path to frontend/tools/bpmn-pipeline/pipeline.mjs, resolved from the processa app path.

	This module lives at ``processa/processa/ai_agent_registry/definitions/prosally/tools_pipeline.py``;
	the pipeline lives at ``processa/frontend/tools/bpmn-pipeline/pipeline.mjs`` (under the app root's
	frontend dir), four directories up from ``prosally/``.
	"""
	import os

	return os.path.normpath(
		os.path.join(
			frappe.get_app_path("processa"),
			"..",
			"frontend",
			"tools",
			"bpmn-pipeline",
			"pipeline.mjs",
		)
	)


def _flow_pairs(flows) -> list[tuple[str, str]]:
	"""IR flow dicts or (from, to) tuples, minus self-loops and blanks."""
	pairs = []
	for f in flows or []:
		a, b = (f.get("from"), f.get("to")) if isinstance(f, dict) else (f[0], f[1])
		if a and b and a != b:
			pairs.append((str(a), str(b)))
	return pairs


def flow_pairs_from_xml(xml: str) -> list[tuple[str, str]]:
	"""The (sourceRef, targetRef) of every sequence flow in a BPMN XML string."""
	import re

	pairs = []
	for m in re.finditer(r"<bpmn2?:sequenceFlow\b([^>]*)>", xml or ""):
		s = re.search(r'sourceRef="([^"]+)"', m.group(1))
		t = re.search(r'targetRef="([^"]+)"', m.group(1))
		if s and t:
			pairs.append((s.group(1), t.group(1)))
	return pairs


def check_topology(flows) -> dict:
	"""Can the flow graph be drawn with no crossing lines at all?

	A non-planar graph forces a crossing in every layout, so ``planar`` fixes the
	crossing count the layout audit holds the drawing to. ``obstruction`` names
	the nodes of the Kuratowski subgraph \u2014 the part that cannot be flattened.
	"""
	pairs = _flow_pairs(flows)
	if not pairs:
		return {"planar": True, "obstruction": [], "min_crossings": 0}
	try:
		import networkx as nx
	except ImportError:  # pragma: no cover \u2014 networkx ships with the bench env
		return {"planar": None, "obstruction": [], "min_crossings": 0}
	graph = nx.Graph()
	graph.add_edges_from(pairs)
	planar, cert = nx.check_planarity(graph, counterexample=True)
	obstruction = [] if planar else sorted(cert.nodes())
	return {"planar": bool(planar), "obstruction": obstruction, "min_crossings": 0 if planar else 1}


def _topology_problem(topo: dict, names: dict) -> dict:
	who = ", ".join(names.get(n, n) for n in topo.get("obstruction", [])[:6])
	return {
		"kind": "topology",
		"rule": "non-planar",
		"elementId": "",
		"nodes": topo.get("obstruction", []),
		"message": (
			"This process cannot be drawn without a crossing line: the paths through "
			f"{who} cannot all be laid flat. One crossing is the minimum."
		),
	}


def compile_ir(ir: dict) -> dict:
	"""Compile an IR dict into BPMN XML via ``frontend/tools/bpmn-pipeline/pipeline.mjs``.

	Runs the Node pipeline (normalise → compile → layout → audit) in a
	subprocess and returns its JSON result:

	    {"ok": bool, "xml": str, "problems": list, "normalizedIR": dict?,
	     "layout": dict?, "topology": dict}

	``topology`` is computed here, before the subprocess, so it is present even
	when the pipeline fails. A non-planar graph adds a ``topology`` problem
	without turning ``ok`` off: the XML compiles, and the crossing is a fact
	about the process rather than a failure. A drawing with more crossings than
	the graph requires adds a ``layout`` problem \u2014 the compiler's defect, never
	the IR's.

	Never raises \u2014 a missing node binary, empty output, timeout, or any other
	failure is returned as ``{"ok": False, "xml": "", "problems": [...]}`` so a
	tool-calling loop stays alive.
	"""
	import json
	import subprocess

	try:
		topo = check_topology((ir or {}).get("flows"))
	except Exception:
		topo = {"planar": None, "obstruction": [], "min_crossings": 0}

	def fail(message):
		return {"ok": False, "xml": "", "topology": topo, "problems": [{"kind": "fatal", "message": message}]}

	# Task configuration is resolved before the subprocess: the compiler writes
	# the attributes verbatim, so what counts as a real setting is decided in
	# Python where it can be checked against this site's own workflows.
	try:
		import frappe

		use_none_tasks(ir)
		config_problems = resolve_ir_config(ir)
		config_problems += resolve_ir_lane_roles(
			ir, frappe.get_all("Role", filters={"disabled": 0}, pluck="name")
		)
	except Exception:
		config_problems = []

	try:
		resolve_ir_conditions(ir)
	except ValueError as exc:
		return fail(f"gateway conditions: {exc}")

	node = find_node()
	if not node:
		return fail("node not found in PATH")
	try:
		result = subprocess.run(
			[node, _pipeline_path()],
			input=json.dumps(ir),
			capture_output=True,
			text=True,
			timeout=30,
		)
		stdout = result.stdout.strip()
		if not stdout:
			return fail(result.stderr.strip() or "pipeline produced no output")
		out = json.loads(stdout)
	except subprocess.TimeoutExpired:
		return fail("pipeline timed out after 30 s")
	except Exception as exc:
		return fail(str(exc))

	out["topology"] = topo
	out.setdefault("problems", [])
	out["problems"].extend(config_problems)
	if topo.get("planar") is False:
		names = {
			n.get("id"): n.get("name") or n.get("id") for n in (ir or {}).get("nodes") or [] if n.get("id")
		}
		out["problems"].append(_topology_problem(topo, names))
	crossings = (out.get("layout") or {}).get("crossings", 0)
	if out.get("ok") and crossings > topo.get("min_crossings", 0):
		out["problems"].append(
			{
				"kind": "layout",
				"rule": "edge-crossing",
				"elementId": "",
				"message": (
					f"Drawing has {crossings} crossing(s); the flow graph needs {topo.get('min_crossings', 0)}. "
					"Layout defect, not an IR change."
				),
			}
		)
	return out


def audit_layout(xml: str) -> dict:
	"""How the drawing of xml measures: crossings, lines through shapes, lines on top of each other, label clashes."""
	import json
	import subprocess

	result = subprocess.run(
		[find_node(), _pipeline_path()],
		input=json.dumps({"audit": xml}),
		capture_output=True,
		text=True,
		timeout=30,
		check=True,
	)
	return json.loads(result.stdout)


def has_lanes(xml: str) -> bool:
	"""True when the diagram XML contains a laneSet."""
	return bool(xml) and ("laneSet" in xml or "bpmn:laneSet" in xml)


def layout_note(old_xml: str, new_xml: str, text: str) -> str:
	"""What a change did for the layout asks in text, measured on both drawings; "" when text makes none."""
	asks = layout_asks(text)
	return layout_change_summary(audit_layout(old_xml), audit_layout(new_xml), asks) if asks else ""


def layout_change_summary(before: dict, after: dict, asks: list[str]) -> str:
	"""The measured change for each layout ask, each sentence led by a space."""
	said = ""
	if "crossings" in asks or before["crossings"] != after["crossings"]:
		said += " " + frappe._("Crossing lines: {0} before, {1} now.").format(
			before["crossings"], after["crossings"]
		)
	if before["throughShape"] != after["throughShape"]:
		said += " " + frappe._("Lines through a shape: {0} before, {1} now.").format(
			before["throughShape"], after["throughShape"]
		)
	if before["overlaps"] != after["overlaps"]:
		said += " " + frappe._("Lines on top of each other: {0} before, {1} now.").format(
			before["overlaps"], after["overlaps"]
		)
	if "spacing" in asks:
		said += " " + frappe._("The gaps between columns and lanes are sized to the lines they carry.")
	if "alignment" in asks:
		said += " " + frappe._("Every step sits on the layout grid of columns and lanes.")
	if "convergence" in asks:
		said += " " + frappe._("Lines that join meet at one point before the step they lead to.")
	return said


def layout_limits(xml: str, audit: dict, asks: list[str]) -> str:
	"""Why a layout that came out the same cannot meet each ask, each sentence led by a space."""
	from xml.etree import ElementTree as ET

	said = ""
	if audit["crossings"]:
		topology = check_topology(flow_pairs_from_xml(xml))
		if topology["planar"] is False:
			names = {
				e.get("id"): e.get("name") or e.get("id") for e in ET.fromstring(xml).iter() if e.get("id")
			}
			who = ", ".join(quoted(names.get(n, n)) for n in topology["obstruction"][:5])
			said += " " + frappe._(
				"{0} crossing line(s) stay because the paths through {1} cannot all be laid flat."
			).format(audit["crossings"], who)
		else:
			said += " " + frappe._("I could not draw it with fewer than {0} crossing line(s).").format(
				audit["crossings"]
			)
	elif "crossings" in asks:
		said += " " + frappe._("No lines cross.")
	if "spacing" in asks:
		said += " " + frappe._(
			"I cannot set a gap of my own: the gaps are sized to the lines each column and lane carries."
		)
	if "alignment" in asks:
		said += " " + frappe._("Every step already sits on the layout grid.")
	if "convergence" in asks:
		said += " " + frappe._("Lines that join already meet where they join.")
	return said


def layout_asks(text: str) -> list[str]:
	"""Which layout asks text makes: spacing, alignment, crossings, convergence."""
	return [ask for ask, pattern in _layout_asks() if pattern.search(text)]


def layout_is_automatic() -> str:
	"""What a person can do about the layout, since no single arrow, label or colour is placed by hand."""
	return frappe._(
		"Layout is computed automatically, so I cannot place one arrow, label or colour by hand. "
		"You can drag shapes on the canvas, or change the flow structure and I will lay it out again."
	)


def xml_to_ir(xml: str) -> dict | None:
	"""The IR that draws xml again, or None when xml has an element the IR cannot hold."""
	from xml.etree import ElementTree as ET

	bpmn = "{" + _ns()["bpmn"] + "}"
	process = next(iter(ET.fromstring(xml).iter(bpmn + "process")), None)
	if process is None:
		return None
	lane_of = {}
	lanes = []
	for lane in process.iter(bpmn + "lane"):
		lanes.append({"id": lane.get("id"), "name": lane.get("name") or lane.get("id")})
		for ref in lane.findall(bpmn + "flowNodeRef"):
			lane_of[(ref.text or "").strip()] = lane.get("id")

	def scope(parent):
		nodes, flows = [], []
		for elem in parent:
			tag = elem.tag.removeprefix(bpmn)
			if tag in _ir_node_types():
				node = {"id": elem.get("id"), "name": elem.get("name") or "", "type": tag}
				if elem.get("id") in lane_of:
					node["lane"] = lane_of[elem.get("id")]
				if elem.get("calledElement"):
					node["calledElement"] = elem.get("calledElement")
				if tag == "subProcess":
					inner = scope(elem)
					if inner is None:
						return None
					node["children"] = inner
				nodes.append(node)
			elif tag == "sequenceFlow":
				flow = {"id": elem.get("id"), "from": elem.get("sourceRef"), "to": elem.get("targetRef")}
				if elem.get("name"):
					flow["name"] = elem.get("name")
				body = elem.find(bpmn + "conditionExpression")
				if body is not None and body.text:
					flow["condition"] = body.text
				if parent.get("default") == elem.get("id"):
					flow["default"] = True
				flows.append(flow)
			elif tag not in _ir_skipped_tags():
				return None
		return {"nodes": nodes, "flows": flows}

	body = scope(process)
	if body is None:
		return None
	kind = {} if process.get("isExecutable", "false").strip().lower() == "true" else {"executable": False}
	return {"name": process.get("name") or "", "lanes": lanes, **kind, **body}


def relayout(xml: str) -> tuple[str | None, str]:
	"""(xml with every shape and line moved to a fresh layout, "") or (None, why not); only coordinates change."""
	xml, libraries = take_out_libraries(xml)
	ir = xml_to_ir(xml)
	if ir is None:
		return None, "unsupported"
	compiled = compile_ir(ir)
	if not compiled.get("ok") or not compiled.get("xml"):
		return None, "failed"
	moved = move_drawing(xml, compiled)
	if moved is None:
		return None, "unplaced"
	if _coordinates(moved) == _coordinates(xml):
		return None, "same"
	return put_back_libraries(moved, libraries), ""


def move_drawing(xml: str, compiled: dict) -> str | None:
	"""xml with each shape and line placed where the compiled drawing has it and every other byte kept, or None."""
	import re

	if any(f'xmlns:{prefix}="{_ns()[prefix]}"' not in xml for prefix in ("bpmndi", "dc", "di")):
		return None
	drawn = {m["id"]: m["body"] for m in _di_element().finditer(compiled["xml"])}
	flows = {
		_attribute(m[1], "id"): (_attribute(m[1], "sourceRef"), _attribute(m[1], "targetRef"))
		for m in re.finditer(r"<bpmn:sequenceFlow\b([^>]*)>", compiled["xml"])
	}
	inferred = {n["id"] for n in compiled["normalizedIR"]["nodes"] if n.get("inferred")}
	pools = set(re.findall(r'<bpmn:participant\b[^>]*?\bid="([^"]+)"', xml))
	unplaced = []

	def place(m):
		key = _compiled_pool() if m["id"] in pools else m["id"]
		body = drawn.get(key)
		through_added_gateway = bool(set(flows.get(key, ())) & inferred)
		if body is not None and through_added_gateway:
			points = _route(key, flows, drawn, inferred)
			label = _label().search(body)
			body = (
				None
				if points is None
				else "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in points)
				+ (label[0] if label else "")
			)
		if body is None:
			unplaced.append(m["id"])
			return m[0]
		return m["open"] + body + m["close"]

	moved = _di_element().sub(place, xml)
	every = len(re.findall(r"<\w*:?BPMN(?:Shape|Edge)\b", xml))
	if unplaced or every != len(_di_element().findall(xml)):
		return None
	return moved


def _route(flow_id: str, flows: dict, drawn: dict, inferred: set) -> list | None:
	"""The points of a flow, run through any gateway the compiler added, which meet at that gateway's centre."""
	source, target = flows[flow_id]
	points = _waypoint().findall(drawn[flow_id])
	while source in inferred:
		into = [f for f, ends in flows.items() if ends[1] == source]
		if len(into) != 1 or into[0] not in drawn:
			return None
		points = [*_waypoint().findall(drawn[into[0]])[:-1], _centre(drawn[source]), *points[1:]]
		source = flows[into[0]][0]
	while target in inferred:
		out = [f for f, ends in flows.items() if ends[0] == target]
		if len(out) != 1 or out[0] not in drawn:
			return None
		points = [*points[:-1], _centre(drawn[target]), *_waypoint().findall(drawn[out[0]])[1:]]
		target = flows[out[0]][1]
	return points


def _coordinates(xml: str) -> list[float]:
	import re

	return [
		float(v)
		for v in re.findall(r'\b(?:x|y|width|height)="(-?[\d.]+)"', xml[xml.find("<bpmndi:BPMNDiagram") :])
	]


def _centre(body: str) -> tuple[str, str]:
	x, y, width, height = (float(v) for v in _bounds().search(body).groups())
	return f"{x + width / 2:g}", f"{y + height / 2:g}"


def _attribute(attrs: str, name: str) -> str:
	import re

	return re.search(r"\b" + name + r'="([^"]*)"', attrs)[1]


def relayout_output(xml: str, text: str = "") -> dict:
	"""The reply to a layout request: the diagram laid out again with only positions changed, or what was tried and why not."""
	asks = layout_asks(text)
	new_xml, reason = relayout(xml)
	if new_xml:
		before, after = audit_layout(xml), audit_layout(new_xml)
		if after["crossings"] > before["crossings"]:
			say = frappe._(
				"I drew the diagram again, but it came out with {0} crossing line(s) where yours has {1}, so I kept your layout."
			).format(after["crossings"], before["crossings"])
			return {"intent": "CLARIFY", "response": say + " " + layout_is_automatic()}
		return {
			"intent": "BPMN_MODIFIED",
			"action_intent": "RELAYOUT",
			"bpmn_xml": new_xml,
			"response": frappe._(
				"I laid the diagram out again and moved only shapes and lines. Every id, name, condition and timer is unchanged."
			)
			+ layout_change_summary(before, after, asks)
			+ " "
			+ frappe._("Review it on the canvas.")
			+ " "
			+ layout_is_automatic(),
			"options": [],
		}
	if reason == "same":
		say = frappe._(
			"I drew the diagram again and every shape and line came out where it already is, so I changed nothing."
		)
		say += layout_limits(xml, audit_layout(xml), asks)
	elif reason == "unsupported":
		kinds = unsupported_kinds(xml)
		say = frappe._(
			"This diagram has {0}, which the layout cannot place, so I changed nothing to keep them safe."
		).format(", ".join(kinds) if kinds else frappe._("elements"))
	elif reason == "unplaced":
		say = frappe._(
			"Some shapes or lines, such as notes, message lines or a second pool, have no place in the new layout, so I changed nothing."
		)
	else:
		say = frappe._(
			"I could not lay the diagram out again without risking your steps, so I changed nothing."
		)
	return {"intent": "CLARIFY", "response": say + " " + layout_is_automatic()}


def unsupported_kinds(xml: str) -> list[str]:
	"""The kinds of element in xml that the layout cannot place, in plain words."""
	import re
	from xml.etree import ElementTree as ET

	bpmn = "{" + _ns()["bpmn"] + "}"
	allowed = _ir_node_types() | _ir_skipped_tags() | {"sequenceFlow"}
	kinds = set()
	for scope in ET.fromstring(xml).iter():
		if scope.tag in (bpmn + "process", bpmn + "subProcess"):
			kinds |= {e.tag.rsplit("}", 1)[-1] for e in scope} - allowed
	return sorted(re.sub(r"(?<!^)(?=[A-Z])", " ", kind).lower() for kind in kinds)


def diagram_edit_output(xml: str, text: str) -> dict | None:
	"""The reply to a message that only asks for one edit ProsAlly makes in code, or None to leave it to the model."""
	if not (xml or "").strip():
		return None
	for operation in (
		move_to_lane_output,
		add_subprocess_output,
		add_workflow_state_output,
		switch_gateways_output,
		reroute_arrow_output,
	):
		reply = operation(xml, text)
		if reply:
			return reply
	return None


def move_to_lane_output(xml: str, text: str) -> dict | None:
	"""The reply to "move this step to that lane": the step moved and the diagram laid out again, no redraw by a model."""
	import re
	from xml.etree import ElementTree as ET

	move = lane_move(xml, text)
	if not move:
		return None
	register_namespaces()
	bpmn = "{" + _ns()["bpmn"] + "}"
	root = ET.fromstring(xml)
	moving = {step["id"] for step in move["steps"]}
	for lane in root.iter(bpmn + "lane"):
		for ref in [r for r in lane.findall(bpmn + "flowNodeRef") if (r.text or "").strip() in moving]:
			lane.remove(ref)
		if lane.get("id") == move["lane"]["id"]:
			for step in move["steps"]:
				ET.SubElement(lane, bpmn + "flowNodeRef").text = step["id"]
	moved = ET.tostring(root, encoding="unicode", xml_declaration=True)
	new_xml, _reason = relayout(re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', moved))
	if not new_xml:
		return None
	return {
		"intent": "BPMN_MODIFIED",
		"action_intent": "MOVE_TO_LANE",
		"bpmn_xml": new_xml,
		"response": frappe._(
			"I moved {0} to the lane {1}. Every step, arrow and setting is kept. Review it on the canvas."
		).format(", ".join(quoted(step["name"]) for step in move["steps"]), quoted(move["lane"]["name"])),
		"options": [],
	}


def lane_move(xml: str, text: str) -> dict | None:
	"""The steps and the lane of a message that only asks to move steps on the diagram into one of its lanes."""
	import re
	from xml.etree import ElementTree as ET

	if not has_lanes(xml) or not re.search(_lane_move_verbs(), text, re.I):
		return None
	bpmn = "{" + _ns()["bpmn"] + "}"
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
	named = [
		(_name_pattern(e.get("name") or ""), e)
		for p in root.iter(bpmn + "process")
		for e in p
		if e.tag in _step_tags()
	]
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
	rest = _lane_move_lead().sub(" ", asked) + " " + _lane_move_tail().sub(" ", text[where.end() :])
	if not steps or re.search(r"\w", rest):
		return None
	return {"steps": steps, "lane": {"id": lane.get("id"), "name": lane.get("name")}}


def _name_pattern(name: str) -> str:
	"""A pattern for name as a person types it, whole words only; empty when name has no letter or digit."""
	import re

	words = [re.escape(word) for word in re.split(r"[\W_]+", name) if word]
	return r"\b" + r"[\s\-]*".join(words) + r"\b" if words else ""


def add_flow_references(scope: "ET.Element") -> None:
	"""Give each step of scope the incoming and outgoing flow references the editor and its linter read."""
	from xml.etree import ElementTree as ET

	bpmn = "{" + _ns()["bpmn"] + "}"
	steps = {e.get("id"): e for e in scope if e.get("id") and e.tag != bpmn + "sequenceFlow"}
	for flow in scope.findall(bpmn + "sequenceFlow"):
		for ref, tag in ((flow.get("sourceRef"), "outgoing"), (flow.get("targetRef"), "incoming")):
			step = steps.get(ref)
			if step is not None and flow.get("id") not in [c.text for c in step.findall(bpmn + tag)]:
				ET.SubElement(step, bpmn + tag).text = flow.get("id")


def take_out_libraries(xml: str) -> tuple[str, list]:
	"""(xml without its Libraries boxes, the boxes with their drawing), so a change to the flow never touches them."""
	from xml.etree import ElementTree as ET

	if 'scriptLibrary="true"' not in (xml or ""):
		return xml, []
	register_namespaces()
	try:
		root = ET.fromstring(xml)
	except ET.ParseError:
		return xml, []
	bpmn, bpmndi = "{" + _ns()["bpmn"] + "}", "{" + _ns()["bpmndi"] + "}"
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
	from xml.etree import ElementTree as ET

	if not libraries or not xml:
		return xml
	register_namespaces()
	root = ET.fromstring(xml)
	bpmn, bpmndi, dc = "{" + _ns()["bpmn"] + "}", "{" + _ns()["bpmndi"] + "}", "{" + _ns()["dc"] + "}"
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
		dy = bottom + _libraries_gap() - float(box_bounds.get("y"))
		for shape in shapes:
			_shift(shape, dx, dy, lambda px, py: (px, py))
			plane.append(shape)
	return _serialize(root)


def is_libraries_box(element: "ET.Element") -> bool:
	from xml.etree import ElementTree as ET

	return (
		element.tag == "{" + _ns()["bpmn"] + "}adHocSubProcess"
		and element.get("{" + _ns()["spiffworkflow"] + "}scriptLibrary") == "true"
	)


def _serialize(root: "ET.Element") -> str:
	import re
	from xml.etree import ElementTree as ET

	text = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', text)


def _squash(text: str) -> str:
	import re

	return re.sub(r"[^a-z0-9]", "", text.lower())


def _make_room(plane: "ET.Element", step_shape: "ET.Element", edges: tuple, dw: float, dh: float) -> None:
	"""Move what is right of the step by dw and what is below it by dh; widen and heighten the lanes and pool."""
	from xml.etree import ElementTree as ET

	dc, bpmndi = "{" + _ns()["dc"] + "}", "{" + _ns()["bpmndi"] + "}"
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


def _shift(drawn: "ET.Element", dx: float, dy: float, rule) -> None:
	"""Move a shape, with its label, or an edge point by point: each point moves as rule says, then by dx and dy."""
	from xml.etree import ElementTree as ET

	dc, di = "{" + _ns()["dc"] + "}", "{" + _ns()["di"] + "}"
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


def _offset(point: "ET.Element", rule) -> tuple:
	from xml.etree import ElementTree as ET

	x, y = float(point.get("x")), float(point.get("y"))
	new_x, new_y = rule(x, y)
	return new_x - x, new_y - y


def coordinate_text(value: float) -> str:
	return str(int(value)) if value == int(value) else str(round(value, 2))


def insert_after(xml: str, after_name: str | None, element: "ET.Element", inner: tuple) -> dict | None:
	"""xml with element placed on the arrow that leaves the step named after_name, or the last step before the end.

	None when that step is not found, is not unique, or does not leave by exactly one arrow.
	"""
	import re
	from xml.etree import ElementTree as ET

	register_namespaces()
	root = ET.fromstring(xml)
	bpmn = "{" + _ns()["bpmn"] + "}"
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


def _anchor(root: "ET.Element", after_name: str | None) -> "ET.Element | None":
	"""The step named after_name, or the one step that leads into the end event."""
	from xml.etree import ElementTree as ET

	bpmn = "{" + _ns()["bpmn"] + "}"
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


def named_node(root: "ET.Element", name: str) -> "ET.Element | None":
	"""The one flow node whose name is name, ignoring case, spaces and punctuation."""
	from xml.etree import ElementTree as ET

	wanted = _squash(name)
	found = [
		e
		for e in root.iter()
		if e.get("name") and e.get("id") and _squash(e.get("name")) == wanted and e.tag in _node_tags()
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
	root: "ET.Element", anchor_id: str, new_id: str, old_flow_id: str, new_flow_id: str, target_id: str
) -> None:
	"""Draw the new step right of its anchor, push the rest right, and route both arrows straight."""
	from xml.etree import ElementTree as ET

	dc, di, bpmndi = "{" + _ns()["dc"] + "}", "{" + _ns()["di"] + "}", "{" + _ns()["bpmndi"] + "}"
	plane = next(
		(p for p in root.iter(bpmndi + "BPMNPlane") if any(s.get("bpmnElement") == anchor_id for s in p)),
		None,
	)
	if plane is None:
		return
	anchor_shape = next(s for s in plane.findall(bpmndi + "BPMNShape") if s.get("bpmnElement") == anchor_id)
	b = anchor_shape.find(dc + "Bounds")
	x, y, w, h = (float(b.get(k)) for k in ("x", "y", "width", "height"))
	width, height = _subprocess_size()
	_make_room(plane, anchor_shape, (x + w, y + h, y + h / 2), width + _insert_gap(), 0)
	new_x, new_y = x + w + _insert_gap(), y + h / 2 - height / 2
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


def _draw_collapsed_inside(root: "ET.Element", sub_id: str, start_id: str, end_id: str, flow_id: str) -> None:
	"""Give a collapsed sub-process its own drawing, holding its start, its end and the arrow between them."""
	from xml.etree import ElementTree as ET

	dc, di, bpmndi = "{" + _ns()["dc"] + "}", "{" + _ns()["di"] + "}", "{" + _ns()["bpmndi"] + "}"
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


def find_node() -> str | None:
	"""Return the path to a Node.js 18 or later binary, falling back to whatever is in PATH."""
	import os
	import shutil

	nvm_dir = os.path.join(os.path.expanduser("~"), ".nvm", "versions", "node")
	if os.path.isdir(nvm_dir):
		try:
			entries = os.listdir(nvm_dir)
		except OSError:
			entries = []
		versions: list[tuple[tuple[int, int, int], str]] = []
		for entry in entries:
			if not entry.startswith("v"):
				continue
			candidate = os.path.join(nvm_dir, entry, "bin", "node")
			if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
				continue
			try:
				parts = entry.lstrip("v").split(".")
				major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
			except (ValueError, IndexError):
				continue
			if major >= 18:
				versions.append(((major, minor, patch), candidate))
		if versions:
			versions.sort(key=lambda x: x[0], reverse=True)
			return versions[0][1]
	return shutil.which("node")


def _problem(element_id: str, message: str, rule: str = "task-config") -> dict:
	return {"kind": "config", "rule": rule, "elementId": element_id, "message": message}


def _as_attr_bool(value) -> str:
	if isinstance(value, str):
		return "true" if value.strip().lower() in ("1", "true", "yes") else "false"
	return "true" if value else "false"


def normalise_task_actions(value) -> str:
	"""The panel's JSON row format, from whatever shape the model produced.

	Accepts ``["Approve", "Reject"]`` and the full row form. Confirm-and-sign
	flags are stored as the strings the checkboxes read, so a generated action
	round-trips through the panel unchanged.
	"""
	import json

	if value in (None, "", []):
		return ""
	if isinstance(value, str):
		text = value.strip()
		if text.startswith("["):
			try:
				value = json.loads(text)
			except ValueError:
				# A plain comma-separated list is the panel's own legacy format.
				value = [p.strip() for p in text.split(",") if p.strip()]
		else:
			value = [p.strip() for p in text.split(",") if p.strip()]

	rows = []
	for entry in value or []:
		if isinstance(entry, str):
			action = entry.strip()
			if action:
				rows.append({"action": action})
			continue
		if not isinstance(entry, dict):
			continue
		action = str(entry.get("action") or "").strip()
		if not action:
			continue
		row = {"action": action}
		for flag in ("confirmTransition", "requireDigitalSignature"):
			if entry.get(flag) not in (None, "", False, "false"):
				row[flag] = "true"
		rows.append(row)
	# Compact separators so a generated value is byte-identical to one the
	# properties panel wrote.
	return json.dumps(rows, separators=(",", ":")) if rows else ""


def workflow_states(doctype: str) -> list[dict]:
	"""Active workflow states for a DocType: state, doc_status and editing role.

	Empty when the DocType has no active workflow, which is itself the answer to
	"can this be an Apply Workflow task".
	"""
	if not doctype:
		return []
	try:
		import frappe

		workflow = frappe.db.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
		if not workflow:
			return []
		return frappe.get_all(
			"Workflow Document State",
			filters={"parent": workflow},
			fields=["state", "doc_status", "allow_edit"],
			order_by="idx",
		)
	except Exception:
		# Config resolution must never take the compile down; an unresolved
		# state simply stays as the model wrote it.
		return []


def _resolve_apply_workflow(attrs: dict, element_id: str, problems: list) -> None:
	"""Fill docStatus and onlyAllowEdit from the Workflow record."""
	doctype = attrs.get("serviceTargetDoctype")
	state = attrs.get("workflowState")
	if not doctype:
		problems.append(_problem(element_id, "Apply Workflow needs serviceTargetDoctype."))
		return
	rows = workflow_states(doctype)
	if not rows:
		_check_state_without_workflow(doctype, state, element_id, problems)
		return
	if not state:
		problems.append(
			_problem(
				element_id,
				f"Apply Workflow needs workflowState. '{doctype}' allows: "
				+ ", ".join(r["state"] for r in rows),
			)
		)
		return
	match = next((r for r in rows if r["state"] == state), None)
	if not match:
		problems.append(
			_problem(
				element_id,
				f"'{state}' is not a workflow state of '{doctype}'. Use one of: "
				+ ", ".join(r["state"] for r in rows),
			)
		)
		return
	attrs["docStatus"] = str(match.get("doc_status") or "0")
	if match.get("allow_edit"):
		attrs["onlyAllowEdit"] = match["allow_edit"]


def _check_state_without_workflow(doctype: str, state: str, element_id: str, problems: list) -> None:
	"""Report a DocType with no active Workflow that cannot hold the state: no workflow_state field, or no such Workflow State."""
	import frappe
	from frappe import _

	if not frappe.db.exists("DocType", doctype):
		problems.append(
			_problem(
				element_id,
				frappe._("'{0}' is not a DocType on this site.").format(doctype),
				rule="apply-workflow-doctype",
			)
		)
	elif not frappe.get_meta(doctype).has_field("workflow_state"):
		problems.append(
			_problem(
				element_id,
				frappe._(
					"{0} has no active Workflow and no workflow_state field, so an Apply Workflow step on it cannot deploy. "
					"Add a workflow_state field to {0} first, or use an Update Field step."
				).format(doctype),
				rule="apply-workflow-doctype",
			)
		)
	elif state and not frappe.db.exists("Workflow State", state):
		problems.append(
			_problem(
				element_id,
				frappe._(
					"'{0}' is not a Workflow State, so the workflow_state field of {1} cannot hold it."
				).format(state, doctype),
				rule="apply-workflow-doctype",
			)
		)


def resolve_node_attrs(node: dict) -> tuple[dict, list[dict]]:
	"""The spiffworkflow attributes for one IR node, plus anything wrong with it."""
	import json

	problems: list[dict] = []
	config = node.get("config")
	if not isinstance(config, dict) or not config:
		return {}, problems

	element_id = str(node.get("id") or "")
	node_type = node.get("type")

	if node_type == "serviceTask":
		service_type = str(config.get("serviceType") or "").strip()
		if not service_type:
			problems.append(
				_problem(
					element_id,
					"A configured Service Task needs serviceType, one of: "
					+ ", ".join(sorted(_service_task_keys())),
				)
			)
			return {}, problems
		if service_type not in _service_task_keys():
			problems.append(
				_problem(
					element_id,
					f"'{service_type}' is not a Service Type. Use one of: "
					+ ", ".join(sorted(_service_task_keys())),
				)
			)
			return {}, problems
		allowed = _service_task_keys()[service_type]
		attrs = {"serviceType": service_type}
	elif node_type == "userTask":
		allowed = _user_task_keys()
		attrs = {}
	elif node_type == "startEvent":
		allowed = _start_event_keys()
		attrs = {}
	else:
		problems.append(
			_problem(
				element_id,
				f"'config' is only read on startEvent, serviceTask and userTask, not {node_type}.",
			)
		)
		return {}, problems

	for key, value in config.items():
		if key == "serviceType":
			continue
		if key not in allowed:
			hint = _misnamed().get(key)
			problems.append(
				_problem(
					element_id,
					f"'{key}' is not a setting here \u2014 use {hint}."
					if hint
					else f"'{key}' is not a setting on this task. Allowed: " + ", ".join(allowed),
				)
			)
			continue
		if value in (None, ""):
			continue
		if key == "taskActions":
			actions = normalise_task_actions(value)
			if actions:
				attrs[key] = actions
			continue
		if key in _bool_keys():
			attrs[key] = _as_attr_bool(value)
			continue
		if isinstance(value, (dict, list)):
			attrs[key] = json.dumps(value)
			continue
		attrs[key] = str(value)

	if node_type == "serviceTask" and attrs.get("serviceType") == "apply_workflow":
		_resolve_apply_workflow(attrs, element_id, problems)
	if node_type == "serviceTask" and attrs.get("serviceType") == "update_field":
		_check_update_field_rows(attrs, element_id, problems)

	if node_type == "startEvent":
		trigger = attrs.get("triggerType")
		if trigger and trigger not in _trigger_types():
			problems.append(
				_problem(
					element_id,
					f"'{trigger}' is not a Trigger Type. Use one of: " + ", ".join(_trigger_types()),
				)
			)
			attrs.pop("triggerType")
		# A trigger with no DocType starts on nothing, which looks configured
		# in the panel and never fires.
		if attrs.get("triggerType") and not attrs.get("triggerDoctype"):
			problems.append(_problem(element_id, "A start trigger also needs triggerDoctype."))

	if node_type == "userTask":
		mode = attrs.get("assigneeMode")
		if mode and mode not in _assignee_modes():
			problems.append(
				_problem(
					element_id,
					f"'{mode}' is not an Assignment Mode. Use one of: " + ", ".join(_assignee_modes()),
				)
			)
		companion = _mode_requires().get(mode or "")
		if companion and not attrs.get(companion):
			problems.append(_problem(element_id, f"Assignment Mode '{mode}' also needs {companion}."))

	return attrs, problems


def _check_update_field_rows(attrs: dict, element_id: str, problems: list) -> None:
	"""Drop each Update Field row whose value the field cannot hold, and report it."""
	import json

	import frappe
	from frappe import _

	doctype = attrs.get("updateFieldDoctype")
	if not doctype:
		return
	if not attrs.get("updateFieldRows"):
		return
	if not frappe.db.exists("DocType", doctype):
		return
	found = update_field_row_problems(doctype, attrs["updateFieldRows"])
	if found and found[0][0] is None:
		problems.append(_problem(element_id, found[0][1]))
		attrs.pop("updateFieldRows")
		return
	for _index, message in found:
		problems.append(
			_problem(element_id, message + " " + frappe._("I left this row out."), rule="update-field-value")
		)
	bad = {index for index, _message in found}
	kept = [row for index, row in enumerate(json.loads(attrs["updateFieldRows"])) if index not in bad]
	if kept:
		attrs["updateFieldRows"] = json.dumps(kept)
	else:
		attrs.pop("updateFieldRows")


def update_field_row_problems(doctype: str, rows_json: str) -> list[tuple[int | None, str]]:
	"""(row index, why) for each Update Field row doctype cannot hold; one (None, why) when rows_json is not a list."""
	import json

	from frappe import _

	try:
		rows = json.loads(rows_json or "[]")
	except ValueError:
		rows = None
	if not isinstance(rows, list):
		return [
			(
				None,
				frappe._(
					"The Field Updates are not a list of field and value rows, so the step writes nothing."
				),
			)
		]
	found = []
	for index, row in enumerate(rows):
		if not isinstance(row, dict):
			continue
		message = update_field_value_problem(doctype, row.get("field") or "", row.get("value"))
		if message:
			found.append((index, message))
	return found


def update_field_value_problem(doctype: str, fieldname: str, value) -> str:
	"""Why an Update Field row cannot write value into fieldname of doctype, or "" when it can."""
	import re

	import frappe
	from frappe import _
	from frappe.utils import get_datetime

	text = str(value if value is not None else "").strip()
	if not text:
		return ""
	if "{{" in text or "{%" in text:
		unknown = [name for name in re.findall(r"{{\s*([A-Za-z_]\w*)", text) if name not in _template_names()]
		if not unknown:
			return ""
		return frappe._(
			"'{0}' renders empty for {1} on {2}: a value can only read doc, instance or frappe. Write {{{{ doc.{3} }}}}."
		).format(text, fieldname, doctype, unknown[0])
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field:
		return ""
	if field.fieldtype == "Select":
		options = [o for o in (field.options or "").split("\n") if o.strip()]
		if text in options:
			return ""
		return frappe._("'{0}' is not an option of {1} on {2}. Allowed: {3}.").format(
			text, fieldname, doctype, ", ".join(options)
		)
	if field.fieldtype == "Link" and not frappe.db.exists(field.options, text):
		return frappe._("'{0}' is not a {1}, so {2} on {3} cannot hold it.").format(
			text, field.options, fieldname, doctype
		)
	try:
		if field.fieldtype in _number_fieldtypes():
			float(text)
		elif field.fieldtype in _date_fieldtypes() and text != "now":
			get_datetime(text)
	except ValueError:
		return frappe._(
			"'{0}' is not a {1} value for {2} on {3}. Write a value, {{{{ doc.fieldname }}}} or now; "
			"a value worked out when the process runs belongs in a Script Task."
		).format(text, field.fieldtype, fieldname, doctype)
	return ""


def resolve_ir_config(ir: dict) -> list[dict]:
	"""Resolve every node's ``config`` into ``attrs``, in place.

	The compiler writes ``attrs`` verbatim, so everything that needs judgement \u2014
	which keys are real, what a workflow state implies \u2014 is decided here where
	it can be tested against the site's own data.
	"""
	problems: list[dict] = []
	for node in (ir or {}).get("nodes") or []:
		if not isinstance(node, dict):
			continue
		# A repair pass returns the compiled attrs instead of config; they are checked the same way.
		if not node.get("config") and node.get("attrs"):
			node["config"] = node.pop("attrs")
		attrs, node_problems = resolve_node_attrs(node)
		problems.extend(node_problems)
		if attrs:
			node["attrs"] = attrs
		node.pop("config", None)
	return problems


def resolve_ir_conditions(ir: dict) -> None:
	"""Write every condition as Python, in place, and correct an action name that nearly matches one on the user task before it."""
	nodes = {n.get("id"): n for n in (ir or {}).get("nodes") or [] if isinstance(n, dict)}
	flows = [f for f in (ir or {}).get("flows") or [] if isinstance(f, dict)]
	for flow in flows:
		if not flow.get("condition"):
			continue
		condition = python_condition(str(flow["condition"]))
		actions = [
			a
			for f in flows
			if f.get("to") == flow.get("from")
			for a in _node_actions(nodes.get(f.get("from")))
		]
		if actions:
			condition = _closest_actions(condition, actions)
		flow["condition"] = condition


def python_condition(text: str) -> str:
	"""text with true, false, null, &&, || and !x written as Python and doc. prefixes dropped; quoted text is left alone."""
	import re

	parts = _quoted().split(text)
	for index in range(0, len(parts), 2):
		part = parts[index].replace("&&", " and ").replace("||", " or ")
		part = re.sub(r"!(?!=)", " not ", part)
		part = re.sub(r"\bdoc\.(?=[A-Za-z_])", "", part)
		part = re.sub(r"\b(true|false|null)\b", lambda m: _js_words()[m[1]], part)
		parts[index] = re.sub(r"\s+", " ", part)
	return "".join(parts).strip()


def _node_actions(node: dict | None) -> list[str]:
	"""The action names configured on an IR user task."""
	import json

	if not node or node.get("type") != "userTask":
		return []
	raw = (node.get("attrs") or {}).get("taskActions") or normalise_task_actions(
		(node.get("config") or {}).get("taskActions")
	)
	return [row["action"] for row in json.loads(raw)] if raw else []


def _closest_actions(condition: str, actions: list[str]) -> str:
	"""condition with each quoted name that is not an action replaced by the action it nearly matches."""
	import difflib

	by_lower = {a.lower(): a for a in actions}

	def closest(match):
		quote, word = match[1][0], match[1][1:-1]
		if word in actions:
			return match[1]
		near = difflib.get_close_matches(word.lower(), by_lower, 1, _action_cutoff())
		return f"{quote}{by_lower[near[0]]}{quote}" if near else match[1]

	return _quoted().sub(closest, condition)


def resolve_ir_lane_roles(ir: dict, roles: list[str]) -> list[dict]:
	"""Rewrite lane names that match a role ignoring case; report lanes with only similar roles."""
	from frappe import _

	from processa.ai_agent_registry.provisioning.bpmn_task_config import match_lane_role

	problems: list[dict] = []
	for lane in (ir or {}).get("lanes") or []:
		name = (lane.get("name") or "").strip()
		matches = match_lane_role(name, roles) if name else []
		if not matches:
			continue
		if matches[0].lower() == name.lower():
			lane["name"] = matches[0]
		else:
			message = frappe._("Lane '{0}' is not a Role. Did you mean {1}?").format(name, ", ".join(matches))
			problems.append(_problem(lane.get("id") or "", message, rule="lane-role"))
	return problems


def use_none_tasks(ir: dict) -> None:
	"""In a non-executable IR, make every task a plain None task and drop its task settings, in place."""
	if (ir or {}).get("executable") is not False:
		return
	for node in ir.get("nodes") or []:
		if node.get("type") in _none_task_sources():
			node["type"] = "task"
			node.pop("config", None)
			node.pop("attrs", None)
		if node.get("type") == "subProcess":
			use_none_tasks({"executable": False, **(node.get("children") or {})})
