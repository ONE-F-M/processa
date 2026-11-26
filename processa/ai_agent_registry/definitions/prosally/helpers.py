"""ProsAlly's map Server Script functions and the model, XML and confirmation basics its tools share."""

import re
from xml.etree import ElementTree as ET


from processa.ai_agent_memory.text_clean import strip_html
from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from processa.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings
from processa.processa_engine.dispatch.attachments import with_attachments
from processa.processa_engine.agent_runtime.turn_state import run_sync

AGENT_ID = "prosally_agent"

# Whole replies that approve a pending confirmation, after punctuation and "please" or "thanks" are dropped.
AFFIRMATIONS = frozenset(
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
# Replies starting with one of these turn a pending confirmation down.
DECLINES = ("no", "nope", "nah", "wait", "change", "not yet", "hold on", "stop", "dont", "do not", "cancel")
_POLITE_WORDS = re.compile(r"\b(please|thanks|thank you)\b")

NS = {
	"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
	"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
	"dc": "http://www.omg.org/spec/DD/20100524/DC",
	"di": "http://www.omg.org/spec/DD/20100524/DI",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom": "http://custom/text-style",
	"camunda": "http://camunda.org/schema/1.0/bpmn",
}

STEP_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("task", "userTask", "scriptTask", "serviceTask", "manualTask", "businessRuleTask")
)

DIAGRAM_REPLIES = ("BPMN_MODIFIED", "BPMN_GENERATED")
IR_NODE_TYPES = frozenset(
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
DIAGRAM_VERSION_SUFFIX = re.compile(r"\s+-\s+v\d+\s*$", re.I)
MEMORY_NOTES_LIMIT = 8
MEMORY_NOTES_HEADER = "Notes from earlier work on this process:"
MEMORY_NOTES_PROVENANCE = "These were agreed in other conversations; they do not mean the diagram exists."
MEMORY_BACKEND = "direct_api"
REQUEST_STOPWORDS = frozenset(
	("create", "sub", "process", "subprocess", "step", "steps", "with", "that", "this", "from", "into", "inside", "when", "then", "should")
)

DMS_SOURCES_LIMIT = 4


def prosally_config() -> dict:
	"""ProsAlly's resolved agent configuration."""
	cfg = get_agent_config(AGENT_ID) or {}
	cfg.setdefault("agent_id", AGENT_ID)
	return cfg


def complete_sub_prompt(
	cfg: dict, sub_id: str, user: str, system: str | None = None, max_tokens=None, files: list | None = None
) -> str:
	"""One model call with a sub-prompt as the system prompt, returning the reply text.

	files are the turn's attachments: images go with the prompt, text files are added to it."""
	stage = (cfg.get("sub_prompts") or {}).get(sub_id) or {}
	if system is None:
		system = stage.get("prompt") or ""
	kwargs = {"system": system, **with_attachments(user, files)}
	if max_tokens:
		kwargs["max_tokens"] = max_tokens
	stage_cfg = {
		**cfg,
		"effort": stage.get("effort") or cfg.get("effort"),
		"stage": f"{cfg.get('name') or AGENT_ID} / {sub_id}",
	}
	return run_sync(get_llm_adapter_from_settings(stage_cfg).complete(**kwargs)).text


def memory_notes_block(turn: dict | None) -> str:
	"""The turn's recalled notes under their heading; "" when it has none."""
	notes = (turn or {}).get("memory_notes") or []
	if not notes:
		return ""
	return "\n".join([MEMORY_NOTES_HEADER, MEMORY_NOTES_PROVENANCE] + ["- " + n for n in notes])


def document_sources_line(documents: list, lead: str) -> str:
	"""A line naming up to DMS_SOURCES_LIMIT distinct documents by code, title and type."""
	named = []
	for d in documents:
		label = " - ".join(filter(None, (d.get("document_code"), d.get("title")))) + f" ({d.get('document_type')})"
		if label not in named:
			named.append(label)
	return f"{lead}: " + "; ".join(named[:DMS_SOURCES_LIMIT])


def confirmation_reply(text: str) -> str:
	""" "yes" when text is a plain affirmation, "no" when it starts with a decline, else ""."""
	words = re.sub(r"[^a-z ]", " ", strip_html(text).lower().replace("'", ""))
	words = " ".join(_POLITE_WORDS.sub(" ", words).split())
	if words in AFFIRMATIONS:
		return "yes"
	if any(words == d or words.startswith(d + " ") for d in DECLINES):
		return "no"
	return ""


def quoted(name: str) -> str:
	return '"' + name + '"'


def register_namespaces() -> None:
	for prefix, uri in NS.items():
		ET.register_namespace(prefix, uri)
