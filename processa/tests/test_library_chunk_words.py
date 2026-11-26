# Copyright (c) 2026, one-fm and contributors
"""Library data files define each function once, so search_dms_documents can split a document into chunks."""

import ast
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import libraries_chunk_word_count_refresh as refresh
from processa.patches.v1_0.logix_helpers_move_to_libraries import DATA
from processa.tests.library import library


class TestLibraryChunkWords(FrappeTestCase):
	def test_no_library_defines_a_function_twice(self):
		for path in sorted(DATA.glob("*_lib_*.py")):
			names = [n.name for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef)]
			self.assertEqual(len(names), len(set(names)), path.name)

	def test_each_library_splits_a_document_into_chunks(self):
		text = " ".join(f"w{i}" for i in range(1300))
		for data_file in refresh.LIBRARIES.values():
			chunks = library(data_file)._chunk_words(text)
			self.assertEqual(len(chunks), 3, data_file)
			self.assertTrue(chunks[0].startswith("w0 "), data_file)

	def test_refresh_writes_each_stale_library_and_skips_a_missing_one(self):
		missing = "ProsAlly: Lib Context"
		with (
			patch("frappe.db.exists", side_effect=lambda _doctype, name: name != missing),
			patch("frappe.db.get_value", return_value="old"),
			patch("frappe.db.set_value") as set_value,
		):
			refresh.execute()
		written = {call.args[1] for call in set_value.call_args_list}
		self.assertEqual(written, set(refresh.LIBRARIES) - {missing})

	def test_refresh_leaves_a_current_library_alone(self):
		with (
			patch("frappe.db.exists", return_value=True),
			patch("frappe.db.get_value", side_effect=lambda _d, name, _f: (DATA / refresh.LIBRARIES[name]).read_text()),
			patch("frappe.db.set_value") as set_value,
		):
			refresh.execute()
		set_value.assert_not_called()
