# ProsAlly context: the agent's settings and model call, process memory, links, maps, documents and lanes.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _agent_id():
	return "prosally_agent"


def _affirmations():
	return frozenset(
		{
			"yes",
			"y",
			"yeah",
			"yep",
			"yup",
			"sure",
			"ok",
			"okay",
			"alright",
			"all right",
			"go",
			"go ahead",
			"yes go ahead",
			"ok go ahead",
			"okay go ahead",
			"proceed",
			"yes proceed",
			"ok proceed",
			"do it",
			"yes do it",
			"do",
			"just do it",
			"go for it",
			"draw it",
			"yes draw it",
			"confirm",
			"confirmed",
			"yes confirm",
			"sounds good",
			"looks good",
			"yes sounds good",
			"yes looks good",
			"perfect",
			"correct",
			"yes correct",
			"thats right",
			"yes thats right",
			"absolutely",
			"of course",
		}
	)


def _declines():
	return ("no", "nope", "nah", "wait", "change", "not yet", "hold on", "stop", "dont", "do not", "cancel")


def _polite_words():
	import re

	return re.compile(r"\b(please|thanks|thank you)\b")


def _diagram_replies():
	return ("BPMN_MODIFIED", "BPMN_GENERATED")


def _diagram_version_suffix():
	import re

	return re.compile(r"\s+-\s+v\d+\s*$", re.I)


def _memory_notes_limit():
	return 8


def _memory_notes_header():
	return "Notes from earlier work on this process:"


def _memory_notes_provenance():
	return "These were agreed in other conversations; they do not mean the diagram exists."


def _memory_backend():
	return "direct_api"


def _max_related_models():
	return 15


def _max_turn_maps():
	return 3


def _cache_ttl():
	return 3600


def _catching_tags():
	return ("startEvent", "intermediateCatchEvent", "boundaryEvent", "receiveTask")


def _throwing_tags():
	return ("intermediateThrowEvent", "endEvent", "sendTask")


def _task_tags():
	return ("receiveTask", "sendTask")


def _lint_fix_request():
	import re

	return re.compile(
		r"\b(?:fix|resolve|clear|clean\s*up|correct|repair|solve|sort\s*out)\b[^.:]{0,60}\b(?:lint(?:ing)?|linter|warnings?|errors?|issues?|problems?)\b"
		r"(?!\s+(?:handler|step|task|event|gateway|flow|path|boundary|code))"
		r"|\blint(?:ing)?\b[^.:]{0,40}\b(?:fix|resolve|clear|clean\s*up|correct|repair)",
		re.I,
	)


def _lane_list():
	import re

	return re.compile(r"\blanes\b(?:\s+(?:only|named|called|are))*\s*:?\s*([^.;:\n]+)", re.I)


def _history_turns():
	return 10


def _tools_dms_doctype():
	return "Document Register"


def _document_types():
	return ("Policy", "SOP", "Manual", "Guideline", "Knowledge Base")


def _fields():
	return [
		"name",
		"title",
		"document_code",
		"document_type",
		"current_version",
		"drive_file_link",
		"content",
	]


def _chunk_word_count():
	return 600


def _chunk_overlap():
	return 80


def _keyword_min_share():
	return 0.34


def _max_results():
	return 4


def _tools_process_digest_doctype():
	return "BPMN Process Model"


def _bpmn_ns():
	return "http://www.omg.org/spec/BPMN/20100524/MODEL"


def _search_fields():
	return ("title", "process_id", "process_name", "description")


def _candidate_limit():
	return 50


def _max_models():
	return 8


def _max_digest_chars():
	return 8000


def _max_doc_chars():
	return 300


def _step_tags():
	return (
		"startEvent",
		"endEvent",
		"task",
		"userTask",
		"serviceTask",
		"scriptTask",
		"manualTask",
		"sendTask",
		"receiveTask",
		"businessRuleTask",
		"subProcess",
		"adHocSubProcess",
		"callActivity",
		"intermediateCatchEvent",
		"intermediateThrowEvent",
		"boundaryEvent",
	)


def _event_definitions():
	return {
		"messageEventDefinition": ("message", "messageRef"),
		"signalEventDefinition": ("signal", "signalRef"),
	}


def _gateway_tags():
	return ("exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway")


def prosally_config() -> dict:
	"""ProsAlly's resolved agent configuration."""
	from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import (
		get_agent_config,
	)

	cfg = get_agent_config(_agent_id()) or {}
	cfg.setdefault("agent_id", _agent_id())
	return cfg


def complete_sub_prompt(
	cfg: dict, sub_id: str, user: str, system: str | None = None, max_tokens=None, files: list | None = None
) -> str:
	"""One model call with a sub-prompt as the system prompt, returning the reply text.

	files are the turn's attachments: images go with the prompt, text files are added to it."""
	from processa.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings
	from processa.processa_engine.agent_runtime.turn_state import run_sync
	from processa.processa_engine.dispatch.attachments import with_attachments

	stage = (cfg.get("sub_prompts") or {}).get(sub_id) or {}
	if system is None:
		system = stage.get("prompt") or ""
	kwargs = {"system": system, **with_attachments(user, files)}
	if max_tokens:
		kwargs["max_tokens"] = max_tokens
	stage_cfg = {
		**cfg,
		"effort": stage.get("effort") or cfg.get("effort"),
		"stage": f"{cfg.get('name') or _agent_id()} / {sub_id}",
	}
	return run_sync(get_llm_adapter_from_settings(stage_cfg).complete(**kwargs)).text


def process_for_diagram(diagram_name: str, process_name: str = "") -> str:
	"""The Process the diagram names (version removed), else the one process_name names; "" when neither exists."""
	for candidate in (_diagram_version_suffix().sub("", diagram_name or ""), process_name or ""):
		name = candidate.strip()
		if name and frappe.db.exists("Process", name):
			return name
	return ""


def _memory_fields(cfg: dict) -> dict:
	"""The memory fields of the agent's configuration record."""
	return (
		frappe.db.get_value(
			"AI Agent Configuration",
			cfg.get("name"),
			[
				"long_term_memory",
				"memory_write_mode",
				"memory_token_budget",
				"memory_distill_model",
				"memory_reconcile_model",
			],
			as_dict=True,
		)
		or {}
	)


def recall_process_memory(diagram_name: str, process_name: str = "") -> dict:
	"""The diagram's Process and the notes recalled for it and the requester, for the turn store."""
	from processa.ai_agent_memory.budget import DEFAULT_MEMORY_TOKEN_BUDGET, bound_memories_to_budget
	from processa.ai_agent_memory.tools import memory_search
	from processa.processa_engine.dispatch.common import cfg_truthy

	fields = _memory_fields(prosally_config())
	if not cfg_truthy(fields.get("long_term_memory")):
		return {"memory_process": "", "memory_notes": []}
	process = process_for_diagram(diagram_name, process_name)
	user = frappe.session.user if frappe.session.user != "Guest" else None
	rows = []
	# An empty query lists the key's newest rows: a confirmation turn's text matches nothing.
	if process:
		key = {"reference_doctype": "Process", "reference_name": process}
		rows += memory_search(
			"Entity", key, "", limit=_memory_notes_limit(), ignore_permissions=True
		)  # notes keyed to the open process
	if user:
		rows += memory_search(
			"User", {"user": user}, "", limit=_memory_notes_limit(), ignore_permissions=True
		)  # notes keyed to the session user
	notes = list(dict.fromkeys((r.get("content") or "").strip() for r in rows))
	budget = fields.get("memory_token_budget") or DEFAULT_MEMORY_TOKEN_BUDGET
	kept = bound_memories_to_budget([{"content": n} for n in notes if n], budget)
	return {"memory_process": process, "memory_notes": [r["content"] for r in kept]}


def memory_notes_block(turn: dict | None) -> str:
	"""The turn's recalled notes under their heading; "" when it has none."""
	notes = (turn or {}).get("memory_notes") or []
	if not notes:
		return ""
	return "\n".join([_memory_notes_header(), _memory_notes_provenance()] + ["- " + n for n in notes])


def queue_process_memory(turn: dict, agent_result: dict | None) -> None:
	"""Queue distillation of a turn that drew or changed a diagram into its Process's memory."""
	process = (turn or {}).get("memory_process")
	intent = (agent_result or {}).get("intent")
	if intent not in _diagram_replies() or frappe.flags.get("eval_origin"):
		return
	if not process:
		frappe.log_error(title="ProsAlly memory: write skipped", message="The diagram matched no Process.")
		return
	from processa.ai_agent_memory.model_resolution import resolve_memory_model

	cfg = prosally_config()
	own = _memory_fields(cfg)
	if own.get("memory_write_mode") != "distilled":
		frappe.log_error(
			title="ProsAlly memory: write skipped",
			message=f"Memory Write Mode is {own.get('memory_write_mode')!r}, process={process}.",
		)
		return
	distill_model = resolve_memory_model(
		own.get("memory_distill_model"), "default_memory_distill_model", cfg.get("ai_model")
	)
	reconcile_model = resolve_memory_model(
		own.get("memory_reconcile_model"), "default_memory_reconcile_model", cfg.get("ai_model")
	)
	source = "\n\n".join(
		[
			"[User message]\n" + (turn.get("user_text") or "")[:3000],
			"[ProsAlly reply]\n" + (agent_result.get("response") or ""),
			"[Conversation]\n" + format_history(turn.get("chat_history")),
		]
	)
	frappe.log_error(
		title="ProsAlly memory: write queued",
		message=f"process={process} model={distill_model} reconcile_model={reconcile_model}",
	)
	frappe.enqueue(
		"processa.ai_agent_memory.writeback.distill_and_write",
		queue="short",
		now=frappe.flags.in_test,
		agent_output=source,
		agent=_agent_id(),
		scope="Entity",
		scope_key={"reference_doctype": "Process", "reference_name": process},
		provider_name=frappe.db.get_value("AI Model", distill_model, "provider") or cfg.get("ai_provider"),
		backend=_memory_backend(),
		model=distill_model,
		reconcile_model=reconcile_model,
		reconcile_provider=frappe.db.get_value("AI Model", reconcile_model, "provider")
		or cfg.get("ai_provider"),
		source_run=None,
		user=frappe.session.user if frappe.session.user != "Guest" else None,
		exclude_context=memory_notes_block(turn),
	)


def confirmation_reply(text: str) -> str:
	""" "yes" when text is a plain affirmation, "no" when it starts with a decline, else ""."""
	import re

	from processa.ai_agent_memory.text_clean import strip_html

	words = re.sub(r"[^a-z ]", " ", strip_html(text).lower().replace("'", ""))
	words = " ".join(_polite_words().sub(" ", words).split())
	if words in _affirmations():
		return "yes"
	if any(words == d or words.startswith(d + " ") for d in _declines()):
		return "no"
	return ""


def get_process_links(process_model: str) -> dict:
	"""Message and signal throws and catches of one map, with gaps against the related maps the user can read."""
	error = _error_unless_readable(process_model)
	if error:
		return error

	links = links_of(process_model)
	related = related_models(process_model, links)
	shown = list(related.items())[: _max_related_models()]
	others = {name: links_of(name) for name, _reason in shown}
	return {
		"process_model": process_model,
		"catches": links["catches"],
		"throws": links["throws"],
		"calls": links["calls"],
		"related": [{"process_model": name, "reason": reason} for name, reason in shown],
		"truncated": len(related) > len(shown),
		"gaps": find_link_gaps(process_model, links, others),
	}


def process_links_for_turn(conversation: str) -> dict:
	"""The get_process_links tool for the map open in this turn, with its findings kept in the turn store for the stage prompts."""
	from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn

	found = get_process_links(_open_map(get_turn(conversation)))
	if "error" not in found:
		keep = {key: found[key] for key in ("process_model", "related", "gaps", "truncated")}
		update_turn(conversation, process_links=keep)
	return found


def read_process_map_for_turn(conversation: str, process_model: str) -> dict:
	"""The digest of one readable map, or the maps matching the words given; a digest is kept on the turn for the stage prompts."""
	from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn

	if not frappe.db.exists(_tools_process_digest_doctype(), process_model or ""):
		return find_process_models(process_model or "")

	found = get_process_model_digest(process_model)
	kept = [
		row
		for row in get_turn(conversation).get("process_maps") or []
		if row["process_model"] != process_model
	]
	kept.append({"process_model": process_model, "digest": found["digest"]})
	update_turn(conversation, process_maps=kept[-_max_turn_maps() :])
	return found


def _open_map(turn: dict) -> str:
	"""The saved map open in the turn: its diagram name, else the active map of its process."""
	if turn.get("diagram_name"):
		return turn["diagram_name"]
	process = turn.get("process_name")
	return (
		process
		and frappe.db.get_value(_tools_process_digest_doctype(), {"process_name": process, "is_active": 1})
	) or ""


def links_review_output(conversation: str) -> dict:
	"""The reply to a review of the open map's links to related maps, built from get_process_links alone."""
	found = process_links_for_turn(conversation)
	if "error" in found:
		response = found["error"]
	else:
		response = "\n\n".join(_review_paragraphs(found))
	return {"intent": "CLARIFY", "action_intent": None, "response": response, "options": []}


def _review_paragraphs(found: dict) -> list[str]:
	if not (found["catches"] or found["throws"] or found["calls"]):
		return [
			frappe._(
				"This map has no message or signal events and no call activities, so it has no links to other maps."
			)
		]

	if found["related"]:
		related = "\n".join(f"- {row['process_model']} ({row['reason']})" for row in found["related"])
		paragraphs = [frappe._("Related maps I can read:") + "\n\n" + related]
	else:
		paragraphs = [frappe._("No map you can read is linked to this one.")]
	if found["truncated"]:
		paragraphs.append(
			frappe._("There are more related maps than I read. These findings cover the first {0}.").format(
				len(found["related"])
			)
		)

	if found["gaps"]:
		gaps = "\n".join(f"- {gap['label'] or gap['element']}: {gap['message']}" for gap in found["gaps"])
		paragraphs.append(frappe._("What to change:") + "\n\n" + gaps)
	else:
		paragraphs.append(
			frappe._("Every message, signal and call activity in this map matches a map you can read.")
		)
	paragraphs.append(
		frappe._(
			"I read the saved map and the related maps and changed none of them. Make any change in the map it names."
		)
	)
	return paragraphs


def _error_unless_readable(process_model: str) -> dict | None:
	if not process_model:
		return {"error": frappe._("I cannot tell which saved map is open. Save the map, then ask again.")}
	if not frappe.db.exists(_tools_process_digest_doctype(), process_model):
		return {"error": frappe._("No process model named {0}.").format(process_model)}
	frappe.get_doc(_tools_process_digest_doctype(), process_model).check_permission("read")
	return None


def links_of(model_name: str) -> dict:
	"""extract_links of a stored map, cached until the map is modified."""
	modified = frappe.db.get_value(_tools_process_digest_doctype(), model_name, "modified")
	key = f"process_links:{model_name}:{modified}"
	links = frappe.cache.get_value(key, expires=True)
	if links is None:
		links = extract_links(frappe.db.get_value(_tools_process_digest_doctype(), model_name, "bpmn_xml"))
		frappe.cache.set_value(key, links, expires_in_sec=_cache_ttl())
	return links


def extract_links(bpmn_xml: str | None) -> dict:
	"""Message and signal catches and throws, and call activities, of one diagram."""
	links = {"catches": [], "throws": [], "calls": []}
	root = parse_bpmn_xml(bpmn_xml)
	if root is None:
		return links

	names = {
		el.get("id"): (el.get("name") or "").strip()
		for kind in ("message", "signal")
		for el in root.iter(bpmn_tag(kind))
	}
	parents = {child: parent for parent in root.iter() for child in parent}
	for el in root.iter():
		tag = local_name(el.tag)
		if tag in _catching_tags():
			links["catches"].extend(_link_events(el, tag, names, parents))
		elif tag in _throwing_tags():
			links["throws"].extend(_link_events(el, tag, names, parents))
		elif tag == "callActivity":
			links["calls"].append(_call(el, parents))
	return links


def _link_events(el, tag: str, names: dict, parents: dict) -> list[dict]:
	if tag in _task_tags():
		refs = [("message", el.get("messageRef"))]
	else:
		refs = []
		for child in el:
			kind, ref_attr = _event_definitions().get(local_name(child.tag), (None, None))
			if kind:
				refs.append((kind, child.get(ref_attr)))
	return [
		{
			"kind": kind,
			"name": names[ref],
			"element": el.get("id"),
			"label": el.get("name") or el.get("id"),
			"step": tag,
			"multi_instance": _multi_instance(el, parents),
		}
		for kind, ref in refs
		if names.get(ref)
	]


def _call(el, parents: dict) -> dict:
	from processa.processa_engine.compiler.called_processes import CALL_SPIFF_NS

	return {
		"element": el.get("id"),
		"label": el.get("name") or el.get("id"),
		"process": (el.get(f"{{{CALL_SPIFF_NS}}}calledProcess") or "").strip(),
		"called": (el.get("calledElement") or "").strip(),
		"multi_instance": _multi_instance(el, parents),
	}


def _multi_instance(el, parents: dict) -> bool:
	while el is not None:
		if el.find(bpmn_tag("multiInstanceLoopCharacteristics")) is not None:
			return True
		el = parents.get(el)
	return False


def related_models(model_name: str, links: dict) -> dict:
	"""Name of each readable active map tied to this one, with the reason, in relevance order."""
	related = {}
	for found in (
		_same_process(model_name),
		_called_maps(model_name, links),
		_name_sharing(model_name, links),
	):
		for name, reason in found:
			related.setdefault(name, reason)
	return related


def _same_process(model_name: str) -> list[tuple]:
	process = frappe.db.get_value(_tools_process_digest_doctype(), model_name, "process_name")
	if not process:
		return []
	names = frappe.get_list(
		_tools_process_digest_doctype(),
		filters={"process_name": process, "is_active": 1, "name": ["!=", model_name]},
		pluck="name",
		limit_page_length=_max_related_models() + 1,
	)
	return [(name, frappe._("same Process")) for name in names]


def _called_maps(model_name: str, links: dict) -> list[tuple]:
	from processa.processa_engine.compiler.called_processes import called_model

	found = []
	for call in links["calls"]:
		target = called_model(call["process"], call["called"])
		if (
			target
			and target.name != model_name
			and frappe.has_permission(_tools_process_digest_doctype(), "read", doc=target.name)
		):
			found.append((target.name, frappe._("called by {0}").format(call["label"])))
	return found


def _name_sharing(model_name: str, links: dict) -> list[tuple]:
	found = []
	for name in sorted({link["name"] for link in links["catches"] + links["throws"]}):
		rows = frappe.get_list(
			_tools_process_digest_doctype(),
			filters={"is_active": 1, "name": ["!=", model_name], "bpmn_xml": ["like", f"%{name}%"]},
			pluck="name",
			limit_page_length=_max_related_models() + 1,
		)
		found.extend((row, frappe._("uses '{0}'").format(name)) for row in rows)
	return found


def find_link_gaps(model_name: str, links: dict, others: dict) -> list[dict]:
	"""Gaps for the elements of this map, judged against itself and the related maps given."""
	maps = {model_name: links, **others}
	gaps = []
	for catch in links["catches"]:
		if catch["step"] != "startEvent":
			gaps.append(_link_gap(model_name, catch, maps, "throws"))
	for throw in links["throws"]:
		gaps.append(_link_gap(model_name, throw, maps, "catches"))
	gaps.extend(_call_gaps(links["calls"]))
	return [gap for gap in gaps if gap]


def _link_gap(model_name: str, link: dict, maps: dict, other_side: str) -> dict | None:
	holders = _holders(link, maps, other_side)
	if model_name in holders or (holders and link["kind"] == "message"):
		return None

	name = link["name"]
	if holders:
		message = frappe._(
			"Signal '{0}' is only matched in {1}. A signal reaches only catchers in the same process "
			"instance, so it never crosses to another map. Use a message or a call activity instead."
		).format(name, ", ".join(holders))
		return _gap("signal_other_process", link, message)

	near = _near(link, maps, other_side)
	if near:
		message = frappe._(
			"The {0} '{1}' has no exact match. Similar names: {2}. Make the names identical."
		).format(link["kind"], name, ", ".join(near))
		return _gap("name_mismatch", link, message)

	if other_side == "throws":
		message = frappe._(
			"No throw of the {0} '{1}' in the process maps you can read. If something outside the maps "
			"sends it, no change is needed; otherwise add a throw in the map that should send it."
		).format(link["kind"], name)
		return _gap("no_throw", link, message)
	message = frappe._(
		"No catch of the {0} '{1}' in the process maps you can read. Add a catch in the map that "
		"should wait for it."
	).format(link["kind"], name)
	return _gap("no_catch", link, message)


def _holders(link: dict, maps: dict, other_side: str) -> list[str]:
	return [
		model
		for model, links in maps.items()
		if any(entry["kind"] == link["kind"] and entry["name"] == link["name"] for entry in links[other_side])
	]


def _near(link: dict, maps: dict, other_side: str) -> list[str]:
	def squash(text):
		return " ".join(text.lower().split())

	return [
		f"{model}: '{entry['name']}'"
		for model, links in maps.items()
		for entry in links[other_side]
		if entry["kind"] == link["kind"]
		and entry["name"] != link["name"]
		and squash(entry["name"]) == squash(link["name"])
	]


def _call_gaps(calls: list[dict]) -> list[dict]:
	from processa.processa_engine.compiler.called_processes import called_model

	gaps = []
	for call in calls:
		target = called_model(call["process"], call["called"])
		if not target or not target.bpmn_xml:
			message = frappe._("The call activity '{0}' calls a process that has no active map.").format(
				call["label"]
			)
			gaps.append(_gap("call_target_missing", call, message))
		elif not frappe.has_permission(_tools_process_digest_doctype(), "read", doc=target.name):
			message = frappe._("The call activity '{0}' calls a map you cannot read.").format(call["label"])
			gaps.append(_gap("call_target_not_visible", call, message))
	return gaps


def _gap(kind: str, link: dict, message: str) -> dict:
	return {"kind": kind, "element": link["element"], "label": link["label"], "message": message}


def lint_fix_requested(texts: list) -> bool:
	"""True when the newest message that is not a yes or a no asks to fix lint findings."""
	from processa.ai_agent_memory.text_clean import strip_html

	request = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	return bool(_lint_fix_request().search(request))


def search_dms_for_turn(
	conversation: str, query: str, document_type: str | None = None, instance=None
) -> dict:
	"""The search_dms_documents tool: the read-only search, with its excerpts kept in the turn store for the stage prompts."""
	from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn

	found = search_dms_documents(query, document_type, instance=instance)
	kept = get_turn(conversation).get("dms_documents") or []
	update_turn(conversation, dms_documents=kept + [r for r in found.get("results") or [] if r not in kept])
	return found


def describe_lanes(chat_history: list, user_text: str, ir: dict | None) -> str:
	"""The lanes drawn, and any lane the person named that is not among them; "" when no lanes were drawn."""
	import copy

	drawn = [lane.get("name") for lane in (ir or {}).get("lanes") or [] if lane.get("name")]
	if not drawn:
		return ""
	text = "\n\n" + frappe._("Lanes drawn:") + "\n" + "\n".join("- " + lane for lane in drawn)
	asked = [e.get("content") or "" for e in chat_history if (e.get("role") or e.get("type")) == "user"]
	missing = [
		lane
		for lane in requested_lanes([*asked, user_text or ""])
		if not any(lane.lower() in d.lower() or d.lower() in lane.lower() for d in drawn)
	]
	if missing:
		text += "\n\n" + frappe._("You also asked for {0}, which I did not draw. Ask me to add it.").format(
			", ".join(missing)
		)
	roles = frappe.get_all("Role", filters={"disabled": 0}, pluck="name")
	hints = [problem["message"] for problem in resolve_ir_lane_roles(copy.deepcopy(ir), roles)]
	if hints:
		text += (
			"\n\n"
			+ "\n".join(hints)
			+ "\n"
			+ frappe._("Select the role in the lane's Lane Role field in the properties panel.")
		)
	return text


def requested_lanes(texts: list) -> list[str]:
	"""The lane names listed after "lanes" in the latest of texts that lists two or more, else []."""
	import re

	from processa.ai_agent_memory.text_clean import strip_html

	for text in reversed(texts):
		for match in _lane_list().finditer(strip_html(text)):
			names = [
				re.sub(r"^the\s+", "", n.strip(), flags=re.I) for n in re.split(r",|\band\b|&", match[1])
			]
			names = [n for n in names if n and n[0].isupper() and len(n.split()) <= 4]
			if len(names) >= 2:
				return names
	return []


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last HISTORY_TURNS messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-_history_turns() :]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def search_dms_documents(query: str, document_type: str | None = None, instance=None) -> dict:
	"""Best matching excerpts from the Active documents the person in the conversation can read."""
	from processa.ai_agent_memory.tools import query_tokens

	if document_type and document_type not in _document_types():
		return {"error": frappe._("document_type must be one of: {0}").format(", ".join(_document_types()))}

	tokens = [_stem(token) for token in query_tokens(query)]
	if not tokens:
		return {"results": []}

	filters = {"lifecycle_state": "Active"}
	if document_type:
		filters["document_type"] = document_type

	# ponytail: reads every readable Active document per query, index them if the register outgrows a few hundred
	user = _chatting_user(instance) or frappe.session.user
	frappe.has_permission(_tools_dms_doctype(), "read", user=user, throw=True)
	documents = [
		document
		for document in frappe.get_all(
			_tools_dms_doctype(), filters=filters, fields=_fields(), limit_page_length=0
		)
		if frappe.has_permission(_tools_dms_doctype(), "read", doc=document.name, user=user)
	]

	hits = []
	for document in documents:
		for chunk in _chunk_words(document.content or ""):
			score = _score(f"{document.title} {chunk}", tokens)
			if score >= _keyword_min_share():
				hits.append((score, document, chunk))
	hits.sort(key=lambda hit: hit[0], reverse=True)

	return {
		"results": [
			{
				"title": document.title,
				"document_code": document.document_code,
				"document_type": document.document_type,
				"version": document.current_version,
				"excerpt": chunk,
				"url": document.drive_file_link,
			}
			for _hit_score, document, chunk in hits[: _max_results()]
		]
	}


def _chatting_user(instance) -> str | None:
	"""The person the conversation belongs to; the agent's own user holds no roles, so reads are checked as this person."""
	if getattr(instance, "context_doctype", "") != "Chat Conversation":
		return None
	return frappe.db.get_value("Chat Conversation", instance.context_docname, "owner")


def _score(text: str, tokens: list) -> float:
	"""Share of the query keywords that appear in the text."""
	text = text.lower()
	return sum(token in text for token in tokens) / len(tokens)


def _stem(token: str) -> str:
	"""Lower-case and drop a plural s, so "fonts" matches "font"."""
	token = token.lower()
	return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _chunk_words(text: str) -> list[str]:
	words = text.split()
	if not words:
		return []
	step = _chunk_word_count() - _chunk_overlap()
	return [
		" ".join(words[start : start + _chunk_word_count()])
		for start in range(0, max(len(words) - _chunk_overlap(), 1), step)
	]


def find_process_models(query: str) -> dict:
	"""Process models the current user can read that match the query, best match first."""
	from processa.ai_agent_memory.tools import query_tokens

	tokens = [token.lower() for token in query_tokens(query)]
	if not tokens:
		return {"error": frappe._("Give at least one keyword to search for.")}

	rows = frappe.get_list(
		_tools_process_digest_doctype(),
		fields=["name", *_search_fields()],
		or_filters=[[field, "like", f"%{token}%"] for field in _search_fields() for token in tokens],
		order_by="modified desc",
		limit_page_length=_candidate_limit(),
	)
	for row in rows:
		haystack = " ".join(str(row[field] or "") for field in _search_fields()).lower()
		row["score"] = sum(token in haystack for token in tokens)
	rows.sort(key=lambda row: row["score"], reverse=True)

	return {
		"results": [
			{
				"process_model": row.name,
				"title": row.title,
				"process": row.process_name,
				"description": frappe.utils.strip_html(row.description or "")[: _max_doc_chars()],
				"kind": _kind(
					parse_bpmn_xml(frappe.db.get_value(_tools_process_digest_doctype(), row.name, "bpmn_xml"))
				),
			}
			for row in rows[: _max_models()]
		]
	}


def get_process_model_digest(process_model: str) -> dict:
	"""Plain-text description of one process model the current user can read."""
	if not frappe.db.exists(_tools_process_digest_doctype(), process_model):
		return {"error": frappe._("No process model named {0}.").format(process_model)}

	model = frappe.get_doc(_tools_process_digest_doctype(), process_model)
	model.check_permission("read")
	root = parse_bpmn_xml(model.bpmn_xml)

	lines = [f"Process model: {model.title}", f"Kind: {_kind(root)}"]
	lines.extend(_process_lines(model.process_name))
	if model.description:
		lines.append(f"Description: {frappe.utils.strip_html(model.description)}")
	lines.extend(_flow_lines(root))

	digest = "\n".join(lines)
	if len(digest) > _max_digest_chars():
		digest = digest[: _max_digest_chars()] + "\n[digest truncated]"
	return {"digest": digest}


def parse_bpmn_xml(bpmn_xml: str | None):
	from xml.etree import ElementTree as ET

	if not (bpmn_xml or "").strip():
		return None
	try:
		return ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except ET.ParseError:
		return None


def _kind(root) -> str:
	"""Executable when any process element carries isExecutable="true", as deploy requires."""
	if root is None:
		return "documented"
	flags = [el.get("isExecutable", "false").strip().lower() for el in root.iter(bpmn_tag("process"))]
	return "executable" if "true" in flags else "documented"


def _process_lines(process_name: str | None) -> list[str]:
	if not process_name:
		return []
	process = frappe.db.get_value("Process", process_name, ["process_owner_name"], as_dict=True)
	if not process:
		return []
	roles = frappe.get_all("Process Role", filters={"parent": process_name}, pluck="role")
	lines = [f"Process: {process_name}"]
	if process.process_owner_name:
		lines.append(f"Process owner: {process.process_owner_name}")
	if roles:
		lines.append(f"Roles: {', '.join(roles)}")
	return lines


def _flow_lines(root) -> list[str]:
	if root is None:
		return ["The diagram is empty or unreadable."]

	names = {el.get("id"): el.get("name") or el.get("id") for el in root.iter() if el.get("id")}
	lanes = {}
	for lane in root.iter(bpmn_tag("lane")):
		for ref in lane.findall(bpmn_tag("flowNodeRef")):
			lanes[(ref.text or "").strip()] = lane.get("name") or ""
	outgoing = {}
	for flow in root.iter(bpmn_tag("sequenceFlow")):
		outgoing.setdefault(flow.get("sourceRef"), []).append(flow)

	lines = ["Steps in diagram order:"]
	for el in root.iter():
		kind = local_name(el.tag)
		if kind in _step_tags():
			lines.append(_step_line(el, kind, lanes, names))
		elif kind in _gateway_tags():
			lines.append(_gateway_line(el, kind, outgoing, names))
	return lines


def _step_line(el, kind: str, lanes: dict, names: dict) -> str:
	lane = lanes.get(el.get("id"))
	text = f"- {kind}: {el.get('name') or el.get('id')}"
	event = _event_note(el, names)
	if event:
		text += f" [{event}]"
	if lane:
		text += f" (lane: {lane})"
	documentation = el.find(bpmn_tag("documentation"))
	if documentation is not None and (documentation.text or "").strip():
		text += f" - {frappe.utils.strip_html(documentation.text).strip()[: _max_doc_chars()]}"
	return text


def _event_note(el, names: dict) -> str:
	for child in el:
		kind, ref_attr = _event_definitions().get(local_name(child.tag), (None, None))
		if kind:
			return f"{kind}: {names.get(child.get(ref_attr), '?')}"
	if el.get("messageRef"):
		return f"message: {names.get(el.get('messageRef'), '?')}"
	return ""


def _gateway_line(el, kind: str, outgoing: dict, names: dict) -> str:
	branches = [
		f"{flow.get('name') or 'unnamed'} -> {names.get(flow.get('targetRef'), '?')}"
		for flow in outgoing.get(el.get("id"), [])
	]
	return f"- {kind}: {el.get('name') or el.get('id')} [{'; '.join(branches)}]"


def bpmn_tag(name: str) -> str:
	return f"{{{_bpmn_ns()}}}{name}"


def local_name(tag) -> str:
	return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _problem(element_id: str, message: str, rule: str = "task-config") -> dict:
	return {"kind": "config", "rule": rule, "elementId": element_id, "message": message}


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
