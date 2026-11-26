"""ProsAlly keeps and describes the configuration on diagram elements across a redraw."""

import json
import re
from xml.etree import ElementTree as ET

from frappe import _

from processa.ai_agent_registry.definitions.prosally.helpers import NS, register_namespaces

EXTENSION_NS_URIS = (
	"{http://spiffworkflow.org/bpmn/schema/1.0/core}",
	"{http://custom/text-style}",
	"{http://camunda.org/schema/1.0/bpmn}",
)
ATTR_FAMILY_LABELS = {
	"serverScript": "Server Script",
	"assignmentMode": "Assignment Mode",
	"assigneeDocField": "Assignee (Doc Field)",
	"roundRobinRole": "Round Robin Role",
	"loadBalancingRole": "Load Balancing Role",
	"leaveRelieverEnabled": "Leave Reliever",
	"triggerType": "Trigger Type",
	"triggerDoctype": "Trigger DocType",
	"serviceType": "Service Type",
	"serviceTargetDoctype": "Target DocType",
	"workflowState": "Workflow State",
	"docStatus": "Doc Status",
	"emailSubject": "Email Subject",
	"emailTo": "Email To",
	"emailBody": "Email Body",
	"emailAccount": "Email Account",
	"gchatMessage": "Google Chat Message",
	"gchatSpaceId": "Google Chat Space",
	"pushTitle": "Push Notification Title",
	"pushMessage": "Push Notification Message",
	"updateFieldDoctype": "Update Field DocType",
	"updateFieldName": "Update Field Name",
	"updateFieldValue": "Update Field Value",
	"calledDecisionId": "Decision Table",
	"notificationName": "Notification",
	"fontFamily": "Font Family",
	"fontSize": "Font Size",
	"fontWeight": "Font Weight",
	"fontStyle": "Font Style",
	"textColor": "Text Color",
	"textDecoration": "Text Decoration",
	"assignee": "Assignee",
	"candidateGroups": "Candidate Groups",
	"candidateUsers": "Candidate Users",
	"formKey": "Form Key",
	"dueDate": "Due Date",
	"followUpDate": "Follow-Up Date",
	"priority": "Priority",
	"asyncBefore": "Async Before",
	"asyncAfter": "Async After",
}


def extract_configured_elements(xml: str) -> dict:
	"""Every BPMN element carrying extension attributes, extension elements or documentation, by id."""
	if not xml or not xml.strip():
		return {}
	register_namespaces()
	root = ET.fromstring(xml)
	configured = {}
	for elem in root.iter():
		tag = elem.tag
		if any(ns in tag for ns in (NS["bpmndi"], NS["dc"], NS["di"])):
			continue
		elem_id = elem.get("id")
		if not elem_id:
			continue
		ext_attrs = {name: value for name, value in elem.attrib.items() if _is_extension_attr(name)}
		ext_elements_xml = None
		ext_el = elem.find("{" + NS["bpmn"] + "}extensionElements")
		if ext_el is not None and len(ext_el) > 0:
			ext_elements_xml = ET.tostring(ext_el, encoding="unicode")
		documentation = _get_documentation_text(elem)
		if ext_attrs or ext_elements_xml or documentation:
			configured[elem_id] = {
				"name": elem.get("name", elem_id),
				"type": _element_type_label(tag),
				"attrs": ext_attrs,
				"extension_elements_xml": ext_elements_xml,
				"documentation": documentation,
			}
	return configured


def _condition_text(xml: str, previous_xml: str) -> str:
	"""The gateway conditions and check steps in xml that cannot route as drawn, leaving out any previous_xml had."""
	from processa.processa_engine.compiler.deploy_warnings import gateway_condition_gaps

	if not (xml or "").strip():
		return ""
	root = ET.fromstring(xml.strip().encode("utf-8"))
	before = set(gateway_condition_gaps(ET.fromstring(previous_xml.strip().encode("utf-8")))) if (previous_xml or "").strip() else set()
	names = {el.get("id"): el.get("name") for el in root.iter() if el.get("id")}
	lines = [
		_("{0}: {1}").format(names.get(elem_id) or elem_id, message)
		for elem_id, message in gateway_condition_gaps(root)
		if (elem_id, message) not in before
	]
	if not lines:
		return ""
	return "\n\n" + _("These decisions need your attention:") + "\n" + "\n".join("- " + line for line in lines)


def _script_task_names(xml: str) -> dict:
	"""{id: name} of the Script Tasks in xml."""
	from processa.ai_agent_registry.definitions.prosally.tools_pipeline import element_names

	return {elem_id: name or elem_id for elem_id, (kind, name) in element_names(xml).items() if kind == "scriptTask"}


def _service_task_sentence(name: str, config: dict) -> str:
	service = config.get("serviceType")
	if service == "apply_workflow":
		return _("{0} moves the {1} to {2}.").format(
			name, config.get("serviceTargetDoctype") or _("document"), config.get("workflowState") or _("its next state")
		)
	if service == "send_email":
		return _("{0} sends an email.").format(name)
	if service == "update_field":
		return _("{0} updates a field on the {1}.").format(name, config.get("updateFieldDoctype") or _("document"))
	if service == "google_chat":
		return _("{0} sends a Google Chat message.").format(name)
	if service == "push_notification":
		return _("{0} sends a push notification.").format(name)
	if service == "connector":
		return _("{0} runs the {1} connector.").format(name, config.get("connectorId") or "")
	return ""


def _user_task_sentence(name: str, config: dict) -> str:
	parts = []
	if config.get("targetDoctype"):
		parts.append(_("works on the {0}").format(config["targetDoctype"]))
	mode = config.get("assigneeMode")
	if mode == "User" and config.get("assigneeUser"):
		parts.append(_("is assigned to {0}").format(config["assigneeUser"]))
	elif mode == "DocField" and config.get("assigneeDocfield"):
		parts.append(_("is assigned to the person in the {0} field").format(config["assigneeDocfield"]))
	elif mode == "Table Field" and config.get("assigneeTableField"):
		parts.append(_("is assigned to the people in the {0} table").format(config["assigneeTableField"]))
	elif mode == "Round Robin":
		parts.append(_("is assigned by round robin"))
	elif mode == "Load Balancing":
		parts.append(_("is assigned by load balancing"))
	elif mode:
		parts.append(_("has no one chosen to do it yet"))
	actions = config.get("taskActions") or []
	if isinstance(actions, str):
		actions = json.loads(actions)
	actions = [a.get("action") if isinstance(a, dict) else a for a in actions]
	actions = [str(a) for a in actions if a]
	if actions:
		parts.append(_("has the buttons {0}").format(", ".join(actions)))
	if not parts:
		return ""
	return _("{0} {1}.").format(name, ", ".join(parts))


def _is_extension_attr(attr_name: str) -> bool:
	return any(attr_name.startswith(uri) for uri in EXTENSION_NS_URIS)


def _attr_label(clark_name: str) -> str:
	local = clark_name.split("}", 1)[1] if "}" in clark_name else clark_name
	return _(ATTR_FAMILY_LABELS.get(local, local))


def _local_name(clark_name: str) -> str:
	return clark_name.split("}", 1)[1] if "}" in clark_name else clark_name


def _element_type_label(tag: str) -> str:
	local = tag.split("}", 1)[-1] if "}" in tag else tag
	return re.sub(r"([a-z])([A-Z])", r"\1 \2", local).title()


def _get_documentation_text(elem):
	doc_el = elem.find("{" + NS["bpmn"] + "}documentation")
	if doc_el is not None and doc_el.text:
		return doc_el.text.strip()
	return None


def _set_documentation(elem, text: str) -> None:
	doc_tag = "{" + NS["bpmn"] + "}documentation"
	doc_el = elem.find(doc_tag)
	if doc_el is not None:
		if not (doc_el.text or "").strip():
			doc_el.text = text
	else:
		doc_el = ET.Element(doc_tag)
		doc_el.text = text
		elem.insert(0, doc_el)
