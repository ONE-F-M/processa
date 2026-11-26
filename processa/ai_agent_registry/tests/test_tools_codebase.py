"""search_codebase finds text in the installed apps' source, stays inside the app and hides secret values."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.shared import tools_codebase
from processa.ai_agent_registry.definitions.shared.tools_codebase import (
	_sanitize_codebase_output,
	search_codebase,
)

SHARED_PATH = "ai_agent_registry/definitions/shared"


def _fake_process(stdout="", communicate_side_effect=None):
	process = MagicMock()
	if communicate_side_effect is not None:
		process.communicate.side_effect = communicate_side_effect
	else:
		process.communicate.return_value = (stdout, None)
	return process


class TestSearchCodebase(FrappeTestCase):
	def test_a_match_has_the_app_path_line_number_and_text(self):
		result = json.loads(search_codebase("def get_doctype_fields", app="processa"))
		self.assertEqual(set(result), {"query", "results", "count", "searched_apps"})
		self.assertEqual(result["query"], "def get_doctype_fields")
		self.assertEqual(result["searched_apps"], ["processa"])
		self.assertEqual(result["count"], len(result["results"]))
		self.assertTrue(
			any(
				line.startswith("[processa] /")
				and line.endswith("/shared/tools.py:14:def get_doctype_fields(doctype: str) -> str:")
				for line in result["results"]
			),
			result["results"],
		)

	def test_a_path_that_leaves_the_app_is_refused_and_grep_does_not_run(self):
		for path in ("../one_fm_password_management", "/etc", "../../sites"):
			with self.subTest(path=path):
				with patch.object(tools_codebase.subprocess, "Popen") as popen:
					result = json.loads(search_codebase("x", path=path, app="processa"))
				self.assertEqual(result, {"error": f"Path '{path}' is outside the app."})
				popen.assert_not_called()

	def test_a_sibling_folder_with_a_longer_name_is_outside_the_app(self):
		with patch.object(tools_codebase.subprocess, "Popen") as popen:
			result = json.loads(search_codebase("x", path="../processa_sibling", app="processa"))
		self.assertIn("is outside the app", result["error"])
		popen.assert_not_called()

	def test_an_app_that_is_not_installed_is_refused(self):
		with patch.object(tools_codebase.subprocess, "Popen") as popen:
			result = json.loads(search_codebase("x", app="zz_not_an_app"))
		self.assertEqual(result, {"error": "App 'zz_not_an_app' is not installed on this site."})
		popen.assert_not_called()

	def test_a_query_with_a_leading_dash_is_searched_as_text(self):
		for query in ("-rf", "--help"):
			with self.subTest(query=query):
				result = json.loads(search_codebase(query, path=SHARED_PATH, app="processa"))
				self.assertNotIn("error", result)
				self.assertEqual(result["count"], len(result["results"]))
				for line in result["results"]:
					self.assertIn(query, line)
					self.assertNotIn("Usage:", line)

	def test_the_dash_dash_comes_before_the_query_and_the_command_is_a_list(self):
		process = _fake_process("")
		with patch.object(tools_codebase.subprocess, "Popen", return_value=process) as popen:
			search_codebase("--help", app="processa")
		command = popen.call_args.args[0]
		self.assertIsInstance(command, list)
		self.assertEqual(command[command.index("--") + 1], "--help")
		self.assertNotIn("shell", popen.call_args.kwargs)
		for pattern in ("*.py", "*.md", "*.pem", ".env", ".env.*", "__pycache__"):
			self.assertIn(pattern, command)

	def test_secret_values_are_redacted(self):
		self.assertEqual(_sanitize_codebase_output('api_key = "abc123"'), "api_key=REDACTED")
		self.assertEqual(_sanitize_codebase_output("PASSWORD: hunter2"), "PASSWORD=REDACTED")
		self.assertEqual(_sanitize_codebase_output("token='t0k3n', x"), "token=REDACTED, x")
		self.assertEqual(_sanitize_codebase_output("def get_doctype_fields():"), "def get_doctype_fields():")

	def test_a_redacted_value_does_not_reach_the_results(self):
		process = _fake_process('/a/b.py:3:password = "hunter2"\n')
		with patch.object(tools_codebase.subprocess, "Popen", return_value=process):
			result = json.loads(search_codebase("password", app="processa"))
		self.assertEqual(result["count"], 1)
		self.assertNotIn("hunter2", result["results"][0])

	def test_a_query_over_200_characters_is_refused(self):
		self.assertEqual(
			json.loads(search_codebase("a" * 201)),
			{"error": "Query too long. Maximum 200 characters allowed."},
		)
		with patch.object(tools_codebase.subprocess, "Popen", return_value=_fake_process("")):
			self.assertNotIn("error", json.loads(search_codebase("a" * 200, app="processa")))

	def test_a_blank_query_is_refused(self):
		for query in ("", "   "):
			with self.subTest(query=repr(query)):
				self.assertEqual(json.loads(search_codebase(query)), {"error": "Query cannot be empty."})

	def test_results_stop_at_100_across_apps(self):
		lines = "".join(f"/x/f.py:{i}:needle\n" for i in range(60))
		with (
			patch.object(tools_codebase.frappe, "get_installed_apps", return_value=["frappe", "processa", "erpnext"]),
			patch.object(tools_codebase.subprocess, "Popen", side_effect=lambda *a, **k: _fake_process(lines)) as popen,
		):
			result = json.loads(search_codebase("needle"))
		self.assertEqual(result["count"], 100)
		self.assertEqual(len(result["results"]), 100)
		self.assertEqual(popen.call_count, 2)

	def test_an_app_that_times_out_is_killed_and_skipped(self):
		process = _fake_process(communicate_side_effect=[subprocess.TimeoutExpired("grep", 5), ("", None)])
		with patch.object(tools_codebase.subprocess, "Popen", return_value=process):
			result = json.loads(search_codebase("needle", app="processa"))
		process.kill.assert_called_once()
		self.assertEqual(result["results"], [])
		self.assertEqual(process.communicate.call_args_list[0].kwargs, {"timeout": 5})
