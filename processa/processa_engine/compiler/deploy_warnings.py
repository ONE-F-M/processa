# Copyright (c) 2026, one-fm and contributors
"""Deploy warnings: advisory findings returned with a successful deploy, never a refusal."""

import ast
import builtins
import json
import re

import frappe
from frappe import _


def check_eval_suite_gating(model_name: str) -> list:
	"""Advisory warnings for gating eval suites that have never run or last failed."""
	warnings = []

	suites = frappe.get_list(
		"AI Eval Suite",
		filters={"process_model": model_name, "gate_deployment": 1},
		fields=["name", "title"],
		ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
	)

	if not suites:
		return warnings

	for suite in suites:
		suite_title = suite.title or suite.name

		latest_runs = frappe.get_list(
			"AI Eval Run",
			filters={"suite": suite.name},
			fields=["name", "status", "started_at"],
			order_by="started_at desc",
			limit_page_length=1,
			ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
		)

		if not latest_runs:
			warnings.append(
				_("Eval suite '{0}' has never been run. "
				  "Consider running it before deploying.").format(suite_title)
			)
		elif latest_runs[0].status == "Failed":
			run_date = frappe.utils.formatdate(latest_runs[0].started_at)
			warnings.append(
				_("Eval suite '{0}' failed - last run on {1}. "
				  "Consider re-running the suite before deploying.").format(
					suite_title, run_date
				)
			)

	return warnings


def check_connector_tools_can_answer(bpmn_xml: str) -> list:
	"""Warn for each connector tool with no Result Variable, which runs but returns nothing to the agent."""
	from processa.processa_engine.maps.readiness import connector_tools_without_result_variable

	return [
		{
			"label": _("Connector tool returns nothing"),
			"icon": "plug",
			"type": "warning",
			"detail": _(
				"'{0}' has no Result Variable, so the {1} connector will run for the "
				"'{2}' agent but return no data to it. Set a Result Variable on that shape."
			).format(g["shape"] or g["bpmn_id"], g["connector"] or _("connector"), g["agent"]),
		}
		for g in connector_tools_without_result_variable(bpmn_xml)
	]


def check_ai_tasks_have_a_user_prompt(spec_data: dict) -> list:
	"""Warn for each AI Agent Task with a system prompt but no user prompt."""
	warnings = []
	for bpmn_id, cfg in (spec_data.get("service_task_extensions") or {}).items():
		if (cfg or {}).get("serviceType") != "ai_agent":
			continue
		if not str(cfg.get("aiSystemPrompt") or "").strip():
			continue
		if str(cfg.get("aiUserPrompt") or "").strip():
			continue
		warnings.append({
			"label": _("AI task has no user prompt"),
			"icon": "message-square-off",
			"type": "warning",
			"detail": _(
				"'{0}' has a system prompt but no user prompt, so the agent will be asked "
				"nothing and will reply that it was given no content. Set the User Prompt "
				"on that task - e.g. a variable the map filled in earlier."
			).format(bpmn_id),
		})
	return warnings


def check_email_settings(service_extensions: dict, user_extensions: dict) -> list:
	"""One warning per Send Email task or notifying User Task whose recipients, subject or body are empty."""
	return [_email_warning(bpmn_id, missing) for bpmn_id, missing in email_setting_gaps(service_extensions, user_extensions)]


def email_setting_gaps(service_extensions: dict, user_extensions: dict) -> list:
	"""(bpmn_id, missing parts) for each Send Email task or notifying User Task with an empty recipient, subject or body."""
	recipient_keys = ("emailTo", "emailToDocFields", "emailToTableField", "emailToRoles")
	gaps = []
	for bpmn_id, cfg in service_extensions.items():
		if cfg.get("serviceType") != "send_email":
			continue
		missing = []
		if not any(str(cfg.get(key) or "").strip() for key in recipient_keys):
			missing.append(_("recipients"))
		if not str(cfg.get("emailSubject") or "").strip():
			missing.append(_("subject"))
		if not str(cfg.get("emailBody") or "").strip():
			missing.append(_("body"))
		if missing:
			gaps.append((bpmn_id, missing))
	for bpmn_id, cfg in user_extensions.items():
		if cfg.get("notifyAssignee") != "true":
			continue
		template = str(cfg.get("notifyAssigneeTemplate") or cfg.get("notifyTemplate") or "").strip()
		subject = str(cfg.get("notifyAssigneeSubject") or cfg.get("notifySubject") or "").strip()
		body = str(cfg.get("notifyAssigneeBody") or cfg.get("notifyBody") or "").strip()
		missing = []
		if not (template or subject):
			missing.append(_("subject"))
		if not (template or body):
			missing.append(_("body"))
		if missing:
			gaps.append((bpmn_id, missing))
	return gaps


def _email_warning(bpmn_id: str, missing: list) -> dict:
	return {
		"label": _("Email settings are empty"),
		"icon": "mail-warning",
		"type": "warning",
		"detail": _("'{0}' sends an email with no {1}. Fill these in so the email goes out as intended.").format(
			bpmn_id, ", ".join(missing)
		),
	}


def check_notification_senders(service_extensions: dict, user_extensions: dict) -> list:
	"""On a Production instance, one warning per notification that does not send from the configured address."""
	expected, gaps = notification_sender_gaps(service_extensions, user_extensions)
	return [
		{
			"label": _("Notification sender is not {0}").format(expected),
			"icon": "mail-warning",
			"type": "warning",
			"detail": _("'{0}' sends from {1}. On this Production site notifications should send from {2}.").format(
				bpmn_id, sender, expected
			),
		}
		for bpmn_id, sender in gaps
	]


def notification_sender_gaps(service_extensions: dict, user_extensions: dict) -> tuple:
	"""(expected address, [(bpmn_id, sender)]) for notifications sending from another address; empty off Production."""
	from processa.api.editability import get_instance_type

	account = frappe.db.get_single_value("Processa Settings", "production_notification_account")
	if get_instance_type() != "Production" or not account:
		return "", []
	expected = frappe.db.get_value("Email Account", account, "email_id") or ""
	accounts = [
		(bpmn_id, cfg.get("emailAccount"))
		for bpmn_id, cfg in service_extensions.items()
		if cfg.get("serviceType") == "send_email"
	]
	accounts += [
		(bpmn_id, cfg.get("notifyAssigneeAccount") or cfg.get("emailAccount"))
		for bpmn_id, cfg in user_extensions.items()
		if cfg.get("notifyAssignee") == "true"
	]
	default_sender = frappe.db.get_value("Email Account", {"default_outgoing": 1}, "email_id")
	gaps = []
	for bpmn_id, account in accounts:
		account = str(account or "").strip()
		sender = frappe.db.get_value("Email Account", account, "email_id") if account else default_sender
		if (sender or "").strip().lower() != expected.lower():
			gaps.append((bpmn_id, sender or account or _("no email account")))
	return expected, gaps


def check_script_tasks_have_a_script(bpmn_xml: str) -> list:
	"""One warning per Script Task with no Server Script and no inline script."""
	import xml.etree.ElementTree as _ET

	return [
		{
			"label": _("Script is empty"),
			"icon": "file-warning",
			"type": "warning",
			"detail": _("'{0}' has no script, so it does nothing when it runs. Pick a Server Script or write one.").format(
				bpmn_id
			),
		}
		for bpmn_id in empty_script_tasks(_ET.fromstring(bpmn_xml.strip().encode("utf-8")))
	]


def empty_script_tasks(root) -> list:
	"""Ids of the Script Tasks under *root* that have neither a Server Script nor an inline script."""
	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	spiff_ns = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	empty = []
	for task in root.iter(f"{{{bpmn_ns}}}scriptTask"):
		script = task.find(f"{{{bpmn_ns}}}script")
		if (task.get(f"{{{spiff_ns}}}serverScript") or "").strip():
			continue
		if script is not None and (script.text or "").strip():
			continue
		empty.append(task.get("id"))
	return empty


def check_shape_config_drift(service_extensions: dict) -> list:
	"""One warning per AI shape whose DRIFT_FIELDS differ from its linked configuration."""
	from processa.ai_agent_registry.provisioning.agent_config_resolver import config_field_map, shape_config_drift

	warnings = []
	live_by_config = {}
	for bpmn_id, cfg in service_extensions.items():
		if cfg.get("serviceType") not in ("ai_agent", "ai_task_selector"):
			continue
		config_name = cfg.get("aiAgentConfig") or ""
		if config_name not in live_by_config:
			live_by_config[config_name] = config_field_map(config_name)
		drift = shape_config_drift(cfg, live_by_config[config_name])
		if not drift:
			continue
		warnings.append({
			"label": _("AI task differs from its configuration"),
			"icon": "git-compare",
			"type": "warning",
			"detail": _("'{0}' differs from AI Agent Configuration '{1}'. What runs: {2}").format(
				bpmn_id, config_name, "; ".join(_drift_line(d) for d in drift)
			),
		})
	return warnings


def _drift_line(drift: dict) -> str:
	if drift["field"] == "aiSystemPrompt":
		return _("{0} is the configuration's ({1} characters, the shape has {2})").format(
			drift["label"], len(drift["live"]), len(drift["shape"])
		)
	return _("{0} {1} (the shape says {2})").format(drift["label"], drift["live"], drift["shape"] or _("nothing"))


BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
# Names the engine puts in task data on every run; document fields come in as bare names too.
ENGINE_NAMES = frozenset({"triggered_by", "trigger_doctype", "trigger_docname", "context_doctype", "context_docname", "docstatus"})
# JavaScript spellings a condition cannot read.
UNREADABLE_NAMES = frozenset({"true", "false", "null"})
DOCTYPE_ATTRS = ("triggerDoctype", "targetDoctype", "serviceTargetDoctype", "updateFieldDoctype")
CHECK_STEP = re.compile(r"(?i)\b(validate|check|verify)\b|^\s*is\b.*\b(allowed|eligible|valid)\b")


def gateway_condition_gaps(root, doctypes: tuple = ()) -> list:
	"""(element id, why) per gateway condition a step cannot satisfy, per check step no gateway follows, and per script that does not parse."""
	elements = {el.get("id"): el for el in root.iter() if el.get("id")}
	flows = list(root.iter(f"{{{BPMN_NS}}}sequenceFlow"))
	named = {el.get(f"{{{SPIFF_NS}}}{attr}") for el in elements.values() for attr in DOCTYPE_ATTRS}
	fields = _document_fields({*doctypes, *named} - {None, ""})
	gaps = []
	keys = {}
	for el in elements.values():
		if _tag(el) != "scriptTask":
			continue
		try:
			keys[el.get("id")] = _script_keys(el)
		except SyntaxError:
			keys[el.get("id")] = set()
			gaps.append((el.get("id"), _("Its script is not valid Python, so it sets nothing a decision can test.")))
	produced = ENGINE_NAMES | fields | _step_outputs(elements.values(), keys)
	for flow in flows:
		expression = flow.find(f"{{{BPMN_NS}}}conditionExpression")
		if expression is None:
			continue
		gateway = elements.get(flow.get("sourceRef"))
		if gateway is None or _tag(gateway) != "exclusiveGateway":
			continue
		before = [elements[f.get("sourceRef")] for f in flows if f.get("targetRef") == gateway.get("id") and f.get("sourceRef") in elements]
		message = _condition_gap((expression.text or "").strip(), before, produced, fields, keys)
		if message:
			gaps.append((gateway.get("id"), message))
	gaps += _unrouted_checks(elements, flows)
	return gaps


def _step_outputs(elements, keys: dict) -> set:
	"""Every name a step of the map puts in task data: action, script keys and result variables."""
	names = set()
	for el in elements:
		if _tag(el) == "userTask" and _task_actions(el):
			names.add("action")
		names |= keys.get(el.get("id")) or set()
		names |= {value for attr, value in el.attrib.items() if attr.startswith(f"{{{SPIFF_NS}}}") and attr.endswith("Variable") and value}
	return names


def _condition_gap(text: str, before: list, produced: frozenset, fields: frozenset, keys: dict) -> str:
	"""Why a condition after the steps in before never routes as drawn, or ""."""
	if not text:
		return ""
	try:
		tree = ast.parse(text, mode="eval")
	except SyntaxError:
		return _("\"{0}\" is not a Python expression.").format(text)
	names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - frozenset(dir(builtins))
	if "doc" in names:
		field = next((n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and getattr(n.value, "id", "") == "doc"), "")
		return _("\"{0}\" reads doc, which a condition cannot see. Write the field name alone, for example {1}.").format(text, field)
	unreadable = sorted(names & UNREADABLE_NAMES)
	if unreadable:
		return _("\"{0}\" uses {1}, which Python does not know. Write True, False or None.").format(text, unreadable[0])
	for step in before:
		if _tag(step) == "userTask":
			return _user_task_gap(text, tree, names - fields - ENGINE_NAMES, step)
		if _tag(step) == "scriptTask":
			return _script_task_gap(text, names, step, fields, keys.get(step.get("id")))
	unknown = sorted(names - produced)
	if unknown:
		return _("'{0}' is not set by any step, the start event or a document field, so \"{1}\" never routes.").format(unknown[0], text)
	return ""


def _user_task_gap(text: str, tree, names: set, step) -> str:
	"""Why a condition after a user task does not test one of its actions, or ""."""
	actions = _task_actions(step)
	label = step.get("name") or step.get("id")
	if not actions:
		return _("{0} has no actions, so action is never set and \"{1}\" never routes. Add the actions on {0}.").format(label, text)
	if not names:
		return ""
	if "action" not in names:
		return _("\"{0}\" does not test the action taken on {1}. Test action == one of: {2}.").format(text, label, ", ".join(actions))
	compared = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
	wrong = [value for value in compared if value not in actions]
	if wrong:
		return _("'{0}' is not an action of {1}. Its actions: {2}.").format(wrong[0], label, ", ".join(actions))
	return ""


def _script_task_gap(text: str, names: set, step, fields: frozenset, keys: set | None) -> str:
	"""Why a condition after a script task tests a key its script does not set, or ""."""
	missing = sorted(names - (keys or set()) - fields - ENGINE_NAMES)
	if not missing:
		return ""
	label = step.get("name") or step.get("id")
	wanted = ", ".join(f'result["{key}"]' for key in missing)
	if keys is None:
		return _("{0} has no script yet. Its script must set {1} for \"{2}\" to route.").format(label, wanted, text)
	return _("The script of {0} never sets {1}, so \"{2}\" never routes.").format(label, wanted, text)


def _unrouted_checks(elements: dict, flows: list) -> list:
	"""(id, why) for each check script task with no gateway right after it."""
	gaps = []
	for el in elements.values():
		if _tag(el) != "scriptTask":
			continue
		if not CHECK_STEP.search(el.get("name") or ""):
			continue
		after = [elements[f.get("targetRef")] for f in flows if f.get("sourceRef") == el.get("id") and f.get("targetRef") in elements]
		if not any(_tag(a) == "exclusiveGateway" for a in after):
			gaps.append((el.get("id"), _("It is a check, but no decision follows it, so its result is never used. Route on its result with a gateway.")))
	return gaps


def _task_actions(step) -> list:
	"""The action names on a user task element."""
	from processa.ai_agent_registry.provisioning.bpmn_task_config import normalise_task_actions

	raw = normalise_task_actions(step.get(f"{{{SPIFF_NS}}}taskActions"))
	return [row["action"] for row in json.loads(raw)] if raw else []


def _script_keys(step) -> set | None:
	"""Names a script task's script puts in task data; None when it has no script. Raises SyntaxError when it does not parse."""
	server_script = (step.get(f"{{{SPIFF_NS}}}serverScript") or "").strip()
	if server_script:
		code = frappe.db.get_value("Server Script", server_script, "script")
		return None if code is None else _assigned_keys(code, inline=False)
	inline = step.find(f"{{{BPMN_NS}}}script")
	if inline is not None and (inline.text or "").strip():
		return _assigned_keys(inline.text, inline=True)
	return None


def _assigned_keys(code: str, inline: bool) -> set:
	"""result["key"] writes, result.update keys and result = {...} keys; an inline script's assigned names too."""
	keys = set()
	for node in ast.walk(ast.parse(code)):
		if isinstance(node, ast.Subscript) and _is_result(node.value) and isinstance(node.slice, ast.Constant):
			keys.add(str(node.slice.value))
		elif isinstance(node, ast.Call) and _is_result_update(node):
			keys |= {k.arg for k in node.keywords if k.arg}
			keys |= {k.value for arg in node.args if isinstance(arg, ast.Dict) for k in arg.keys if isinstance(k, ast.Constant)}
		elif isinstance(node, ast.Assign) and any(_is_result(t) for t in node.targets) and isinstance(node.value, ast.Dict):
			keys |= {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
		elif inline and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
			keys.add(node.id)
	return keys


def _is_result_update(node) -> bool:
	return isinstance(node.func, ast.Attribute) and node.func.attr == "update" and _is_result(node.func.value)


def _is_result(node) -> bool:
	return isinstance(node, ast.Name) and node.id == "result"


def _document_fields(doctypes: set) -> frozenset:
	"""Field names of the DocTypes that exist on this site, as a condition reads them."""
	fields = set()
	for doctype in doctypes:
		if frappe.db.exists("DocType", doctype):
			fields |= {f.fieldname for f in frappe.get_meta(doctype).fields}
	return frozenset(fields)


def _tag(el) -> str:
	return el.tag.split("}")[-1]
