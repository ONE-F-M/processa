# Copyright (c) 2026, one-fm and contributors
"""The review step keeps the lines the writer kept from the existing script."""

import ast
import re
import textwrap

from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import logix_review_keeps_kept_lines as p

ORIGINAL = (
	"# Posts the url and body.\n"
	"lib = import_script('Demo: Lib HTTP')\n"
	'doc = frappe.get_last_doc("Employee")\n'
	"lib2 = import_script('Demo: Lib Replies')\n"
	'response = lib.post_json(task_data.get("url"), task_data.get("body"))\n'
	'result["status_code"] = response.status_code\n'
)
DRAFT_CODE = ORIGINAL + 'result["chunk_count"] = len((task_data.get("text") or "").split())\n'
DRAFT = "I left the doc and lib2 lines alone.\n\n```python\n" + DRAFT_CODE + "```\n"


def _apply(revised: str, original: str = ORIGINAL) -> str:
	namespace = {
		"re": re,
		"ast": ast,
		"draft": DRAFT,
		"_review": {"revised_script": revised},
		"turn": {"original_script_content": original},
	}
	exec(textwrap.dedent(p.OLD + p.RESTORE), namespace)
	return namespace["_revised"]


class TestLogixReviewKeepsKeptLines(FrappeTestCase):
	def test_lines_the_reviewer_dropped_from_the_existing_script_come_back_in_place(self):
		revised = "\n".join(
			line for line in DRAFT_CODE.splitlines() if not line.startswith(("doc =", "lib2 ="))
		)
		self.assertEqual(_apply(revised), DRAFT_CODE.rstrip("\n"))

	def test_the_reviewers_own_changes_to_new_lines_still_apply(self):
		revised = DRAFT_CODE.replace(".split())", ".split()) or 0")
		self.assertIn(".split()) or 0", _apply(revised))
		self.assertNotIn(".split())\n", _apply(revised) + "\n")

	def test_a_new_line_the_reviewer_dropped_stays_dropped(self):
		revised = ORIGINAL.rstrip("\n")
		self.assertEqual(_apply(revised), ORIGINAL.rstrip("\n"))

	def test_the_patch_inserts_once(self):
		code = "x\n" + p.OLD + "y\n"
		once = p.restored(code)
		self.assertEqual(once.count("_kept_from_original = set()"), 1)
		self.assertIn(p.OLD + p.RESTORE + "y\n", once)
