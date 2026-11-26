# Logix helpers that read the turn: the script under debug, its last error, the DocTypes a request is about.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _code_fence():
	import re

	return re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.DOTALL)


def _traceback():
	return "Traceback (most recent call last)"


def _error_chars():
	return 3000


def _engine_error_title():
	return 'BPMN ScriptTask: "{}" execution failed'


def _check_error_title():
	return 'Logix check: "{}" failed'


def _max_doctypes():
	return 3


def _named_doctype():
	import re

	return re.compile(r"((?:[A-Z][\w-]*\s+){0,3}[A-Z][\w-]*)\s+((?i:doctype|record|records|form))\b")


def _referred_doctype():
	import re

	return re.compile(r"\b(this|the|each|every|an?|for)\s+((?:[A-Z][\w-]*\s+){0,3}[A-Z][\w-]*)")


def debug_inputs(user_text: str, original_script_content: str, current_script: str) -> dict:
	"""The script under debug and its newest error; what the person pasted wins over the saved script."""
	user_text = user_text or ""
	script_text = _saved_script(current_script) or original_script_content or ""
	for block in _code_fence().findall(user_text):
		if _traceback() not in block:
			script_text = block.strip()
			break

	at = user_text.find(_traceback())
	last_error = user_text[at:][-_error_chars() :] if at != -1 else _logged_error(current_script)
	return {"script_text": script_text, "last_error": last_error}


def _saved_script(script_name: str) -> str:
	return (script_name and frappe.db.get_value("Server Script", script_name, "script")) or ""


def _logged_error(script_name: str) -> str:
	"""The newest Error Log raised by this script, whichever path ran it, with when it and the script were saved."""
	if not script_name:
		return ""
	rows = frappe.get_all(
		"Error Log",
		or_filters=[
			["method", "=", _engine_error_title().format(script_name)],
			["method", "=", _check_error_title().format(script_name)],
			[
				"error",
				"like",
				f'%{frappe.utils.safe_exec.SERVER_SCRIPT_FILE_PREFIX}: {frappe.scrub(script_name)}"%',
			],
		],
		fields=["error", "creation"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return ""
	saved = frappe.db.get_value("Server Script", script_name, "modified")
	return (
		f"Logged {rows[0].creation}; the script was last saved {saved}.\n{rows[0].error[-_error_chars() :]}"
	)


def doctype_inputs(user_text: str, process_context: dict | None, current_script: str) -> dict:
	"""The fields of each DocType the turn is about, and the DocTypes it names that do not exist."""
	names, missing = _turn_doctypes(user_text or "", process_context or {}, current_script)
	return {
		"doctype_fields": {name: field_list(name) for name in names},
		"missing_doctypes": missing,
		"doc_doctype": _trigger_doctype(process_context or {}) or _this_doctype(user_text or ""),
	}


def field_list(doctype: str) -> dict:
	"""The data fields of a DocType and of each of its child tables."""
	meta = frappe.get_meta(doctype)
	return {
		"fields": [f.fieldname for f in meta.fields if f.fieldtype not in frappe.model.display_fieldtypes],
		"child_tables": {
			f.fieldname: {
				"doctype": f.options,
				"fields": [
					c.fieldname
					for c in frappe.get_meta(f.options).fields
					if c.fieldtype not in frappe.model.display_fieldtypes
				],
			}
			for f in meta.get_table_fields()
		},
	}


def _turn_doctypes(user_text: str, process_context: dict, current_script: str) -> tuple[list[str], list[str]]:
	"""The start event's DocType, the linked script's and those the request names, in that order."""
	candidates = [_trigger_doctype(process_context)]
	if current_script:
		candidates.append(frappe.db.get_value("Server Script", current_script, "reference_doctype"))
	missing = []
	for match in _named_doctype().finditer(user_text):
		words = match.group(1).split()
		found = next(
			(" ".join(words[i:]) for i in range(len(words)) if _is_doctype(" ".join(words[i:]))), None
		)
		if found:
			candidates.append(found)
		elif match.group(2).lower() == "doctype":
			missing.append(match.group(1))
	for match in _referred_doctype().finditer(user_text):
		candidates.append(_leading_doctype(match.group(2).split()))
	names = []
	for name in candidates:
		if not name or name in names:
			continue
		if _is_doctype(name):
			names.append(name)
		elif name not in missing:
			missing.append(name)
	return names[: _max_doctypes()], missing


def _this_doctype(user_text: str) -> str | None:
	"""The DocType the request calls "this X": the record the script task runs on."""
	for match in _referred_doctype().finditer(user_text):
		if match.group(1).lower() == "this":
			found = _leading_doctype(match.group(2).split())
			if found:
				return found
	return None


def _leading_doctype(words: list[str]) -> str | None:
	"""The longest run of leading words that names a DocType."""
	return next(
		(" ".join(words[:i]) for i in range(len(words), 0, -1) if _is_doctype(" ".join(words[:i]))), None
	)


def _trigger_doctype(process_context: dict) -> str | None:
	process_id = process_context.get("process_name")
	return process_id and frappe.db.get_value(
		"BPMN Process Model", {"process_id": process_id}, "trigger_doctype", order_by="modified desc"
	)


def _is_doctype(name: str) -> bool:
	return bool(name) and bool(frappe.db.exists("DocType", name))


def _python_block():
	import re

	return re.compile(r"(```python\s*\n)(.*?)(```)", re.DOTALL)


def reply_with_code(text: str, code: str) -> str:
	"""The reply text with its first python block replaced by code, so what is shown is what gets applied."""
	if not code:
		return text
	block = code.rstrip("\n") + "\n"
	if _python_block().search(text):
		return _python_block().sub(lambda m: m.group(1) + block + m.group(3), text, count=1)
	return text.rstrip() + "\n\n```python\n" + block + "```"
