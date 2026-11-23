# Copyright (c) 2026, one-fm and contributors
"""Files attached to a chat turn reach the model: images as images, text files as text, the rest named as not read."""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import helpers as prosally_helpers
from processa.processa_engine.agent_runtime.direct_api import DirectApiExecutor
from processa.processa_engine.agent_runtime.executor import ExecutorConfig, ExecutorContext
from processa.processa_engine.agent_runtime.llm_anthropic import AnthropicAdapter
from processa.processa_engine.agent_runtime.llm_base import BaseLLMAdapter
from processa.processa_engine.agent_runtime.llm_gemini import GeminiAdapter
from processa.processa_engine.agent_runtime.llm_types import StepResult
from processa.processa_engine.agent_runtime.llm_openai import OpenAIAdapter
from processa.processa_engine.dispatch import attachments
from processa.tests.test_adapter_tool_controls import _OpenAICompletions
from processa.tests.test_anthropic_sampling_params import _model
from processa.tests.test_temperature_reaches_the_provider import _Stream

PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
IMAGE = {"media_type": "image/png", "data": base64.b64encode(PNG).decode()}
TURN = [{"role": "user", "content": "what is in this picture?", "images": [IMAGE]}]


def _file(name, content):
	return frappe.get_doc({"doctype": "File", "file_name": name, "content": content, "is_private": 0}).insert(
		ignore_permissions=True
	)


class TestReadAttachments(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_images_text_and_unreadable_files_are_each_handled(self):
		image = _file("screen.png", PNG)
		note = _file("steps.txt", b"Click Generate Invoice, then wait.")
		clip = _file("clip.mp4", b"\x00\x00\x00\x18ftypmp42")
		images, text = attachments.read_attachments(
			[image.file_url, note.file_url, clip.file_url, "/files/gone.png"]
		)
		self.assertEqual(images, [IMAGE])
		self.assertIn("Click Generate Invoice, then wait.", text)
		self.assertIn("clip.mp4 was not read", text)
		self.assertIn("gone.png was not read", text)

	def test_an_image_over_the_limit_is_not_read(self):
		image = _file("big.png", PNG)
		with patch.object(attachments, "MAX_IMAGE_BYTES", 10):
			images, text = attachments.read_attachments([image.file_url])
		self.assertEqual(images, [])
		self.assertIn("big.png was not read", text)

	def test_a_step_run_as_a_tool_reads_the_turns_files(self):
		as_tool = frappe._dict(data={"request": "x"}, process_data={"files": ["/files/a.png"]})
		self.assertEqual(attachments.task_files(as_tool), ["/files/a.png"])
		own = frappe._dict(data={"files": ["/files/b.png"]}, process_data={"files": ["/files/a.png"]})
		self.assertEqual(attachments.task_files(own), ["/files/b.png"])
		self.assertEqual(attachments.task_files(frappe._dict(data={})), [])

	def test_no_files_gives_nothing(self):
		self.assertEqual(attachments.read_attachments([]), ([], ""))
		self.assertEqual(attachments.read_attachments(None), ([], ""))


class TestAdaptersSendImages(FrappeTestCase):
	def test_anthropic_sends_an_image_block_after_the_text(self):
		adapter = AnthropicAdapter(api_key="test-key-not-real", model="claude-sonnet-4-5")
		sent = []
		adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=_Stream(sent)))
		asyncio.run(adapter.step("sys", TURN))
		content = sent[0]["messages"][-1]["content"]
		self.assertEqual(content[-1], {"type": "image", "source": {"type": "base64", **IMAGE}})
		self.assertIn("what is in this picture?", "".join(b.get("text", "") for b in content))

	def test_openai_sends_the_image_as_a_data_url(self):
		adapter = OpenAIAdapter(api_key="test-key-not-real", model="gpt-4o-mini")
		sent = []
		message = SimpleNamespace(content="ok", tool_calls=None)
		adapter._client = SimpleNamespace(
			chat=SimpleNamespace(completions=_OpenAICompletions(sent, message, "stop"))
		)
		asyncio.run(adapter.step("s", TURN))
		content = sent[0]["messages"][-1]["content"]
		self.assertEqual(content[1]["image_url"]["url"], f"data:image/png;base64,{IMAGE['data']}")

	def test_gemini_sends_the_image_bytes(self):
		adapter = GeminiAdapter(api_key="test-key-not-real", model="gemini-2.5-flash")
		sent = []

		async def generate_content(model, contents, config):
			sent.append(contents)
			part = SimpleNamespace(function_call=None, text="ok")
			return SimpleNamespace(
				candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], usage_metadata=None
			)

		adapter._client = SimpleNamespace(
			aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
		)
		asyncio.run(adapter.step("s", TURN))
		self.assertEqual(sent[0][-1].parts[1].inline_data.data, PNG)


class TestImagesTakeTheAdapterPath(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_call_with_an_image_and_no_tools_goes_through_the_adapter(self):
		config = ExecutorConfig(
			provider_name="Anthropic",
			model=_model("zz-attachments-model", 1),
			user_prompt="look",
			images=[IMAGE],
		)
		with patch.object(DirectApiExecutor, "_run_with_tools", return_value="adapter path") as adapter_path:
			self.assertEqual(DirectApiExecutor().run(config, ExecutorContext()), "adapter path")
		self.assertEqual(adapter_path.call_args.args[0].images, [IMAGE])


class TestSubCallsSendImages(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_complete_puts_the_images_on_the_first_user_message(self):
		sent = []

		class Adapter(BaseLLMAdapter):
			async def step(self, system, transcript, **kwargs):
				sent.append(list(transcript))
				return StepResult(content="done")

		result = asyncio.run(Adapter().complete(system="s", user="draw this", images=[IMAGE]))
		self.assertEqual(result.text, "done")
		self.assertEqual(sent[0][0], {"role": "user", "content": "draw this", "images": [IMAGE]})

	def test_a_prosally_step_sends_the_turns_files_with_its_model_call(self):
		calls = []

		class Adapter:
			async def complete(self, **kwargs):
				calls.append(kwargs)
				return SimpleNamespace(text="reply")

		image = _file("process.png", PNG)
		note = _file("steps.txt", "Submit, Review, Approve")
		cfg = {"sub_prompts": {"modifier": {"prompt": "You modify BPMN."}}}
		with patch.object(prosally_helpers, "get_llm_adapter_from_settings", return_value=Adapter()):
			prosally_helpers.complete_sub_prompt(
				cfg, "modifier", "copy this", files=[image.file_url, note.file_url]
			)
			prosally_helpers.complete_sub_prompt(cfg, "modifier", "no files", files=[])
		self.assertEqual(calls[0]["images"], [IMAGE])
		self.assertTrue(calls[0]["user"].startswith("copy this\n\n"))
		self.assertIn("Submit, Review, Approve", calls[0]["user"])
		self.assertEqual(calls[1], {"system": "You modify BPMN.", "user": "no files"})
