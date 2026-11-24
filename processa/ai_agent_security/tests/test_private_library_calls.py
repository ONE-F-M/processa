# Copyright (c) 2026, one-fm and contributors
"""A function whose name starts with an underscore cannot be reached through import_script."""

import unittest

from processa.ai_agent_security.code_checks.script_validator import private_library_calls

LIB = "Demo: Lib Text"


class TestPrivateLibraryCalls(unittest.TestCase):
	def test_a_private_function_reached_through_a_library_is_reported(self):
		code = f'lib = import_script("{LIB}")\nresult["n"] = len(lib._chunk_text(task_data.get("text"), 600))\n'
		self.assertEqual(private_library_calls(code), [(LIB, "_chunk_text", 2)])

	def test_a_direct_import_call_is_reported_too(self):
		code = f'result["n"] = import_script("{LIB}")._chunk_text("a b", 1)\n'
		self.assertEqual(private_library_calls(code), [(LIB, "_chunk_text", 1)])

	def test_public_functions_and_other_objects_pass(self):
		code = (
			f'lib = import_script("{LIB}")\n'
			'result["n"] = len(lib.chunk_text("a b", 1))\n'
			'result["d"] = doc._doc_before_save\n'
		)
		self.assertEqual(private_library_calls(code), [])
