# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Task configuration for a generated diagram: IR ``config`` -> spiffworkflow attributes.

A generated Service Task used to arrive on the canvas with a name and nothing
else, so every one of them had to be configured by hand afterwards. The model
can supply that configuration — it is in the person's own words ("set the Visa
Request to Pending GRD Manager Approval") — but the IR had nowhere to put it and
the compiler emitted only id and name.

This module is the contract between the two. It takes the ``config`` object the
generator writes on a node — a start event's trigger, a Service Task's operation,
a User Task's assignment — and returns the exact ``spiffworkflow:*`` attributes
the properties panel reads back, so a generated diagram and a hand-built one are
indistinguishable in the XML.

WHY THE KEYS ARE THE PANEL'S OWN NAMES
--------------------------------------
``serviceTargetDoctype``, ``emailDoctype``, ``pushDoctype`` and ``targetDoctype``
all mean "the DocType", and an alias layer that smooths that over is one more
thing to drift. The keys here ARE the attribute names, and a wrong-but-obvious
key comes back as a repair hint naming the right one — the generate loop already
knows how to act on those.

WHAT IS DERIVED RATHER THAN TRUSTED
-----------------------------------
A workflow state's document status and editing role are facts about the
workflow, not opinions: ``Workflow Document State`` already stores them per
state. Asking a model to restate them invites a diagram that says Draft is
status 1. It supplies the DocType and the target state; the rest is read off the
Workflow record, and a state that does not exist there comes back as a problem
listing the ones that do.
"""

from __future__ import annotations

import difflib
import json
import re

# Attributes each Service Type accepts, keyed by the serviceType value the panel
# writes. Anything outside the set for the chosen type is dropped and reported —
# a hallucinated attribute must never reach the canvas as a real setting.
SERVICE_TASK_KEYS: dict[str, tuple[str, ...]] = {
	"apply_workflow": ("serviceTargetDoctype", "workflowState", "docStatus", "onlyAllowEdit"),
	"send_email": (
		"emailAccount", "emailUseDoctype", "emailDoctype", "emailSubject",
		"emailTo", "emailToDocFields", "emailToTableField", "emailToTableUserField",
		"emailToRoles", "emailCc", "emailBcc", "emailBody",
		"emailLayout", "emailSubjectAr", "emailHeadingEn", "emailHeadingAr", "emailMessageEn",
		"emailMessageAr", "emailShowStatus", "emailFacts", "emailDetails", "emailAttachments",
		"emailArabicEdited",
	),
	"update_field": ("updateFieldDoctype", "updateFieldRows"),
	"google_chat": (
		"gchatType", "gchatRecipientBasis", "gchatEmail", "gchatDoctype", "gchatDocField",
		"gchatTableField", "gchatTableUserField", "gchatSpaceId", "gchatMessage",
	),
	"push_notification": (
		"pushDoctype", "pushTitle", "pushToUsers", "pushToDocFields",
		"pushToRoles", "pushMessage", "pushToTableField", "pushToTableUserField",
		"pushLinkToDocument", "pushFallbackInApp",
	),
	# Connector parameters are manifest-driven, so the params blob is passed
	# through as given rather than checked key by key here.
	"connector": ("connectorId", "connectorParams"),
}

USER_TASK_KEYS: tuple[str, ...] = (
	"targetDoctype", "assigneeMode", "assigneeUser", "assigneeUsers", "assigneeDocfield",
	"assigneeTableField", "assigneeTableUserField", "taskActions",
	"notifyAssignee", "notifyAssigneeAccount", "notifyAssigneeSubject",
	"notifyAssigneeBody", "notifyAssigneeTemplate",
	"notifyLayout", "notifySubjectAr", "notifyQuestionEn", "notifyQuestionAr",
	"notifyFacts", "notifyDetails", "notifyAttachments", "notifyActions",
	"notifyConversation", "notifyTokenHours", "notifyArabicEdited",
)

# What starts the process. The trigger is the one setting that decides whether a
# generated diagram ever runs on its own, so it is worth the model filling in.
START_EVENT_KEYS: tuple[str, ...] = ("triggerDoctype", "triggerType")

TRIGGER_TYPES = ("After Insert",)

DATE_FIELDTYPES = ("Date", "Datetime", "Time")
NUMBER_FIELDTYPES = ("Int", "Float", "Currency", "Percent", "Check")
# The names update_field renders a value with.
TEMPLATE_NAMES = ("doc", "instance", "frappe")

ASSIGNEE_MODES = ("User", "DocField", "Round Robin", "Load Balancing", "Table Field")

# The field that carries the assignee for each mode. A mode without its
# companion field assigns the task to nobody, which is only visible at runtime.
MODE_REQUIRES: dict[str, str] = {
	"User": "assigneeUser",
	"DocField": "assigneeDocfield",
	"Table Field": "assigneeTableField",
}

# Keys a model reaches for that are nearly right. Naming the real one costs a
# line here and saves a whole repair round trip.
_MISNAMED: dict[str, str] = {
	"doctype": "serviceTargetDoctype (Service Task) or targetDoctype (User Task)",
	"docType": "serviceTargetDoctype (Service Task) or targetDoctype (User Task)",
	"documentStatus": "docStatus",
	"nextWorkflowState": "workflowState",
	"state": "workflowState",
	"assignmentMode": "assigneeMode",
	"actions": "taskActions",
	"assignee": "assigneeUser",
}

# Checkbox attributes: the panel stores the string, and a real bool from JSON
# would render as "True" and read back as neither checked nor empty.
_BOOL_KEYS = frozenset({"emailUseDoctype", "notifyAssignee"})


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

		workflow = frappe.db.get_value(
			"Workflow", {"document_type": doctype, "is_active": 1}, "name"
		)
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
		problems.append(_problem(
			element_id,
			f"Apply Workflow needs workflowState. '{doctype}' allows: "
			+ ", ".join(r["state"] for r in rows),
		))
		return
	match = next((r for r in rows if r["state"] == state), None)
	if not match:
		problems.append(_problem(
			element_id,
			f"'{state}' is not a workflow state of '{doctype}'. Use one of: "
			+ ", ".join(r["state"] for r in rows),
		))
		return
	attrs["docStatus"] = str(match.get("doc_status") or "0")
	if match.get("allow_edit"):
		attrs["onlyAllowEdit"] = match["allow_edit"]


def _check_state_without_workflow(doctype: str, state: str, element_id: str, problems: list) -> None:
	"""Report a DocType with no active Workflow that cannot hold the state: no workflow_state field, or no such Workflow State."""
	import frappe
	from frappe import _

	if not frappe.db.exists("DocType", doctype):
		problems.append(_problem(element_id, _("'{0}' is not a DocType on this site.").format(doctype), rule="apply-workflow-doctype"))
	elif not frappe.get_meta(doctype).has_field("workflow_state"):
		problems.append(_problem(
			element_id,
			_("{0} has no active Workflow and no workflow_state field, so an Apply Workflow step on it cannot deploy. "
			"Add a workflow_state field to {0} first, or use an Update Field step.").format(doctype),
			rule="apply-workflow-doctype",
		))
	elif state and not frappe.db.exists("Workflow State", state):
		problems.append(_problem(
			element_id,
			_("'{0}' is not a Workflow State, so the workflow_state field of {1} cannot hold it.").format(state, doctype),
			rule="apply-workflow-doctype",
		))


def resolve_node_attrs(node: dict) -> tuple[dict, list[dict]]:
	"""The spiffworkflow attributes for one IR node, plus anything wrong with it."""
	problems: list[dict] = []
	config = node.get("config")
	if not isinstance(config, dict) or not config:
		return {}, problems

	element_id = str(node.get("id") or "")
	node_type = node.get("type")

	if node_type == "serviceTask":
		service_type = str(config.get("serviceType") or "").strip()
		if not service_type:
			problems.append(_problem(
				element_id,
				"A configured Service Task needs serviceType, one of: "
				+ ", ".join(sorted(SERVICE_TASK_KEYS)),
			))
			return {}, problems
		if service_type not in SERVICE_TASK_KEYS:
			problems.append(_problem(
				element_id,
				f"'{service_type}' is not a Service Type. Use one of: "
				+ ", ".join(sorted(SERVICE_TASK_KEYS)),
			))
			return {}, problems
		allowed = SERVICE_TASK_KEYS[service_type]
		attrs = {"serviceType": service_type}
	elif node_type == "userTask":
		allowed = USER_TASK_KEYS
		attrs = {}
	elif node_type == "startEvent":
		allowed = START_EVENT_KEYS
		attrs = {}
	else:
		problems.append(_problem(
			element_id,
			"'config' is only read on startEvent, serviceTask and userTask, "
			f"not {node_type}.",
		))
		return {}, problems

	for key, value in config.items():
		if key == "serviceType":
			continue
		if key not in allowed:
			hint = _MISNAMED.get(key)
			problems.append(_problem(
				element_id,
				f"'{key}' is not a setting here — use {hint}." if hint
				else f"'{key}' is not a setting on this task. Allowed: " + ", ".join(allowed),
			))
			continue
		if value in (None, ""):
			continue
		if key == "taskActions":
			actions = normalise_task_actions(value)
			if actions:
				attrs[key] = actions
			continue
		if key in _BOOL_KEYS:
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
		if trigger and trigger not in TRIGGER_TYPES:
			problems.append(_problem(
				element_id,
				f"'{trigger}' is not a Trigger Type. Use one of: " + ", ".join(TRIGGER_TYPES),
			))
			attrs.pop("triggerType")
		# A trigger with no DocType starts on nothing, which looks configured
		# in the panel and never fires.
		if attrs.get("triggerType") and not attrs.get("triggerDoctype"):
			problems.append(_problem(
				element_id, "A start trigger also needs triggerDoctype."
			))

	if node_type == "userTask":
		mode = attrs.get("assigneeMode")
		if mode and mode not in ASSIGNEE_MODES:
			problems.append(_problem(
				element_id,
				f"'{mode}' is not an Assignment Mode. Use one of: " + ", ".join(ASSIGNEE_MODES),
			))
		companion = MODE_REQUIRES.get(mode or "")
		if companion and not attrs.get(companion):
			problems.append(_problem(
				element_id, f"Assignment Mode '{mode}' also needs {companion}."
			))

	return attrs, problems


def _check_update_field_rows(attrs: dict, element_id: str, problems: list) -> None:
	"""Drop each Update Field row whose value the field cannot hold, and report it."""
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
		problems.append(_problem(element_id, message + " " + _("I left this row out."), rule="update-field-value"))
	bad = {index for index, _message in found}
	kept = [row for index, row in enumerate(json.loads(attrs["updateFieldRows"])) if index not in bad]
	if kept:
		attrs["updateFieldRows"] = json.dumps(kept)
	else:
		attrs.pop("updateFieldRows")


def update_field_row_problems(doctype: str, rows_json: str) -> list[tuple[int | None, str]]:
	"""(row index, why) for each Update Field row doctype cannot hold; one (None, why) when rows_json is not a list."""
	from frappe import _

	try:
		rows = json.loads(rows_json or "[]")
	except ValueError:
		rows = None
	if not isinstance(rows, list):
		return [(None, _("The Field Updates are not a list of field and value rows, so the step writes nothing."))]
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
	import frappe
	from frappe import _
	from frappe.utils import get_datetime

	text = str(value if value is not None else "").strip()
	if not text:
		return ""
	if "{{" in text or "{%" in text:
		unknown = [name for name in re.findall(r"{{\s*([A-Za-z_]\w*)", text) if name not in TEMPLATE_NAMES]
		if not unknown:
			return ""
		return _("'{0}' renders empty for {1} on {2}: a value can only read doc, instance or frappe. Write {{{{ doc.{3} }}}}.").format(
			text, fieldname, doctype, unknown[0]
		)
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field:
		return ""
	if field.fieldtype == "Select":
		options = [o for o in (field.options or "").split("\n") if o.strip()]
		if text in options:
			return ""
		return _("'{0}' is not an option of {1} on {2}. Allowed: {3}.").format(text, fieldname, doctype, ", ".join(options))
	if field.fieldtype == "Link" and not frappe.db.exists(field.options, text):
		return _("'{0}' is not a {1}, so {2} on {3} cannot hold it.").format(text, field.options, fieldname, doctype)
	try:
		if field.fieldtype in NUMBER_FIELDTYPES:
			float(text)
		elif field.fieldtype in DATE_FIELDTYPES and text != "now":
			get_datetime(text)
	except ValueError:
		return _(
			"'{0}' is not a {1} value for {2} on {3}. Write a value, {{{{ doc.fieldname }}}} or now; "
			"a value worked out when the process runs belongs in a Script Task."
		).format(text, field.fieldtype, fieldname, doctype)
	return ""


def resolve_ir_config(ir: dict) -> list[dict]:
	"""Resolve every node's ``config`` into ``attrs``, in place.

	The compiler writes ``attrs`` verbatim, so everything that needs judgement —
	which keys are real, what a workflow state implies — is decided here where
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


LANE_ROLE_CUTOFF = 0.75
LANE_ROLE_EXCLUDED = frozenset({"Administrator"})
LANE_ROLE_SUGGESTIONS = 3


def match_lane_role(name: str, roles: list[str]) -> list[str]:
	"""The role equal to name ignoring case, else up to three similar roles."""
	roles = [role for role in roles if role not in LANE_ROLE_EXCLUDED]
	for role in roles:
		if role.lower() == name.strip().lower():
			return [role]
	by_lower = {role.lower(): role for role in roles}
	close = difflib.get_close_matches(name.strip().lower(), by_lower, LANE_ROLE_SUGGESTIONS, LANE_ROLE_CUTOFF)
	return [by_lower[c] for c in close]


def resolve_ir_lane_roles(ir: dict, roles: list[str]) -> list[dict]:
	"""Rewrite lane names that match a role ignoring case; report lanes with only similar roles."""
	from frappe import _

	problems: list[dict] = []
	for lane in (ir or {}).get("lanes") or []:
		name = (lane.get("name") or "").strip()
		matches = match_lane_role(name, roles) if name else []
		if not matches:
			continue
		if matches[0].lower() == name.lower():
			lane["name"] = matches[0]
		else:
			message = _("Lane '{0}' is not a Role. Did you mean {1}?").format(name, ", ".join(matches))
			problems.append(_problem(lane.get("id") or "", message, rule="lane-role"))
	return problems


NONE_TASK_SOURCES = frozenset({"userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask"})


def use_none_tasks(ir: dict) -> None:
	"""In a non-executable IR, make every task a plain None task and drop its task settings, in place."""
	if (ir or {}).get("executable") is not False:
		return
	for node in ir.get("nodes") or []:
		if node.get("type") in NONE_TASK_SOURCES:
			node["type"] = "task"
			node.pop("config", None)
			node.pop("attrs", None)
		if node.get("type") == "subProcess":
			use_none_tasks({"executable": False, **(node.get("children") or {})})
