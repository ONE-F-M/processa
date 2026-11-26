# Logix helpers that read DocType code: field checks for a draft and the controller and hook sources of a DocType.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _standard_fields():
	return frozenset(
		frappe.model.default_fields + frappe.model.child_table_fields + frappe.model.optional_fields
	)


def _doc_loaders():
	return ("get_doc", "new_doc", "get_cached_doc", "get_last_doc")


def _field_queries():
	return {
		"get_all": "fields",
		"get_list": "fields",
		"get_value": "fieldname",
		"get_values": "fieldname",
		"set_value": "fieldname",
		"exists": None,
		"count": None,
		"delete": None,
	}


def _index_cache_key():
	return "lucrusher_codebase_index_v3"


def _index_ttl():
	return 3600


def _hook_keys():
	return frozenset(
		{
			"doc_events",
			"override_doctype_class",
			"scheduler_events",
			"override_whitelisted_methods",
			"permission_query_conditions",
			"has_permission",
		}
	)


def _fallback_apps():
	return ("frappe", "erpnext", "one_fm", "hrms", "processa", "onefm_mcp")


def _structural_re():
	import re

	return re.compile(
		r"^\s*(if|elif|else|for|while|try|except|finally|return|raise)\b"
		r"|frappe\.throw|frappe\.db\.|frappe\.(get_doc|new_doc|get_all|get_list)\("
		r"|\.(save|insert|submit|cancel|delete)\(|\bself\.\w+\("
	)


def _link_calls():
	return {
		"enqueue": "enqueue",
		"publish_realtime": "realtime",
		"send_message": "message",
		"new_doc": "creates",
	}


def field_findings(code: str, turn: dict) -> list[dict]:
	"""A finding for each field the script reads or writes that its DocType does not have."""
	import ast

	try:
		tree = ast.parse(code)
	except SyntaxError:
		return []
	lines = code.splitlines()
	bound = {"doc": turn.get("doc_doctype")} if turn.get("doc_doctype") else {}
	for node in ast.walk(tree):
		if not isinstance(node, ast.Assign) or len(node.targets) != 1:
			continue
		doctype = _loaded_doctype(node.value)
		if doctype and isinstance(node.targets[0], ast.Name):
			bound[node.targets[0].id] = doctype

	findings, seen = [], set()
	for node in ast.walk(tree):
		for doctype, field in _used_fields(node, bound):
			if (doctype, field) in seen:
				continue
			seen.add((doctype, field))
			finding = _field_finding(doctype, field)
			if finding:
				findings.append(dict(finding, line=node.lineno, code=lines[node.lineno - 1].strip()))
	return findings


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


def _loaded_doctype(value) -> str | None:
	"""The DocType of frappe.get_doc("X", ...), frappe.new_doc("X") or frappe.get_doc({"doctype": "X", ...})."""
	import ast

	if not (
		isinstance(value, ast.Call)
		and isinstance(value.func, ast.Attribute)
		and value.func.attr in _doc_loaders()
	):
		return None
	first = value.args[0] if value.args else None
	if isinstance(first, ast.Dict):
		return _dict_doctype(first)
	return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def _used_fields(node, bound: dict):
	"""(DocType, field) pairs a node reads or writes."""
	import ast

	owner = node.value.id if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) else None
	if owner in bound:
		if not hasattr(frappe.model.document.Document, node.attr):
			yield bound[owner], node.attr
	elif isinstance(node, ast.Dict) and _dict_doctype(node):
		doctype = _dict_doctype(node)
		for key in node.keys:
			if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value != "doctype":
				yield doctype, key.value
	elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
		yield from _called_fields(node, bound)


def _called_fields(node: "ast.Call", bound: dict):
	import ast

	func = node.func
	if (
		isinstance(func.value, ast.Name)
		and func.value.id in bound
		and func.attr in ("get", "set", "db_set", "append")
	):
		if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
			yield bound[func.value.id], node.args[0].value
		return
	if func.attr in _doc_loaders() and node.args and isinstance(node.args[0], ast.Constant):
		yield node.args[0].value, None
		return
	if func.attr not in _field_queries() or not node.args:
		return
	doctype = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
	if not isinstance(doctype, str):
		return
	yield doctype, None
	keyword = {k.arg: k.value for k in node.keywords}
	filters = keyword.get("filters") or (node.args[1] if len(node.args) > 1 else None)
	fields = keyword.get(_field_queries()[func.attr]) if _field_queries()[func.attr] else None
	if fields is None and func.attr in ("get_value", "get_values") and len(node.args) > 2:
		fields = node.args[2]
	if fields is None and func.attr == "set_value" and len(node.args) > 2:
		fields = node.args[2]
	for value in (filters, fields, keyword.get("pluck")):
		for field in _field_names(value):
			yield doctype, field


def _field_names(node) -> list[str]:
	"""Field names in a literal fields list, field name, filters dict or filters list."""
	import ast

	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return [node.value]
	if isinstance(node, ast.Dict):
		return [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
	if isinstance(node, (ast.List, ast.Tuple)):
		names = []
		for item in node.elts:
			if not isinstance(item, (ast.List, ast.Tuple)):
				names.extend(_field_names(item))
				continue
			# A filter row is [field, op, value] or [doctype, field, op, value].
			entry = item.elts[1 if len(item.elts) == 4 else 0] if item.elts else None
			if isinstance(entry, ast.Constant) and isinstance(entry.value, str):
				names.append(entry.value)
		return names
	return []


def _field_finding(doctype: str, field: str | None) -> dict | None:
	"""A finding when the DocType does not exist, or the field is not one of its fields."""
	if not _is_doctype(doctype):
		return {
			"category": "Field check",
			"name": doctype,
			"rule": f"{doctype} is not a DocType on this site. Do not guess one; ask which DocType the person means.",
		}
	field = (field or "").split(" as ")[0].strip()
	if not field or field in _standard_fields():
		return None
	if any(c in field for c in "(*`."):
		return None
	if frappe.get_meta(doctype).has_field(field):
		return None
	return {
		"category": "Field check",
		"name": field,
		"rule": f"{field} is not a field of {doctype}. Use one of its fields, or ask which field the person means.",
	}


def _is_doctype(name: str) -> bool:
	return bool(name) and bool(frappe.db.exists("DocType", name))


def _dict_doctype(node: "ast.Dict") -> str | None:
	import ast

	for key, value in zip(node.keys, node.values, strict=True):
		if isinstance(key, ast.Constant) and key.value == "doctype" and isinstance(value, ast.Constant):
			return value.value
	return None


def get_apps_root() -> str:
	"""Absolute path to the bench's ``apps/`` directory."""
	import os

	# frappe.get_app_path('frappe') -> .../bench/apps/frappe/frappe
	return os.path.dirname(os.path.dirname(frappe.get_app_path("frappe")))


def _installed_apps() -> list:
	try:
		return frappe.get_installed_apps()
	except Exception:
		return list(_fallback_apps())


def _module_app_map(apps_root: str, installed_apps: list) -> dict:
	"""``{module_name: app_name}``.

	Prefers Frappe's runtime mapping (populated at request startup); falls back
	to reading each app's modules.txt, which is what background workers need.
	"""
	import os

	runtime_map = getattr(frappe.local, "module_app", None) or {}
	if runtime_map:
		return dict(runtime_map)

	mapping = {}
	for app in installed_apps:
		modules_txt = os.path.join(apps_root, app, app, "modules.txt")
		if not os.path.isfile(modules_txt):
			continue
		try:
			with open(modules_txt, encoding="utf-8", errors="ignore") as fh:
				for raw_line in fh:
					module = raw_line.strip()
					if module:
						mapping[module] = app
		except Exception:
			pass
	return mapping


def _doctypes(module_app: dict, apps_root: str) -> list:
	"""Every DocType with its app, module and conventional file paths.

	``py_exists`` is resolved here so callers never need an isfile() of their
	own (they cannot make one).
	"""
	import os

	entries = []
	try:
		doctypes = frappe.get_all("DocType", fields=["name", "module", "istable"])
	except Exception:
		frappe.log_error(title="Codebase index - DocType scan", message=frappe.get_traceback())
		return entries

	for dt in doctypes:
		name = (dt.get("name") or "").strip()
		module = (dt.get("module") or "").strip()
		if not name:
			continue
		app = module_app.get(frappe.scrub(module)) or module_app.get(module, "")
		snake_name = name.lower().replace(" ", "_")
		module_snake = module.lower().replace(" ", "_")
		json_file = py_file = ""
		if app:
			base = f"{app}/{app}/{module_snake}/doctype/{snake_name}/{snake_name}"
			json_file = f"{base}.json"
			py_file = f"{base}.py"
		entries.append(
			{
				"name": name,
				"app": app,
				"module": module,
				"file": json_file,
				"py_file": py_file,
				"py_exists": bool(py_file) and os.path.isfile(os.path.join(apps_root, py_file)),
				"istable": bool(dt.get("istable")),
			}
		)
	return entries


def _parse_hooks_py(hooks_path: str) -> dict:
	"""Read the hook keys out of a hooks.py with ``ast.literal_eval``.

	The file is never imported or executed.
	"""
	import ast

	out = {}
	try:
		with open(hooks_path, encoding="utf-8", errors="ignore") as fh:
			source = fh.read()
		tree = ast.parse(source, filename=hooks_path)
		for node in ast.walk(tree):
			if not isinstance(node, ast.Assign):
				continue
			for target in node.targets:
				if not (isinstance(target, ast.Name) and target.id in _hook_keys()):
					continue
				try:
					out[target.id] = ast.literal_eval(node.value)
				except (ValueError, TypeError):
					pass
	except SyntaxError:
		pass  # a hooks.py that does not parse is skipped silently
	except Exception:
		frappe.log_error(
			title="Codebase index - hooks.py parse error",
			message=f"File: {hooks_path}\n{frappe.get_traceback()}",
		)
	return out


def _hooks(apps_root: str, installed_apps: list) -> list:
	"""Flatten every installed app's hooks into
	``{hook_type, doctype, event, method, app}`` rows."""
	import os

	entries = []
	for app in installed_apps:
		hooks_path = os.path.join(apps_root, app, app, "hooks.py")
		if not os.path.isfile(hooks_path):
			continue
		hooks = _parse_hooks_py(hooks_path)

		# doc_events: {DocType: {event: [method, ...]}}
		for doctype, events in (hooks.get("doc_events") or {}).items():
			if not isinstance(events, dict):
				continue
			for event, methods in events.items():
				if isinstance(methods, str):
					methods = [methods]
				for method in methods or []:
					entries.append(
						{
							"hook_type": "doc_events",
							"doctype": doctype,
							"event": event,
							"method": method,
							"app": app,
						}
					)

		# override_doctype_class: {DocType: 'module.ClassName'}
		for doctype, class_path in (hooks.get("override_doctype_class") or {}).items():
			entries.append(
				{
					"hook_type": "override_doctype_class",
					"doctype": doctype,
					"event": "class_override",
					"method": class_path,
					"app": app,
				}
			)

		# override_whitelisted_methods: {old_path: new_path}
		for old_path, new_path in (hooks.get("override_whitelisted_methods") or {}).items():
			entries.append(
				{
					"hook_type": "override_whitelisted_methods",
					"doctype": "",
					"event": "method_override",
					"method": new_path,
					"app": app,
					"replaces": old_path,
				}
			)

		# scheduler_events: {'daily': [...]} or {'cron': {'expr': [...]}}
		for schedule_type, schedule_data in (hooks.get("scheduler_events") or {}).items():
			if isinstance(schedule_data, list):
				for method in schedule_data:
					entries.append(
						{
							"hook_type": "scheduler_events",
							"doctype": "",
							"event": schedule_type,
							"method": method,
							"app": app,
						}
					)
			elif isinstance(schedule_data, dict):
				for cron_expr, methods in schedule_data.items():
					if isinstance(methods, str):
						methods = [methods]
					for method in methods or []:
						entries.append(
							{
								"hook_type": "scheduler_events",
								"doctype": "",
								"event": f"cron({cron_expr})",
								"method": method,
								"app": app,
							}
						)
	return entries


def build_codebase_index() -> dict:
	"""Build the raw index. Slow; prefer :func:`get_codebase_index`."""
	apps_root = get_apps_root()
	installed_apps = _installed_apps()
	module_app = _module_app_map(apps_root, installed_apps)
	return {
		"apps_root": apps_root,
		"apps_scanned": installed_apps,
		"doctypes": _doctypes(module_app, apps_root),
		"hooks": _hooks(apps_root, installed_apps),
	}


def get_codebase_index() -> dict:
	"""The cached raw index, rebuilt when absent or expired."""
	try:
		cached = frappe.cache.get_value(_index_cache_key())
		if cached:
			return cached
	except Exception:
		pass

	index = build_codebase_index()

	try:
		frappe.cache.set_value(_index_cache_key(), index, expires_in_sec=_index_ttl())
	except Exception:
		pass  # a cache write failure is not fatal
	return index


def _cross_process_calls(node) -> list:
	"""Calls in a function that start work elsewhere: enqueue, realtime publish, BPMN message, or a new document."""
	import ast

	found = []
	for call in ast.walk(node):
		if not isinstance(call, ast.Call):
			continue
		name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
		if name not in _link_calls():
			continue
		keyword = next(
			(k.value for k in call.keywords if k.arg in ("method", "message_name", "doctype")), None
		)
		target = call.args[0] if call.args else keyword
		found.append(
			{
				"kind": _link_calls()[name],
				"target": ast.unparse(target) if target else "",
				"line": call.lineno,
			}
		)
	return found


def _function_info(node, src_lines: list, limit: int) -> dict:
	"""Name, lines and a body without docstring, comments or blanks, cut to ``limit`` lines.

	A body over the limit keeps its def line and the structural lines (control flow, throws,
	database and document calls) so decisions deep inside a long method survive.
	"""
	import ast

	skip = set()
	first = node.body[0]
	if (
		isinstance(first, ast.Expr)
		and isinstance(first.value, ast.Constant)
		and isinstance(first.value.value, str)
	):
		skip = set(range(first.lineno, first.end_lineno + 1))
	kept = []
	for number in range(node.lineno, node.end_lineno + 1):
		text = src_lines[number - 1].rstrip()
		if number in skip or not text.strip() or text.strip().startswith("#"):
			continue
		kept.append(text)
	full_lines = len(kept)
	if full_lines > limit:
		kept = kept[:1] + [line for line in kept[1:] if _structural_re().search(line)][: limit - 1]
	return {
		"name": node.name,
		"line": node.lineno,
		"end_line": node.end_lineno,
		"whitelisted": any("frappe.whitelist" in ast.unparse(d) for d in node.decorator_list),
		"body": "\n".join(kept),
		"links": _cross_process_calls(node),
		"trimmed": full_lines > limit,
		"full_lines": full_lines,
	}


def _parse_python(abs_path: str):
	"""``(tree, source_lines)`` of a python file."""
	import ast

	with open(abs_path, encoding="utf-8", errors="ignore") as fh:
		source = fh.read()
	return ast.parse(source, filename=abs_path), source.splitlines()


def _functions_of(body: list, src_lines: list, limit: int) -> list:
	import ast

	return [
		_function_info(n, src_lines, limit)
		for n in body
		if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
	]


def _read_controller(abs_path: str, doctype: str, limit: int) -> dict:
	"""The DocType class methods and every module-level function of a controller file."""
	import ast

	tree, src_lines = _parse_python(abs_path)
	class_name = "".join(word.title() for word in doctype.split())
	classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
	controller = next((c for c in classes if c.name == class_name), classes[0] if classes else None)
	return {
		"class": controller.name if controller else "",
		"methods": _functions_of(controller.body, src_lines, limit) if controller else [],
		"module_functions": _functions_of(tree.body, src_lines, limit),
	}


def _resolve_dotted(apps_root: str, dotted: str):
	"""``(abs_path, attribute_name)`` for a dotted path from a hooks.py, or ``("", "")``."""
	import os

	parts = dotted.split(".")
	if len(parts) < 2:
		return "", ""
	abs_path = os.path.join(apps_root, parts[0], *parts[:-1]) + ".py"
	return (abs_path, parts[-1]) if os.path.isfile(abs_path) else ("", "")


def _module_function(tree, name: str):
	import ast

	return next(
		(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
		None,
	)


def _hook_entry(apps_root: str, hook: dict, limit: int) -> dict:
	"""A hook row plus the trimmed body of the function (or override class methods) it names."""
	import ast
	import os

	entry = {key: hook.get(key) for key in ("hook_type", "event", "method", "app")}
	abs_path, name = _resolve_dotted(apps_root, hook.get("method") or "")
	if not abs_path:
		entry["message"] = "source file not found"
		return entry
	tree, src_lines = _parse_python(abs_path)
	entry["file"] = os.path.relpath(abs_path, apps_root)
	if hook.get("hook_type") == "override_doctype_class":
		node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name), None)
		entry["methods"] = _functions_of(node.body, src_lines, limit) if node else []
		return entry
	node = _module_function(tree, name)
	if node is None:
		entry["message"] = "function not found in file"
		return entry
	entry.update(_function_info(node, src_lines, limit))
	return entry


def _targets_doctype(apps_root: str, hook: dict, doctype: str, controller_path: str) -> bool:
	"""Whether a scheduler method lives in the DocType's controller or names the DocType."""
	import ast

	abs_path, name = _resolve_dotted(apps_root, hook.get("method") or "")
	if not abs_path:
		return False
	if abs_path == controller_path:
		return True
	node = _module_function(_parse_python(abs_path)[0], name)
	return node is not None and any(
		isinstance(n, ast.Constant) and n.value == doctype for n in ast.walk(node)
	)


def read_doctype_sources(doctype_names: list, body_lines: int = 60) -> list:
	"""Controller, hook and scheduler source for each DocType name, as one raw dict each.

	Paths come from the index, never from the name. A DocType without a controller file or
	unknown to the index is reported in ``status`` and ``message``.
	"""
	import os

	index = get_codebase_index()
	apps_root = get_apps_root()
	by_name = {dt["name"].lower(): dt for dt in index["doctypes"]}
	out = []
	for requested in doctype_names:
		dt = by_name.get(str(requested).strip().lower())
		if not dt:
			out.append(
				{
					"doctype": requested,
					"status": "unknown_doctype",
					"message": "DocType not found in any installed app",
				}
			)
			continue
		name = dt["name"]
		if not dt.get("py_exists"):
			out.append(
				{
					"doctype": name,
					"status": "no_controller_file",
					"message": "no controller file in any app (the DocType may be defined in the database only)",
					"hooks": [],
				}
			)
			continue
		controller_path = os.path.join(apps_root, dt["py_file"])
		item = {"doctype": name, "status": "read", "app": dt["app"], "file": dt["py_file"]}
		item.update(_read_controller(controller_path, name, body_lines))
		hooks = [
			h
			for h in index["hooks"]
			if h.get("doctype") == name and h["hook_type"] in ("doc_events", "override_doctype_class")
		]
		hooks += [
			h
			for h in index["hooks"]
			if h["hook_type"] == "scheduler_events" and _targets_doctype(apps_root, h, name, controller_path)
		]
		item["hooks"] = [_hook_entry(apps_root, h, body_lines) for h in hooks]
		item["star_hooks"] = sum(1 for h in index["hooks"] if h.get("doctype") == "*")
		out.append(item)
	return out
