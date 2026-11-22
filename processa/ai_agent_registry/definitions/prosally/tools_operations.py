# Copyright (c) 2026, one-fm and contributors
"""ProsAlly edits a map by applying a short list of operations to its IR, so what they do not name stays as it was."""

import copy

from frappe import _

from processa.ai_agent_registry.definitions.prosally.tools_review import IR_NODE_TYPES


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
	if not new_id or _element(ir, new_id):
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
		if len(into) == 1 and len(out) == 1 and into[0] is not out[0]:
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
	return _("there is no step, arrow or lane with the id {0} on the diagram").format(element_id)


def _label(operation) -> str:
	return (
		(operation.get("name") or operation.get("id") or "")
		if isinstance(operation, dict)
		else str(operation)
	)
