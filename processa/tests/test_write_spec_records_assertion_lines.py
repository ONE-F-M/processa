# Copyright (c) 2026, one-fm and contributors
"""Write Spec records the '// ASSERT ACn:' lines of the spec it wrote, and the patch gives that to sites that lack it."""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from processa.patches.v1_0 import add_testing_agent_sandbox_tools as tools
from processa.patches.v1_0 import write_spec_records_assertion_lines as p

AC2_SPEC = (
	"test('x', async ({ page }) => {\n"
	'  // ASSERT AC2: with 8 seeded chat users in one department this month, no text matching "<number> more users"  is shown (UI)\n'
	"});\n"
)


def run_block(content, file="ac2.spec.js", turn=None, result=None):
	"""Runs the appended block the way a Server Script would, against a fake turn state. Returns (result, saved turn updates)."""
	state, saved = dict(turn or {}), {}
	fake = types.ModuleType("turn_state")
	fake.get_turn = lambda docname: state
	fake.update_turn = lambda docname, **kw: saved.update(kw)
	namespace = {"content": content, "file": file, "context_docname": "A2A-1", "result": {} if result is None else result}
	with patch.dict(sys.modules, {"processa.processa_engine.agent_runtime.turn_state": fake}):
		exec(compile(tools.RECORD_ASSERTIONS, "write_spec", "exec"), namespace)
	return namespace["result"], saved


class TestRecordedLines(unittest.TestCase):
	def test_the_line_after_the_prefix_is_saved_with_whitespace_collapsed(self):
		result, saved = run_block(AC2_SPEC)
		self.assertEqual(
			saved["spec_assertions"],
			{"ac2.spec.js": {"AC2": ['with 8 seeded chat users in one department this month, no text matching "<number> more users" is shown (UI)']}},
		)
		self.assertEqual(result["assertion_lines_recorded"], {"AC2": 1})

	def test_the_id_loses_its_spaces_and_is_upper_cased_and_lines_keep_file_order(self):
		_result, saved = run_block("// assert ac 1: first\n// ASSERT AC1:   second   line\n// ASSERT AC 2: other\n")
		self.assertEqual(saved["spec_assertions"]["ac2.spec.js"], {"AC1": ["first", "second line"], "AC2": ["other"]})

	def test_files_already_recorded_are_kept(self):
		_result, saved = run_block(AC2_SPEC, file="b.spec.js", turn={"spec_assertions": {"a.spec.js": {"AC1": ["one"]}}})
		self.assertEqual(sorted(saved["spec_assertions"]), ["a.spec.js", "b.spec.js"])

	def test_writing_the_same_file_again_replaces_its_lines(self):
		_result, saved = run_block("// ASSERT AC1: new\n", file="a.spec.js", turn={"spec_assertions": {"a.spec.js": {"AC1": ["old"]}}})
		self.assertEqual(saved["spec_assertions"], {"a.spec.js": {"AC1": ["new"]}})

	def test_a_failed_write_records_nothing(self):
		_result, saved = run_block(AC2_SPEC, result={"error": "sandbox refused"})
		self.assertEqual(saved, {})

	def test_the_tool_script_is_valid_python_and_ends_with_the_block(self):
		compile(tools.WRITE_SPEC, "write_spec", "exec")
		self.assertTrue(tools.WRITE_SPEC.endswith(tools.RECORD_ASSERTIONS))


class TestPatch(unittest.TestCase):
	def _run(self, script):
		store = {} if script is None else {p.NAME: script}
		with patch.object(p.frappe, "db", new=MagicMock()) as db:
			db.get_value.side_effect = lambda dt, n, f: store.get(n)
			db.set_value.side_effect = lambda dt, n, f, v: store.update({n: v})
			p.execute()
		return store

	def test_a_script_without_the_block_gets_it_once(self):
		old = 'result["x"] = 1\n'
		once = self._run(old)[p.NAME]
		self.assertTrue(once.startswith(old.rstrip("\n")) and once.endswith(tools.RECORD_ASSERTIONS))
		self.assertEqual(self._run(once)[p.NAME], once)

	def test_a_script_that_already_records_is_left_alone(self):
		recorded = "update_turn(context_docname, spec_assertions=_specs)\n"
		self.assertEqual(self._run(recorded)[p.NAME], recorded)

	def test_a_site_without_the_script_gets_nothing(self):
		self.assertEqual(self._run(None), {})
