# ProsAlly reply, lint and prompt helpers: confirmation text, change summaries, lint replies and stage limits.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _diagram_replies():
	return ("BPMN_MODIFIED", "BPMN_GENERATED")


def _request_stopwords():
	return frozenset(
		(
			"create",
			"sub",
			"process",
			"subprocess",
			"step",
			"steps",
			"with",
			"that",
			"this",
			"from",
			"into",
			"inside",
			"when",
			"then",
			"should",
		)
	)


def _dms_sources_limit():
	return 4


def _other_maps():
	import re

	return re.compile(
		r"\b(?:cross[- ]process|related (?:process|map)|other (?:process|maps?)|across (?:\w+ ){0,2}(?:process|maps?)|dependenc)",
		re.I,
	)


def _link_words():
	import re

	return re.compile(
		r"\b(?:signals?|messages?|call activit|catch(?:es)?|throws?|senders?|hand-?offs?)", re.I
	)


def _draw_words():
	import re

	return re.compile(r"\b(?:add|draw|create|insert|generate|build|modify|redraw)\b", re.I)


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


def _min_stage_tokens():
	return 16384


def _max_confirmation_steps():
	return 8


def _max_confirmation_settings():
	return 6


def _element_words():
	return {
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


def _no_element_kinds():
	return {
		"script task": ("scriptTask",),
		"service task": ("serviceTask",),
		"user task": ("userTask",),
		"gateway": ("exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway"),
		"decision": ("exclusiveGateway", "inclusiveGateway", "eventBasedGateway"),
		"lane": ("lane",),
		"timer": ("timerEventDefinition",),
		"sub-process": ("subProcess",),
	}


def _rule_out():
	return r"\b(?:no|without|avoid|never (?:use|add)|do not (?:use|add)|don'?t (?:use|add))\s+(?:any\s+|new\s+|extra\s+)?"


def _only_what_is_named():
	import re

	return re.compile(
		r"\b(?:do not|don'?t|never)\s+(?:change|touch|modify|move|alter)\s+(?:anything|any other|the rest|other)"
		r"|\bnothing else\b|\bleave (?:the rest|everything else)\b|\bonly (?:change|edit|update|rename|add|remove)\b",
		re.I,
	)


def _asks_for_a_gateway():
	import re

	return re.compile(
		r"\b(?:gateway|decision|condition|split|join|merge|parallel|branch|if|whether|either|otherwise)\b",
		re.I,
	)


def _crossing_note():
	return "One crossing line is unavoidable"


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


def _call_activity_conversion():
	import re

	return re.compile(
		r"\b(?:as|into|to)\s+(?:a\s+|an\s+)?call[\s-]?activit|\b(?:make|turn|convert|change)\b[^.:]{0,80}\bcall[\s-]?activit",
		re.I,
	)


def document_sources_line(documents: list, lead: str) -> str:
	"""A line naming up to _dms_sources_limit() distinct documents by code, title and type."""
	named = []
	for d in documents:
		label = (
			" - ".join(filter(None, (d.get("document_code"), d.get("title"))))
			+ f" ({d.get('document_type')})"
		)
		if label not in named:
			named.append(label)
	return f"{lead}: " + "; ".join(named[: _dms_sources_limit()])


def add_document_sources(text: str, intent: str | None, turn: dict | None) -> str:
	"""A drawn or changed diagram's reply with the documents the DMS search found named under it."""
	documents = (turn or {}).get("dms_documents") or []
	if intent not in _diagram_replies() or not documents:
		return text
	return text.rstrip() + "\n\n" + document_sources_line(documents, frappe._("Documents checked"))


def pending_confirmation(conversation: str) -> str:
	"""The action_intent the last Bot message asks the user to confirm; "" when that message is not a confirmation card."""
	last = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata"],
		order_by="creation desc",
		limit=1,
	)
	meta = frappe.parse_json(last[0].metadata or "{}") if last else {}
	action = (meta.get("agent_result") or {}).get("action_intent")
	if meta.get("intent") != "CONFIRM" or not action:
		return ""
	return action


def quoted(name: str) -> str:
	return '"' + name + '"'


def asks_for_links_review(text: str) -> bool:
	"""True when the message asks about links to other process maps and does not ask to draw or change steps."""
	text = text or ""
	return bool(_other_maps().search(text) and _link_words().search(text) and not _draw_words().search(text))


def lint_prompt(findings: dict) -> str:
	"""The findings to fix, one per line, under where they sit."""
	where = findings["scope"]["name"] if findings["scope"] else "the main process"
	lines = [
		"- [{}] {} (id {}): {} ({})".format(
			f["category"], quoted(f["name"]), f["id"], f["message"], f["rule"]
		)
		for f in findings["fix"]
	]
	return "In {}:\n{}".format(where, "\n".join(lines))


def lint_leftovers(findings: dict) -> str:
	"""What a lint fix did not touch: findings in other places and findings that need a person."""
	parts = []
	for name, count in findings["elsewhere"]:
		parts.append(
			frappe._("{0} in {1}").format(count, quoted(name) if name else frappe._("the main process"))
		)
	if findings["left"]:
		parts.append(frappe._("{0} that need a person to fix").format(len(findings["left"])))
	if not parts:
		return ""
	return "\n\n" + frappe._("Not fixed: {0}. Ask me again from there, or fix them in the editor.").format(
		", ".join(parts)
	)


def lint_unfixed_reply(where: str, findings: dict) -> str:
	"""The answer when a lint fix changed nothing: how many findings stayed and which rules they break."""
	count = len(findings["fix"])
	rules = ", ".join(sorted({f["rule"] for f in findings["fix"]}))
	return frappe._(
		"I did not change {0}. I could not fix the {1} lint findings it has ({2}) by editing the steps and paths. "
		"Fix them in the editor, or tell me which steps to connect or add."
	).format(where, count, rules)


def no_lint_fix_reply(findings: dict | None) -> str:
	"""The answer to a request to fix lint findings when there is nothing ProsAlly can change."""
	if not findings:
		return frappe._(
			"The editor shows no lint findings to fix. If you expect some, open the lint panel and ask again."
		)
	lines = "\n".join("- {}: {}".format(quoted(f["name"]), f["message"]) for f in findings["left"])
	return frappe._(
		"None of these findings can be fixed by changing the steps and paths, so they need a person in the editor:"
	) + ("\n" + lines)


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


def stage_max_tokens(cfg: dict) -> int:
	"""Output budget for a full IR: at least _min_stage_tokens(), at most what the model allows."""
	max_tokens = max(int(cfg.get("max_tokens") or 0), _min_stage_tokens())
	ceiling = 0
	if cfg.get("ai_model"):
		ceiling = frappe.db.get_value("AI Model", cfg.get("ai_model"), "max_output_tokens") or 0
	if ceiling:
		max_tokens = min(max_tokens, int(ceiling))
	return max_tokens


def join_confirmation(summary: str | dict, question: str) -> str:
	"""The summary then the question as its own paragraph, without a closing summary sentence that repeats the question.

	A summary given as {"intro", "steps", "settings"} is laid out as a paragraph and two one-per-line lists."""
	import re

	if isinstance(summary, dict):
		summary = _confirmation_text(summary)
	summary = (summary or "").strip()
	question = (question or "").strip()
	last = re.search(r"[^.!?\n]*[.!?]?\s*$", summary)
	if question and _comparable(last.group(0)) == _comparable(question):
		summary = summary[: last.start()].rstrip()
	return (summary + "\n\n" + question) if summary else question


def _confirmation_text(parts: dict) -> str:
	"""The intro, the steps understood and the settings planned, each list one item per line."""
	steps = [str(step).strip() for step in parts.get("steps") or [] if str(step).strip()]
	settings = [str(setting).strip() for setting in parts.get("settings") or [] if str(setting).strip()]
	blocks = [str(parts.get("intro") or "").strip()]
	if steps:
		blocks.append(
			frappe._("Here's what I understood:") + "\n" + _capped_lines(steps, _max_confirmation_steps())
		)
	if settings:
		blocks.append(
			frappe._("I'll also set these up on the steps:")
			+ "\n"
			+ _capped_lines(settings, _max_confirmation_settings())
		)
		blocks.append(
			frappe._('Reply "draw only" if you\'d rather I draw just the steps, without these settings.')
		)
	return "\n\n".join(block for block in blocks if block)


def _capped_lines(items: list, limit: int) -> str:
	"""The first limit items one per line, then a line saying how many more were not listed."""
	lines = ["- " + item for item in items[:limit]]
	if len(items) > limit:
		lines.append(frappe._("and {0} more not listed here").format(len(items) - limit))
	return "\n".join(lines)


def _comparable(text: str) -> str:
	import re

	return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def format_removal_warning(removed_elements: list) -> str:
	"""The message asking the user to confirm a change that drops configured shapes."""
	lines = [
		frappe._(
			"I've prepared the changes, but the following configured shapes will be removed and their settings will be lost:\n"
		)
	]
	for elem in removed_elements:
		line = frappe._("• **{0}** ({1})").format(elem["name"], elem["type"])
		configs = elem["configs"]
		if configs:
			detail = list(configs[:3])
			if len(configs) > 3:
				detail.append(frappe._("and {0} more").format(len(configs) - 3))
			line = line + " - " + ", ".join(detail)
		lines.append(line)
	lines.append(
		frappe._(
			"\nThese configurations (scripts, assignments, triggers, documentation, etc.) cannot be recovered after applying the changes.\n\nShall I apply the changes anyway?"
		)
	)
	return "\n".join(lines)


def describe_changes(previous_xml: str, xml: str) -> str:
	"""What a modify added, removed and renamed on the diagram, as plain lines; says so when nothing changed."""
	from collections import Counter

	before = element_names(previous_xml)
	after = element_names(xml)
	lines = []
	for elem_id, (kind, name) in after.items():
		if kind == "sequenceFlow":
			continue
		if elem_id not in before:
			lines.append(frappe._("Added {0}.").format(_element_label(kind, name)))
			continue
		old_name = before[elem_id][1]
		if name and old_name and name != old_name:
			lines.append(frappe._("Renamed {0} to {1}.").format(_element_label(kind, old_name), quoted(name)))
	for elem_id, (kind, name) in before.items():
		if kind != "sequenceFlow" and elem_id not in after:
			lines.append(frappe._("Removed {0}.").format(_element_label(kind, name)))
	# Paths are compared by label, since a modify may give an unchanged path a new id.
	old_paths = Counter(name for kind, name in before.values() if kind == "sequenceFlow" and name)
	new_paths = Counter(name for kind, name in after.values() if kind == "sequenceFlow" and name)
	for name in (new_paths - old_paths).elements():
		lines.append(frappe._("Added {0}.").format(_element_label("sequenceFlow", name)))
	for name in (old_paths - new_paths).elements():
		lines.append(frappe._("Removed {0}.").format(_element_label("sequenceFlow", name)))
	lines += _moved_arrows(previous_xml, xml)
	lines += _changed_kinds(before, after)
	lines += _lane_lines(previous_xml, xml)
	lines += _config_lines(previous_xml, xml)
	if not lines:
		return "\n\n" + frappe._(
			"I could not find any change on the diagram. Check that your request was applied."
		)
	return "\n\n" + frappe._("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def _changed_kinds(before: dict, after: dict) -> list[str]:
	"""Steps present before and after whose element type changed, as plain lines."""
	return [
		frappe._("Changed {0} to {1}.").format(
			_element_label(kind, name), _element_words().get(after[elem_id][0], "another kind of element")
		)
		for elem_id, (kind, name) in before.items()
		if elem_id in after and kind != "sequenceFlow" and after[elem_id][0] != kind
	]


def _lanes(xml: str) -> dict:
	"""{lane name: set of step ids} in diagram order; empty when the diagram has no lanes."""
	import re

	lanes = {}
	for attrs, body in re.findall(r"<bpmn:lane\s([^>]*)>(.*?)</bpmn:lane>", xml or "", re.S):
		values = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
		lanes[values.get("name") or values.get("id")] = set(
			re.findall(r"<bpmn:flowNodeRef>([^<]+)</bpmn:flowNodeRef>", body)
		)
	return lanes


def _lane_lines(previous_xml: str, xml: str) -> list[str]:
	"""Lanes added, removed, reordered and steps moved between lanes, as plain lines."""
	old, new = _lanes(previous_xml), _lanes(xml)
	lines = [frappe._("Added the lane {0}.").format(quoted(name)) for name in new if name not in old]
	lines += [frappe._("Removed the lane {0}.").format(quoted(name)) for name in old if name not in new]
	kept_old = [name for name in old if name in new]
	kept_new = [name for name in new if name in old]
	if kept_old != kept_new:
		lines.append(frappe._("Reordered the lanes: {0}.").format(", ".join(new)))
	names = {elem_id: name for elem_id, (_kind, name) in element_names(xml).items()}
	for lane in kept_new:
		for elem_id in sorted(new[lane] - old[lane]):
			home = next((other for other in old if elem_id in old[other]), None)
			if home and elem_id in names:
				lines.append(
					frappe._("Moved {0} from the lane {1} to {2}.").format(
						quoted(names[elem_id]), quoted(home), quoted(lane)
					)
				)
	return lines


def _settings(xml: str) -> dict:
	"""{element id: its prefixed attributes such as spiffworkflow:workflowState} for elements that have any."""
	import html
	import re

	found = {}
	for attrs in re.findall(r"<bpmn:\w+\s([^>]*?)/?>", xml or ""):
		values = dict(re.findall(r'([\w.-]+:[\w.-]+)="([^"]*)"', attrs))
		values = {key: html.unescape(val) for key, val in values.items() if not key.startswith("xmlns")}
		elem_id = re.search(r'\bid="([^"]+)"', attrs)
		if values and elem_id:
			found[elem_id.group(1)] = values
	return found


def _config_lines(previous_xml: str, xml: str) -> list[str]:
	"""Steps present before and after whose settings changed, as plain lines."""
	before, names = _settings(previous_xml), element_names(xml)
	return [
		frappe._("Changed the settings of {0}.").format(quoted(names[elem_id][1] or elem_id))
		for elem_id, values in _settings(xml).items()
		if elem_id in before and before[elem_id] != values and elem_id in names
	]


def _moved_arrows(previous_xml: str, xml: str) -> list[str]:
	"""Arrows between steps that exist before and after whose source or target changed, as plain lines."""
	import re
	from collections import Counter

	old_names = {i: name for i, (kind, name) in element_names(previous_xml).items() if kind != "sequenceFlow"}
	new_names = {i: name for i, (kind, name) in element_names(xml).items() if kind != "sequenceFlow"}

	def arrows(text):
		found = Counter()
		for attrs in re.findall(r"<bpmn:sequenceFlow\s([^>]*?)/?>", text or ""):
			values = {key: val for key, val in re.findall(r'(\w+)="([^"]*)"', attrs)}
			found[(values.get("sourceRef"), values.get("targetRef"), values.get("name", ""))] += 1
		return found

	gone = list((arrows(previous_xml) - arrows(xml)).elements())
	lines = []
	for source, target, label in (arrows(xml) - arrows(previous_xml)).elements():
		if source not in old_names or target not in old_names:
			continue
		match = next(
			(
				old
				for old in gone
				if old[2] == label
				and (old[0] == source) != (old[1] == target)
				and old[0] in new_names
				and old[1] in new_names
			),
			None,
		)
		if match:
			gone.remove(match)
			lines.append(
				frappe._("Moved the arrow from {0} to {1}.").format(
					quoted(new_names[source] or source), quoted(new_names[target] or target)
				)
			)
	return lines


def request_constraints(text: str) -> dict:
	"""The constraints a request sets: the element kinds it rules out, and whether only what it names may change."""
	import re

	ruled_out = [
		kind
		for kind in _no_element_kinds()
		if re.search(_rule_out() + kind.replace("-", "[- ]?") + r"s?\b", text or "", re.I)
	]
	return {"ruled_out": ruled_out, "only_what_is_named": bool(_only_what_is_named().search(text or ""))}


def constraint_prompt(constraints: dict) -> str:
	"""The constraints as lines for the step that draws the change; "" when the request sets none."""
	lines = [f"Do not add any {kind}." for kind in constraints["ruled_out"]]
	if constraints["only_what_is_named"]:
		lines.append(
			"Change only what the request names. Every other step, arrow, lane and setting stays exactly as it is."
		)
	if not lines:
		return ""
	return "Constraints from the request; the result is checked against them:\n- " + "\n- ".join(lines)


def unrequested_changes(previous_xml: str, xml: str, text: str, constraints: dict) -> list[str]:
	"""Each way xml breaks a constraint of the request, or adds what the request did not ask for, in plain words."""
	problems = [
		frappe._("The request says no {0}, and the change adds one.").format(kind)
		for kind in constraints["ruled_out"]
		if sum(_count(xml, tag) for tag in _no_element_kinds()[kind])
		> sum(_count(previous_xml, tag) for tag in _no_element_kinds()[kind])
	]
	before, after = element_names(previous_xml), element_names(xml)
	for elem_id, (kind, name) in after.items():
		if elem_id in before or kind == "sequenceFlow":
			continue
		gateway_not_asked = kind.endswith("Gateway") and not _asks_for_a_gateway().search(text or "")
		element_not_asked = not kind.endswith("Gateway") and bool(name) and not _named_in(name, text)
		if gateway_not_asked or element_not_asked:
			problems.append(
				frappe._("The change adds {0}, which the request did not ask for.").format(
					_element_label(kind, name)
				)
			)
	if constraints["only_what_is_named"]:
		problems += _changed_but_not_named(previous_xml, xml, text)
	return problems


def _changed_but_not_named(previous_xml: str, xml: str, text: str) -> list[str]:
	"""Elements removed, renamed, retyped or reconfigured although the request names none of them."""
	before, after = element_names(previous_xml), element_names(xml)
	old_settings, new_settings = _settings(previous_xml), _settings(xml)
	problems = []
	for elem_id, (kind, name) in before.items():
		if kind == "sequenceFlow" or _named_in(name, text):
			continue
		changed = elem_id not in after or after[elem_id] != (kind, name)
		changed = changed or old_settings.get(elem_id) != new_settings.get(elem_id)
		if changed:
			problems.append(
				frappe._("The request says to change nothing else, and the change also alters {0}.").format(
					_element_label(kind, name)
				)
			)
	return problems


def _named_in(name: str, text: str) -> bool:
	"""True when a significant word of name appears in text, matched on its first five letters."""
	import re

	asked = {word[:5] for word in re.findall(r"[a-z]{4,}", (text or "").lower())}
	words = [
		word[:5]
		for word in re.findall(r"[a-z]{4,}", (name or "").lower())
		if word not in _request_stopwords()
	]
	return bool(words) and any(word in asked for word in words)


def _count(xml: str, tag: str) -> int:
	import re

	return len(re.findall(r"<(?:\w+:)?" + tag + r"\b", xml or ""))


def no_change_reply(where: str, similar: list[str]) -> str:
	"""The answer when a modify changed nothing: what already covers the request and what to say next."""
	if not similar:
		return frappe._(
			"I did not change {0}. Tell me which step to add or change, and where it goes."
		).format(where)
	label = frappe._("the step") if len(similar) == 1 else frappe._("the steps")
	return frappe._(
		"I did not change {0}. It already has {1} {2}. Tell me what else to add or change, and where it goes."
	).format(where, label, ", ".join(quoted(name) for name in similar))


def _element_label(kind: str, name: str) -> str:
	return _element_words().get(kind, "the element") + (" " + quoted(name) if name else "")


def crossing_line_note(nodes: list, topology: dict, conversation: str | None) -> str:
	"""The note that one crossing stays, naming the steps on it, said once per conversation."""
	if topology.get("planar") is not False:
		return ""
	said = {"conversation": conversation, "message_type": "Bot", "text": ["like", f"%{_crossing_note()}%"]}
	if conversation and frappe.db.exists("Chat Message", said):
		return ""
	names = {n.get("id"): n.get("name") or n.get("id") for n in nodes}
	who = ", ".join(names.get(x, x) for x in (topology.get("obstruction") or [])[:5])
	return " " + frappe._("{0}: the paths through {1} cannot all be laid flat.").format(
		frappe._(_crossing_note()), who
	)


def layout_asks(text: str) -> list[str]:
	"""Which layout asks text makes: spacing, alignment, crossings, convergence."""
	return [ask for ask, pattern in _layout_asks() if pattern.search(text)]


def asks_to_make_call_activity(text: str) -> bool:
	"""True when the message asks to show or turn something into a call activity, which runs a separate process."""
	return bool(_call_activity_conversion().search(text or ""))
