# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Tool choice, parallel calls, thinking, leaked delimiters, and complete() running the one step loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.provisioning.agent_config_resolver import CONFIG_TO_SHAPE
from processa.processa_engine.agent_runtime.step_loop import run_agent_loop
from processa.processa_engine.agent_runtime.tool_bounds import salvage_leaked_delimiters
from processa.processa_engine.agent_runtime.direct_api import DirectApiExecutor
from processa.processa_engine.agent_runtime.executor import ExecutorConfig
from processa.processa_engine.agent_runtime.llm_anthropic import AnthropicAdapter
from processa.processa_engine.agent_runtime.llm_factory import _for_stage
from processa.processa_engine.agent_runtime.llm_types import (
	LLMRefusedError,
	LLMTruncatedError,
	StepResult,
	StepToolCall,
	ToolSpec,
)
from processa.processa_engine.agent_runtime.llm_gemini import GeminiAdapter
from processa.processa_engine.agent_runtime.llm_openai import OpenAIAdapter
from processa.ai_agent_observability.observability import SUB_CALL_TURN_FLAG
from processa.ai_agent_skills.tools.shape_tools import PAUSE_HELD_FLAG
from processa.patches.v1_0 import ai_models_mark_effort_support, lift_max_tokens_to_thinking_minimum
from processa.tests.test_anthropic_sampling_params import _model

RAN = []


def _tool(name="wi_set_state", required=("state",)):
	return ToolSpec(
		fn=lambda **kw: RAN.append((name, kw)) or "done",
		name=name,
		description="Set the work item state.",
		parameters={"state": {"type": "string"}, "note": {"type": "string"}},
		required=list(required),
	)


class _ScriptedAdapter:
	"""Returns the given StepResults in order and records the controls each call received."""

	def __init__(self, *steps):
		self.steps = list(steps)
		self.calls = []

	async def step(self, system, transcript, tools=None, max_tokens=16384, **controls):
		self.calls.append({"transcript": [dict(t) for t in transcript], **controls})
		return self.steps.pop(0)


def _call(name="wi_set_state", **arguments):
	return StepResult(tool_calls=[StepToolCall(id="c1", name=name, arguments=arguments)])


def _loop(adapter, **kwargs):
	return asyncio.run(run_agent_loop(adapter, system="s", user="u", tools=[_tool()], **kwargs))


class TestToolChoiceInTheLoop(FrappeTestCase):
	def setUp(self):
		RAN.clear()

	def test_required_goes_to_the_first_call_only(self):
		adapter = _ScriptedAdapter(_call(state="Done"), StepResult(content="ok"))
		_loop(adapter, tool_choice="required")
		self.assertEqual(adapter.calls[0]["tool_choice"], "required")
		self.assertNotIn("tool_choice", adapter.calls[1])

	def test_a_plain_text_answer_is_sent_back_once_with_a_nudge(self):
		adapter = _ScriptedAdapter(StepResult(content="Sure."), _call(state="Done"), StepResult(content="ok"))
		completion, _ = _loop(adapter, tool_choice="required")
		self.assertEqual(completion.text, "ok")
		self.assertIn("must call a tool", adapter.calls[1]["transcript"][-1]["content"])
		self.assertEqual(adapter.calls[1]["tool_choice"], "required")
		self.assertEqual(RAN, [("wi_set_state", {"state": "Done"})])

	def test_a_second_plain_text_answer_fails_the_run(self):
		adapter = _ScriptedAdapter(StepResult(content="Sure."), StepResult(content="Still no."))
		with self.assertRaisesRegex(RuntimeError, "tool_choice is required"):
			_loop(adapter, tool_choice="required")

	def test_auto_sends_nothing_and_accepts_text(self):
		adapter = _ScriptedAdapter(StepResult(content="Hello."))
		completion, _ = _loop(adapter, tool_choice="auto")
		self.assertEqual(completion.text, "Hello.")
		self.assertNotIn("tool_choice", adapter.calls[0])

	def test_parallel_off_and_a_thinking_budget_reach_every_call(self):
		adapter = _ScriptedAdapter(_call(state="Done"), StepResult(content="ok"))
		_loop(adapter, parallel_tool_calls=False, thinking_budget_tokens=2048)
		for call in adapter.calls:
			self.assertEqual((call["parallel_tool_calls"], call["thinking_budget_tokens"]), (False, 2048))

	def test_thinking_blocks_go_back_with_the_tool_results(self):
		block = {"type": "thinking", "thinking": "plan", "signature": "sig"}
		first = _call(state="Done")
		first.thinking = [block]
		adapter = _ScriptedAdapter(first, StepResult(content="ok"))
		_loop(adapter)
		self.assertEqual(adapter.calls[1]["transcript"][-2]["thinking"], [block])


class TestLeakedDelimiters(FrappeTestCase):
	def setUp(self):
		RAN.clear()

	def test_the_delimiter_is_removed_and_the_opened_argument_recovered(self):
		repaired = salvage_leaked_delimiters(
			"finalize",
			{"summary": {"type": "string"}, "outstanding": {"type": "array"}},
			{"summary": 'Done.</summary>\n<parameter name="outstanding">Add tests</parameter>'},
		)
		self.assertEqual(repaired, {"summary": "Done.", "outstanding": ["Add tests"]})

	def test_a_recovered_required_argument_passes_validation_and_the_tool_runs(self):
		adapter = _ScriptedAdapter(
			_call(note='Closing.</note><parameter name="state">Done</parameter>'), StepResult(content="ok")
		)
		_loop(adapter)
		self.assertEqual(RAN, [("wi_set_state", {"note": "Closing.", "state": "Done"})])

	def test_clean_arguments_are_untouched(self):
		arguments = {"summary": "Done <b>well</b>."}
		self.assertEqual(salvage_leaked_delimiters("finalize", {"summary": {}}, arguments), arguments)


class TestCompleteRunsTheStepLoop(FrappeTestCase):
	def setUp(self):
		RAN.clear()

	def _adapter(self, *steps):
		adapter = AnthropicAdapter(api_key="test-key-not-real", model="claude-sonnet-4-5")
		scripted = _ScriptedAdapter(*steps)
		adapter.step = scripted.step
		return adapter, scripted

	def test_a_missing_required_argument_never_reaches_the_script(self):
		adapter, scripted = self._adapter(_call(), StepResult(content="ok"))
		asyncio.run(adapter.complete(system="s", user="u", tools=[_tool()]))
		self.assertEqual(RAN, [])
		self.assertIn(
			"Missing required argument 'state' for tool wi_set_state",
			scripted.calls[1]["transcript"][-1]["results"][0]["content"],
		)

	def test_the_calling_turn_keeps_its_flags_and_a_turn_cap_returns_no_text(self):
		frappe.flags[SUB_CALL_TURN_FLAG] = 3
		frappe.flags[PAUSE_HELD_FLAG] = True
		adapter, _ = self._adapter(_call(state="a"), _call(state="b"))
		completion = asyncio.run(adapter.complete(system="s", user="u", tools=[_tool()], max_turns=2))
		self.assertEqual((frappe.flags[SUB_CALL_TURN_FLAG], frappe.flags[PAUSE_HELD_FLAG]), (3, True))
		self.assertEqual((completion.text, completion.hit_turn_cap), ("", True))
		frappe.flags[SUB_CALL_TURN_FLAG] = None
		frappe.flags[PAUSE_HELD_FLAG] = False


class _AnthropicStream:
	def __init__(self, sent, response):
		self.sent, self.response = sent, response

	def __call__(self, **kwargs):
		self.sent.append(kwargs)
		return self

	async def __aenter__(self):
		return self

	async def __aexit__(self, *exc):
		return False

	async def get_final_message(self):
		return self.response


def _anthropic(model, *, stop_reason="end_turn", content=None):
	adapter = AnthropicAdapter(api_key="test-key-not-real", model=model)
	sent = []
	response = SimpleNamespace(
		content=content or [SimpleNamespace(type="text", text="ok")],
		stop_reason=stop_reason,
		usage=SimpleNamespace(input_tokens=1, output_tokens=1),
	)
	adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=_AnthropicStream(sent, response)))
	return adapter, sent


def _anthropic_step(model, **controls):
	adapter, sent = _anthropic(model)
	asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}], tools=[_tool()], **controls))
	return sent[0]


def _effort_model(name: str, support: int) -> str:
	_model(name, 0)
	frappe.db.set_value("AI Model", name, "support_effort", support)
	return name


def _anthropic_effort_step(model, effort="", stage="", stop_reason="end_turn", thinking_min_tokens=0, **controls):
	adapter, sent = _anthropic(model, stop_reason=stop_reason)
	adapter.effort, adapter.stage, adapter.thinking_min_tokens = effort, stage, thinking_min_tokens
	asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}], **controls))
	return sent[0]


class TestEffortAndRoomToThink(FrappeTestCase):
	def test_the_adapter_sends_the_effort_it_was_given(self):
		sent = _anthropic_effort_step("claude-sonnet-5-5", effort="high")
		self.assertEqual(sent["output_config"], {"effort": "high"})

	def test_effort_rides_with_a_response_schema(self):
		schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
		sent = _anthropic_effort_step("claude-opus-5-5", effort="low", response_schema=schema)
		self.assertEqual(sent["output_config"]["effort"], "low")
		self.assertIn("format", sent["output_config"])

	def test_a_blank_effort_and_a_word_that_is_no_level_send_nothing(self):
		self.assertNotIn("output_config", _anthropic_effort_step("claude-sonnet-5-5"))
		self.assertNotIn("output_config", _anthropic_effort_step("claude-sonnet-5-5", effort="extreme"))

	def test_an_adapter_gets_effort_and_the_thinking_minimum_only_when_its_ai_model_supports_effort(self):
		supported, unsupported = _effort_model("_effort-yes-sonnet-5-5", 1), _effort_model("_effort-no-sonnet-4-5", 0)
		cfg = {"effort": "high", "name": "Logix - Script Writer", "thinking_min_tokens": 4096}
		for model, expected in ((supported, ("high", 4096)), (unsupported, ("", 0))):
			adapter = _for_stage(SimpleNamespace(), cfg, model)
			self.assertEqual((adapter.effort, adapter.thinking_min_tokens), expected)
			self.assertEqual(adapter.stage, "Logix - Script Writer")

	def test_a_minimum_that_is_not_set_is_8192_on_a_model_that_thinks(self):
		adapter = _for_stage(SimpleNamespace(), {"thinking_min_tokens": 0}, _effort_model("_effort-yes-sonnet-5-5", 1))
		self.assertEqual(adapter.thinking_min_tokens, 8192)

	def test_a_call_below_the_minimum_is_raised_to_it(self):
		sent = _anthropic_effort_step("claude-sonnet-5-5", max_tokens=512, thinking_min_tokens=8192)
		self.assertEqual(sent["max_tokens"], 8192)

	def test_a_value_above_the_minimum_and_a_model_that_does_not_think_are_kept(self):
		sent = _anthropic_effort_step("claude-sonnet-5", max_tokens=64000, thinking_min_tokens=8192)
		self.assertEqual(sent["max_tokens"], 64000)
		self.assertEqual(_anthropic_effort_step("claude-sonnet-4-5", max_tokens=512)["max_tokens"], 512)

	def test_a_truncated_reply_is_logged_with_the_stage_and_the_cap(self):
		with patch("frappe.log_error") as log_error, self.assertRaises(LLMTruncatedError):
			_anthropic_effort_step(
				"claude-sonnet-5-5",
				stage="Logix - Clarifier",
				stop_reason="max_tokens",
				max_tokens=512,
				thinking_min_tokens=8192,
			)
		self.assertEqual(log_error.call_args.kwargs["title"], "AI reply truncated: Logix - Clarifier")
		self.assertIn("8192-token output cap", log_error.call_args.kwargs["message"])

	def test_the_plain_call_sends_effort_and_the_minimum_by_the_ai_model(self):
		executor = DirectApiExecutor()
		supported = _effort_model("_effort-yes-opus-5-5", 1)
		config = ExecutorConfig(model=supported, user_prompt="u", max_tokens=1024, effort="medium")
		_url, payload, _headers = executor._build_anthropic_request("e", "k", "claude-opus-5-5", config)
		self.assertEqual((payload["output_config"], payload["max_tokens"]), ({"effort": "medium"}, 8192))
		config.thinking_min_tokens = 2048
		_url, payload, _headers = executor._build_anthropic_request("e", "k", "claude-opus-5-5", config)
		self.assertEqual(payload["max_tokens"], 2048)
		config.model = _effort_model("_effort-no-sonnet-4-5", 0)
		_url, payload, _headers = executor._build_anthropic_request("e", "k", "claude-sonnet-4-5", config)
		self.assertNotIn("output_config", payload)
		self.assertEqual(payload["max_tokens"], 1024)

	def test_the_patch_ticks_the_claude_models_that_take_every_level(self):
		fable, haiku = _effort_model("claude-fable-5-2", 0), _effort_model("claude-haiku-4-5", 0)
		ai_models_mark_effort_support.execute()
		ai_models_mark_effort_support.execute()
		self.assertEqual(frappe.db.get_value("AI Model", fable, "support_effort"), 1)
		self.assertEqual(frappe.db.get_value("AI Model", haiku, "support_effort"), 0)
		for name in ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-opus-4-8"):
			self.assertTrue(ai_models_mark_effort_support.accepts_effort(name), name)
		for name in ("claude-sonnet-4-5", "claude-sonnet-4-6", "claude-opus-4-5", "gpt-5", "gemini-2.0-flash", ""):
			self.assertFalse(ai_models_mark_effort_support.accepts_effort(name), name)


class TestMaxTokensCoversTheThinkingMinimum(FrappeTestCase):
	def _doc(self, model, max_tokens, minimum):
		doc = frappe.new_doc("AI Agent Configuration")
		doc.ai_model, doc.max_tokens, doc.thinking_min_tokens = model, max_tokens, minimum
		return doc

	def test_max_tokens_below_the_minimum_is_refused_on_a_model_that_thinks(self):
		thinks = _effort_model("_effort-yes-sonnet-5-5", 1)
		with self.assertRaisesRegex(frappe.ValidationError, "below Minimum Tokens When Thinking"):
			self._doc(thinks, 512, 8192).validate_thinking_minimum()
		with self.assertRaisesRegex(frappe.ValidationError, r"\(8192\)"):
			self._doc(thinks, 512, 0).validate_thinking_minimum()

	def test_a_lowered_minimum_a_covering_max_and_a_model_that_does_not_think_pass(self):
		thinks = _effort_model("_effort-yes-sonnet-5-5", 1)
		self._doc(thinks, 2048, 2048).validate_thinking_minimum()
		self._doc(thinks, 64000, 8192).validate_thinking_minimum()
		self._doc(_effort_model("_effort-no-sonnet-4-5", 0), 512, 8192).validate_thinking_minimum()

	def test_the_patch_lifts_max_tokens_only_where_the_model_thinks(self):
		names = []
		for agent_id, model in (("zz_lift_thinks", "_effort-yes-sonnet-5-5"), ("zz_lift_plain", "_effort-no-sonnet-4-5")):
			_effort_model(model, int(model.startswith("_effort-yes")))
			doc = frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": agent_id,
					"agent_id": agent_id,
					"agent_type": "Background",
					"agent_framework": "LangGraph",
					"ai_model": model,
					"max_tokens": 16384,
				}
			)
			doc.insert()
			frappe.db.set_value("AI Agent Configuration", doc.name, "max_tokens", 512)
			names.append(doc.name)
		lift_max_tokens_to_thinking_minimum.execute()
		lift_max_tokens_to_thinking_minimum.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", names[0], "max_tokens"), 8192)
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", names[1], "max_tokens"), 512)


class TestAnthropicControls(FrappeTestCase):
	def test_required_and_a_name_are_forced_on_a_model_that_accepts_it(self):
		self.assertEqual(
			_anthropic_step("claude-sonnet-4-5", tool_choice="required")["tool_choice"], {"type": "any"}
		)
		self.assertEqual(
			_anthropic_step("claude-sonnet-5", tool_choice="wi_set_state")["tool_choice"],
			{"type": "tool", "name": "wi_set_state"},
		)

	def test_a_model_that_rejects_forcing_gets_auto(self):
		for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"):
			self.assertNotIn("tool_choice", _anthropic_step(model, tool_choice="required"), model)

	def test_parallel_off_is_sent_on_every_model(self):
		self.assertEqual(
			_anthropic_step("claude-opus-5-5", tool_choice="required", parallel_tool_calls=False)[
				"tool_choice"
			],
			{"type": "auto", "disable_parallel_tool_use": True},
		)

	def test_a_thinking_budget_goes_only_to_models_that_take_one_and_drops_forcing(self):
		sent = _anthropic_step("claude-sonnet-4-5", tool_choice="required", thinking_budget_tokens=2048)
		self.assertEqual(sent["thinking"], {"type": "enabled", "budget_tokens": 2048})
		self.assertNotIn("tool_choice", sent)
		self.assertNotIn("thinking", _anthropic_step("claude-sonnet-5", thinking_budget_tokens=2048))

	def test_thinking_comes_back_and_is_replayed_before_the_tool_call(self):
		adapter, sent = _anthropic(
			"claude-sonnet-4-5",
			stop_reason="tool_use",
			content=[
				SimpleNamespace(type="thinking", thinking="plan", signature="sig"),
				SimpleNamespace(type="tool_use", id="t1", name="wi_set_state", input={"state": "Done"}),
			],
		)
		step = asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}], tools=[_tool()]))
		self.assertEqual(step.thinking, [{"type": "thinking", "thinking": "plan", "signature": "sig"}])
		transcript = [
			{"role": "user", "content": "u"},
			{
				"role": "assistant",
				"content": "",
				"thinking": step.thinking,
				"tool_calls": [{"id": "t1", "name": "wi_set_state", "arguments": {}}],
			},
			{"role": "tool_results", "results": [{"id": "t1", "name": "wi_set_state", "content": "done"}]},
		]
		asyncio.run(adapter.step("s", transcript, tools=[_tool()]))
		self.assertEqual([b["type"] for b in sent[1]["messages"][1]["content"]], ["thinking", "tool_use"])

	def test_a_reply_cut_at_max_tokens_raises(self):
		adapter, _ = _anthropic("claude-sonnet-4-5", stop_reason="max_tokens")
		with self.assertRaises(LLMTruncatedError):
			asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}]))

	def test_a_refusal_with_no_content_raises_instead_of_an_empty_answer(self):
		adapter, _ = _anthropic("claude-sonnet-5-5", stop_reason="refusal", content=[])
		with self.assertRaises(LLMRefusedError):
			asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}]))

	def test_the_user_context_prefix_is_cached_before_the_first_tool_result(self):
		adapter, sent = _anthropic("claude-sonnet-4-5")
		asyncio.run(adapter.step("s", [{"role": "user", "content": "History...\n\nUser message: hi"}]))
		blocks = sent[0]["messages"][0]["content"]
		self.assertEqual(
			blocks[0], {"type": "text", "text": "History...", "cache_control": {"type": "ephemeral"}}
		)
		self.assertEqual(blocks[1]["text"], "User message: hi")


class _OpenAICompletions:
	def __init__(self, sent, message, finish_reason):
		self.sent, self.message, self.finish_reason = sent, message, finish_reason

	async def create(self, **kwargs):
		self.sent.append(kwargs)
		return SimpleNamespace(
			choices=[SimpleNamespace(message=self.message, finish_reason=self.finish_reason)],
			usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=None),
		)


def _openai_step(message=None, finish_reason="stop", **controls):
	adapter = OpenAIAdapter(api_key="test-key-not-real", model="gpt-4o-mini")
	sent = []
	message = message or SimpleNamespace(content="ok", tool_calls=None)
	adapter._client = SimpleNamespace(
		chat=SimpleNamespace(completions=_OpenAICompletions(sent, message, finish_reason))
	)
	step = asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}], tools=[_tool()], **controls))
	return step, sent[0]


class TestOpenAIControls(FrappeTestCase):
	def test_required_a_name_and_parallel_off_reach_the_request(self):
		self.assertEqual(_openai_step(tool_choice="required")[1]["tool_choice"], "required")
		self.assertEqual(
			_openai_step(tool_choice="wi_set_state")[1]["tool_choice"],
			{"type": "function", "function": {"name": "wi_set_state"}},
		)
		self.assertIs(_openai_step(parallel_tool_calls=False)[1]["parallel_tool_calls"], False)
		self.assertNotIn("tool_choice", _openai_step()[1])

	def test_a_forced_call_that_finishes_with_stop_still_returns_the_tool_call(self):
		call = SimpleNamespace(
			id="t1", function=SimpleNamespace(name="wi_set_state", arguments='{"state": "Done"}')
		)
		step, _ = _openai_step(SimpleNamespace(content=None, tool_calls=[call]), tool_choice="wi_set_state")
		self.assertEqual(
			[(c.name, c.arguments) for c in step.tool_calls], [("wi_set_state", {"state": "Done"})]
		)


class TestGeminiControls(FrappeTestCase):
	def _config(self, **controls):
		adapter = GeminiAdapter(api_key="test-key-not-real", model="gemini-2.5-flash")
		sent = []

		async def generate_content(model, contents, config):
			sent.append(config)
			part = SimpleNamespace(function_call=None, text="ok")
			return SimpleNamespace(
				candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], usage_metadata=None
			)

		adapter._client = SimpleNamespace(
			aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
		)
		asyncio.run(adapter.step("s", [{"role": "user", "content": "u"}], tools=[_tool()], **controls))
		return sent[0]

	def test_a_tool_name_forces_that_function_and_the_budget_reaches_thinking(self):
		config = self._config(tool_choice="wi_set_state", thinking_budget_tokens=2048)
		calling = config.tool_config.function_calling_config
		self.assertEqual((calling.mode.value, calling.allowed_function_names), ("ANY", ["wi_set_state"]))
		self.assertEqual(config.thinking_config.thinking_budget, 2048)

	def test_auto_leaves_both_unset(self):
		config = self._config()
		self.assertIsNone(config.tool_config)
		self.assertIsNone(config.thinking_config)


class TestTheAgentConfiguration(FrappeTestCase):
	def test_the_controls_reach_the_task_config(self):
		for field, attribute in (
			("tool_choice", "aiToolChoice"),
			("parallel_tool_calls", "aiParallelToolCalls"),
			("thinking_budget_tokens", "aiThinkingBudgetTokens"),
			("effort", "aiEffort"),
			("terminal_tools", "aiTerminalTools"),
		):
			self.assertEqual(CONFIG_TO_SHAPE[field], attribute)

	def test_a_thinking_budget_below_1024_or_at_max_tokens_is_refused(self):
		doc = frappe.new_doc("AI Agent Configuration")
		doc.max_tokens = 4096
		for budget in (500, 4096):
			doc.thinking_budget_tokens = budget
			with self.assertRaises(frappe.ValidationError):
				doc.validate_thinking_budget()
		doc.thinking_budget_tokens = 2048
		doc.validate_thinking_budget()
