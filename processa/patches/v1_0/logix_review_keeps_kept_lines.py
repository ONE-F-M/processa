# Copyright (c) 2026, one-fm and contributors
"""Logix's review step puts back lines of the existing script that the writer kept and the reviewer dropped.

The reviewer's revised_script replaces only the code block, so the writer's reply could say it left
two lines alone while the diff deleted them. Its other changes still apply.
"""

import frappe

SCRIPT = "Logix \u2013 Tool Review Script"
OLD = (
	'            _revised = _review["revised_script"]\n'
	'            _mm = re.search(r"(```python\\s*\\n)(.*?)(```)", draft, re.DOTALL)\n'
)
RESTORE = (
	"            # Lines the writer kept from the existing script stay, so the reply still matches the code.\n"
	"            _kept_from_original = set()\n"
	'            for _ol in (turn.get("original_script_content") or "").split("\\n"):\n'
	"                if _ol.strip():\n"
	"                    _kept_from_original.add(_ol.strip())\n"
	'            _rev_lines = _revised.rstrip("\\n").split("\\n")\n'
	"            _pos = 0\n"
	'            for _dl in (_mm.group(2) if _mm else "").split("\\n"):\n'
	"                _found = False\n"
	"                for _ri in range(_pos, len(_rev_lines)):\n"
	"                    if _rev_lines[_ri].strip() == _dl.strip():\n"
	"                        _pos = _ri + 1\n"
	"                        _found = True\n"
	"                        break\n"
	"                if not _found and _dl.strip() in _kept_from_original:\n"
	"                    _rev_lines.insert(_pos, _dl)\n"
	"                    _pos += 1\n"
	'            _merged = "\\n".join(_rev_lines)\n'
	"            try:\n"
	"                ast.parse(_merged)\n"
	"                _revised = _merged\n"
	"            except SyntaxError:\n"
	"                _revised = _mm.group(2) if _mm else _revised\n"
)


def execute():
	code = frappe.db.get_value("Server Script", SCRIPT, "script")
	if not code or "_kept_from_original" in code or code.count(OLD) != 1:
		return
	frappe.db.set_value("Server Script", SCRIPT, "script", restored(code), update_modified=False)


def restored(code: str) -> str:
	"""The review script with the kept-lines step after the reviewer's revision is read."""
	return code.replace(OLD, OLD + RESTORE)
