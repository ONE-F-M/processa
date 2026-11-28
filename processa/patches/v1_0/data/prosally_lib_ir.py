# ProsAlly IR helpers: read model replies, fix and merge the diagram IR, apply operations and explain problems.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


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


def _none_task_sources():
	return frozenset({"userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask"})


def _rule_hints():
	return {
		"task-type": (
			"Change the node's 'type' field. 'task' is forbidden. "
			"Use: 'userTask' (person acts on screen), 'scriptTask' (system runs automatically), "
			"'serviceTask' (external API/service), 'manualTask' (physical real-world action)."
		),
		"start-event-required": ("Add a node with type='startEvent'. The process must have exactly one."),
		"end-event-required": ("Add a node with type='endEvent'. The process must have at least one."),
		"single-blank-start-event": (
			"Remove extra startEvent nodes \u2014 keep exactly one startEvent in the entire process."
		),
		"no-disconnected": (
			"This node has no flows at all. Add incoming and/or outgoing flows connecting it "
			"to the rest of the process, or remove the node entirely."
		),
		"no-implicit-start": (
			"This node has no incoming flow but is not a startEvent. "
			"Add a flow leading into it from a predecessor node."
		),
		"no-implicit-end": (
			"This node has no outgoing flow but is not an endEvent. "
			"Add a flow leading out of it to a successor node."
		),
		"no-gateway-join-fork": (
			"A gateway cannot both join (multiple incoming) AND fork (multiple outgoing) at the same time. "
			"Replace it with TWO separate gateways: a join gateway (N→1) immediately followed by a fork gateway (1→N)."
		),
		"superfluous-gateway": (
			"This gateway has exactly 1 incoming and 1 outgoing flow \u2014 it serves no purpose. "
			"Remove it and connect its predecessor directly to its successor."
		),
		"conditional-flows": (
			"For every exclusiveGateway split: mark exactly one outgoing flow with 'default': true "
			"(the else/fallback path), and add a 'condition' field to every other outgoing flow."
		),
		"label-required": (
			"Add a descriptive 'name' field to this node or flow. Every element must have a non-empty name."
		),
		"no-bpmndi": ("DI shapes are added by the compiler \u2014 no IR change needed for this rule."),
		"no-complex-gateway": (
			"Remove the complexGateway node. Replace it with an exclusiveGateway or parallelGateway."
		),
		"no-inclusive-gateway": (
			"Remove the inclusiveGateway node. Replace it with an exclusiveGateway or parallelGateway."
		),
		"no-duplicate-sequence-flows": (
			"Two flows connect the same pair of nodes. Remove one of the duplicate flows."
		),
		"lane-orphan": (
			"Add a 'lane' field to this node. Every node must be assigned to one of the lane ids "
			"defined in the 'lanes' array. Match the lane to the actor who performs the work: "
			"userTask → person's lane, scriptTask/serviceTask → 'system' lane, "
			"startEvent → lane of whoever triggers the process, "
			"endEvent → lane of the last meaningful actor before it, "
			"gateway → same lane as the task immediately before it."
		),
		"lane-bounds": (
			"This node's visual position falls outside its lane band. The 'lane' field is likely wrong. "
			"Change the node's 'lane' to the correct lane id for the actor performing this step."
		),
		"non-planar": (
			"The flow graph cannot be drawn without lines crossing; no layout can change that. "
			"If a returning flow can join at an existing merge gateway with the same behaviour, join there. "
			"Otherwise keep the IR as it is and tell the user one crossing is unavoidable. "
			"Do not regenerate to chase a crossing-free drawing."
		),
	}


def _ir_ignorable_rules():
	return frozenset(
		{
			"no-bpmndi",
			"edge-crossing",
			"edge-through-shape",
			"collinear-overlap",
			"label-collision",
		}
	)


def _id_skip_types():
	return frozenset(
		{
			"definitions",
			"process",
			"collaboration",
			"participant",
			"laneSet",
			"lane",
			"BPMNDiagram",
			"BPMNPlane",
			"BPMNShape",
			"BPMNEdge",
			"messageEventDefinition",
			"timerEventDefinition",
			"conditionalEventDefinition",
			"signalEventDefinition",
			"terminateEventDefinition",
			"dataObject",
			"incoming",
			"outgoing",
			"conditionExpression",
		}
	)


def _system_lane_node_types():
	return frozenset({"scriptTask", "serviceTask"})


def _history_turns():
	return 10


def apply_operations(ir: dict, operations: list) -> tuple[dict | None, str]:
	"""(ir with every operation applied, "") or (None, which operation failed and why); ir itself never changes."""
	import copy

	edited = copy.deepcopy(ir)
	for number, operation in enumerate(operations, 1):
		problem = (
			_apply(edited, operation) if isinstance(operation, dict) else frappe._("it is not an operation")
		)
		if problem:
			return None, frappe._('Change {0} ({1} "{2}") could not be made: {3}.').format(
				number,
				operation.get("op", "") if isinstance(operation, dict) else "",
				_label(operation),
				problem,
			)
	return edited, ""


def _apply(ir: dict, operation: dict) -> str:
	handler = _operations().get(operation.get("op"))
	if handler is None:
		return frappe._("it is not one of {0}").format(", ".join(_operations()))
	return handler(ir, operation)


def _operations() -> dict:
	return {
		"add": _add,
		"remove": _remove,
		"rename": _rename,
		"reconnect": _reconnect,
		"retype": _retype,
		"move": _move,
		"set_condition": _set_condition,
	}


def _add(ir: dict, operation: dict) -> str:
	kind, new_id = operation.get("type"), operation.get("id")
	if not new_id:
		return frappe._("the new element needs an id that is not used yet")
	if _element(ir, new_id):
		return frappe._("the new element needs an id that is not used yet")
	if kind == "sequenceFlow":
		ends = _ends_problem(ir, operation.get("from"), operation.get("to"))
		if ends:
			return ends
		flow = {"id": new_id, "from": operation["from"], "to": operation["to"]}
		flow.update({key: operation[key] for key in ("name", "condition", "default") if operation.get(key)})
		ir["flows"].append(flow)
	elif kind == "lane":
		if not ir["lanes"]:
			return frappe._("the diagram has no lanes, so a lane cannot be added to it")
		ir["lanes"].append({"id": new_id, "name": operation.get("name") or new_id})
	elif kind in _ir_node_types():
		lane = _lane_problem(ir, operation.get("lane"))
		if lane:
			return lane
		node = {"id": new_id, "name": operation.get("name") or "", "type": kind}
		if operation.get("lane"):
			node["lane"] = operation["lane"]
		ir["nodes"].append(node)
	else:
		return frappe._("{0} is not a kind of element the diagram can hold").format(kind)
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
			return frappe._("the lane still has steps in it")
		ir["lanes"].remove(lane)
		return ""
	return _missing(target)


def _rename(ir: dict, operation: dict) -> str:
	element = _element(ir, operation.get("id"))
	if not element:
		return _missing(operation.get("id"))
	if not operation.get("name"):
		return frappe._("the new name is empty")
	element["name"] = operation["name"]
	return ""


def _reconnect(ir: dict, operation: dict) -> str:
	flow = _by_id(ir["flows"], operation.get("id"))
	if not flow:
		return frappe._("there is no arrow with the id {0}").format(operation.get("id"))
	source, target = operation.get("from") or flow["from"], operation.get("to") or flow["to"]
	ends = _ends_problem(ir, source, target)
	if ends:
		return ends
	flow["from"], flow["to"] = source, target
	return ""


def _retype(ir: dict, operation: dict) -> str:
	node = _by_id(ir["nodes"], operation.get("id"))
	if not node:
		return frappe._("there is no step with the id {0}").format(operation.get("id"))
	kind = operation.get("type")
	if kind not in _ir_node_types():
		return frappe._("{0} is not a kind of step the diagram can hold").format(kind)
	if "subProcess" in (kind, node["type"]):
		return frappe._(
			"a sub-process holds steps of its own, so it cannot be changed to or from another kind"
		)
	if ir.get("executable") is False and kind in _none_task_sources():
		return frappe._(
			"this process is non-executable, so its tasks stay plain tasks. Make the process executable first"
		)
	node["type"] = kind
	return ""


def _move(ir: dict, operation: dict) -> str:
	node = _by_id(ir["nodes"], operation.get("id"))
	if not node:
		return frappe._("there is no step with the id {0}").format(operation.get("id"))
	if not ir["lanes"]:
		return frappe._("the diagram has no lanes, so the step cannot move to one")
	if not _by_id(ir["lanes"], operation.get("lane")):
		return frappe._("{0} is not one of the diagram's lanes: {1}").format(
			operation.get("lane"), ", ".join(lane["id"] for lane in ir["lanes"])
		)
	node["lane"] = operation["lane"]
	return ""


def _set_condition(ir: dict, operation: dict) -> str:
	flow = _by_id(ir["flows"], operation.get("id"))
	if not flow:
		return frappe._("there is no arrow with the id {0}").format(operation.get("id"))
	if operation.get("default"):
		for other in ir["flows"]:
			if other["from"] == flow["from"]:
				other.pop("default", None)
		flow["default"] = True
		flow.pop("condition", None)
		return ""
	condition = str(operation.get("condition") or "").strip()
	if not condition:
		return frappe._("the condition is empty")
	flow["condition"] = condition
	flow.pop("default", None)
	return ""


def _ends_problem(ir: dict, source: str | None, target: str | None) -> str:
	for end in (source, target):
		if not _by_id(ir["nodes"], end):
			return frappe._("an arrow can only join steps on the diagram, and {0} is not one").format(end)
	return ""


def _lane_problem(ir: dict, lane: str | None) -> str:
	if ir["lanes"] and not _by_id(ir["lanes"], lane):
		return frappe._("a new step needs one of the diagram's lanes: {0}").format(
			", ".join(lane["id"] for lane in ir["lanes"])
		)
	if lane and not ir["lanes"]:
		return frappe._("the diagram has no lanes, so the step cannot go in one")
	return ""


def _element(ir: dict, element_id: str | None) -> dict | None:
	return (
		_by_id(ir["nodes"], element_id) or _by_id(ir["flows"], element_id) or _by_id(ir["lanes"], element_id)
	)


def _by_id(items: list, element_id: str | None) -> dict | None:
	return next((item for item in items if element_id and item.get("id") == element_id), None)


def _missing(element_id: str | None) -> str:
	return frappe._("there is no step, arrow or lane called {0} on the diagram").format(element_id)


def _label(operation) -> str:
	return (
		(operation.get("name") or operation.get("id") or "")
		if isinstance(operation, dict)
		else str(operation)
	)


def ensure_default_lanes(ir: dict) -> bool:
	"""Apply the generator prompt's own "User" + "System (Automatic)" lane
	fallback in code, so a missing lane structure skips a repair-pass retry.

	Mutates ``ir`` in place; returns True when it changed anything. Returns
	False when there are no nodes to assign, so the caller still re-prompts.
	"""
	import re

	if len(ir.get("lanes") or []) >= 2:
		return False
	nodes = ir.get("nodes") or []
	if not nodes:
		return False
	ir["lanes"] = [
		{"id": "user", "name": "User"},
		{"id": "system", "name": "System (Automatic)"},
	]
	for node in nodes:
		if not node.get("lane"):
			node["lane"] = "system" if node.get("type") in _system_lane_node_types() else "user"
	return True


def auto_fix_ir(ir: dict) -> list[str]:
	"""Fix in place the IR problems the compiler names exactly and return one line per fix: drop flows to
	or from a missing node, default the last unconditioned flow of an exclusiveGateway split that has
	none, and give a node with no lane its predecessor's lane."""
	nodes = {n.get("id"): n for n in ir.get("nodes") or [] if n.get("id")}
	fixes = []
	kept = []
	for flow in ir.get("flows") or []:
		missing = [end for end in (flow.get("from"), flow.get("to")) if end not in nodes]
		if missing:
			gone = ", ".join(map(str, missing))
			fixes.append(f"Dropped flow {flow.get('from')} -> {flow.get('to')}: no node {gone}")
		else:
			kept.append(flow)
	ir["flows"] = kept

	for node_id, node in nodes.items():
		outgoing = [f for f in kept if f.get("from") == node_id]
		if node.get("type") != "exclusiveGateway":
			continue
		if len(outgoing) < 2:
			continue
		if any(f.get("default") for f in outgoing):
			continue
		unconditioned = [f for f in outgoing if not f.get("condition")]
		if unconditioned:
			unconditioned[-1]["default"] = True
			fixes.append(
				f"Marked flow {node_id} -> {unconditioned[-1].get('to')} as the default of {node_id}"
			)

	if ir.get("lanes"):
		changed = True
		while changed:
			changed = False
			for flow in kept:
				source, target = nodes[flow["from"]], nodes[flow["to"]]
				if source.get("lane") and not target.get("lane"):
					target["lane"] = source["lane"]
					fixes.append(f"Put {flow['to']} in lane {source['lane']}, the lane of {flow['from']}")
					changed = True
	return fixes


def merge_chunked_ir(lanes: list, chunks: list) -> dict:
	"""Combine ordered per-phase IR fragments into one IR sharing one lane set.

	Each chunk is {"nodes": [...], "flows": [...]} for one phase of a process
	generated in pieces because the whole thing would not fit in one
	completion. A chunk's own flows already connect its first node from the
	exit id it was given, so merging is concatenation.
	"""
	nodes = []
	flows = []
	for chunk in chunks:
		nodes.extend(chunk.get("nodes") or [])
		flows.extend(chunk.get("flows") or [])
	return {"lanes": lanes, "nodes": nodes, "flows": flows}


def chunk_exit_node_id(chunk: dict) -> str | None:
	"""The node id the next phase's flow should originate from.

	By convention the phase prompt asks for the hand-off node last, so it is
	the final entry in this chunk's own "nodes" array.
	"""
	nodes = chunk.get("nodes") or []
	return nodes[-1].get("id") if nodes else None


def extract_process_name(bpmn_xml: str) -> str:
	"""Extract the human-readable process name from BPMN XML.

	pipeline.mjs puts the process name on ``<bpmn:Participant name="...">`` (the
	pool header), not on ``<bpmn:Process>``. Prefer the participant name; fall
	back to the process name. Returns "" if none is found.
	"""
	import re

	if not bpmn_xml:
		return ""
	match = re.search(r'<bpmn:Participant[^>]+name="([^"]+)"', bpmn_xml)
	if match and match.group(1) != "Process":
		return match.group(1)
	match = re.search(r'<bpmn:Process[^>]+name="([^"]+)"', bpmn_xml)
	if match:
		return match.group(1)
	return ""


def extract_element_ids(xml: str) -> str:
	"""Return a table of element IDs the LLM must preserve during a modify.

	Skips structural/DI/definition elements (see ``_id_skip_types()``) and lists
	each real element as ``  <type> id="..." name="..."``.
	"""
	lines = []
	for elem_id, (bpmn_type, elem_name) in element_names(xml).items():
		label = f' name="{elem_name}"' if elem_name else ""
		lines.append(f'  {bpmn_type} id="{elem_id}"{label}')
	return "\n".join(lines)


def element_names(xml: str) -> dict[str, tuple[str, str]]:
	"""{id: (type, name)} for every real element of a BPMN XML string; name is "" when it has none."""
	import re

	elements = {}
	for m in re.finditer(r"<bpmn:(\w+)\s([^>]*?)/?>", xml or ""):
		if m.group(1) in _id_skip_types():
			continue
		id_m = re.search(r'id="([^"]+)"', m.group(2))
		if id_m:
			name_m = re.search(r'name="([^"]*)"', m.group(2))
			elements[id_m.group(1)] = (m.group(1), name_m.group(1) if name_m else "")
	return elements


def translate_problems(problems: list) -> list[str]:
	"""Convert pipeline problem dicts into IR-level fix hints (deduped, ignorable rules removed)."""
	hints: list[str] = []
	seen: set[tuple] = set()
	for p in problems:
		rule = p.get("rule") or ""
		kind = p.get("kind") or ""
		eid = p.get("elementId") or ""
		msg = p.get("message") or str(p)

		if rule in _ir_ignorable_rules():
			continue

		key = (rule or kind, eid)
		if key in seen:
			continue
		seen.add(key)

		hint_body = _rule_hints().get(rule, msg)
		label = rule or kind or "problem"
		if eid:
			hints.append(f"[{label}] Element '{eid}': {hint_body}")
		else:
			hints.append(f"[{label}] {hint_body}")
	return hints


def translate_violations(violations: list[str]) -> list[str]:
	"""Convert prosally.validators violation strings to IR-level fix hints (deduped)."""
	import re

	hints: list[str] = []
	seen: set[str] = set()
	for v in violations:
		rule_match = re.match(r"\[([^\]]+)\]", v)
		rule = rule_match.group(1) if rule_match else ""
		if rule in _ir_ignorable_rules():
			continue
		if rule in seen:
			continue
		seen.add(rule or v[:60])
		hint = _rule_hints().get(rule, v)
		hints.append(f"[{rule}] {hint}" if rule else hint)
	return hints


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last _history_turns() messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-_history_turns() :]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def extract_json(raw: str) -> dict | None:
	"""The first JSON object found in a model reply: whole, fenced, or embedded in prose.

	Literal newlines inside string values are accepted, since models often write them.
	"""
	import json
	import re

	if not raw:
		return None
	stripped = raw.strip()
	candidates = [stripped]
	fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
	if fenced:
		candidates.append(fenced.group(1).strip())
	greedy = re.search(r"\{[\s\S]*\}", raw)
	if greedy:
		candidates.append(greedy.group(0))
	if stripped.startswith("```"):
		unfenced = stripped.split("\n", 1)[-1]
		if unfenced.rstrip().endswith("```"):
			unfenced = unfenced.rstrip()[: unfenced.rstrip().rfind("```")]
		candidates.append(unfenced.strip())
	start = raw.find("{")
	if start != -1:
		depth = 0
		for i in range(start, len(raw)):
			if raw[i] == "{":
				depth += 1
			elif raw[i] == "}":
				depth -= 1
				if depth == 0:
					candidates.append(raw[start : i + 1])
					break
	for candidate in candidates:
		try:
			parsed = json.loads(candidate, strict=False)
		except json.JSONDecodeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None
