# Docu schema helpers: read model replies, check a DocType IR, diff two IRs and merge into live fields.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _history_turns():
	return 10


def _allowed_fieldtypes():
	return frozenset(
		{
			"Data",
			"Small Text",
			"Text",
			"Long Text",
			"Text Editor",
			"Code",
			"Markdown Editor",
			"Int",
			"Float",
			"Currency",
			"Percent",
			"Check",
			"Date",
			"Datetime",
			"Time",
			"Duration",
			"Select",
			"Link",
			"Dynamic Link",
			"Table",
			"Table MultiSelect",
			"Attach",
			"Attach Image",
			"Signature",
			"Color",
			"Rating",
			"Password",
			"Read Only",
			"Phone",
			# Layout / presentational
			"Section Break",
			"Column Break",
			"Tab Break",
			"HTML",
			"Heading",
		}
	)


def _options_required():
	return frozenset(
		{
			"Link",
			"Table",
			"Table MultiSelect",
			"Dynamic Link",
			"Select",
		}
	)


def _table_fieldtypes():
	return frozenset({"Table", "Table MultiSelect"})


def _layout_fieldtypes():
	return frozenset(
		{
			"Section Break",
			"Column Break",
			"Tab Break",
		}
	)


def reserved_fieldnames():
	return frozenset(
		{
			"name",
			"owner",
			"creation",
			"modified",
			"modified_by",
			"docstatus",
			"idx",
			"parent",
			"parentfield",
			"parenttype",
			"doctype",
			"_user_tags",
			"_comments",
			"_assign",
			"_liked_by",
			"_seen",
			"amended_from",
			"amendment_date",
		}
	)


def _reserved_doctype_names():
	return frozenset(
		{
			"DocType",
			"DocField",
			"User",
			"Role",
			"Report",
			"Print Format",
		}
	)


def _fieldname_re():
	import re

	return re.compile(r"^[a-z][a-z0-9_]*$")


def _doctype_name_re():
	import re

	return re.compile(r"^[A-Za-z][A-Za-z0-9 ]*[A-Za-z0-9]$")


def _max_fields():
	return 200


def _max_permissions():
	return 40


def _fix_hint():
	return (
		"Fix every issue listed above and output the complete corrected DocType JSON. "
		"Use snake_case fieldnames, a supported fieldtype for every field, and provide "
		"'options' for Link/Table/Dynamic Link/Select fields. Do not redefine Frappe's "
		"standard fields (name, owner, creation, modified, docstatus, parent, ...)."
	)


def _diff_attrs():
	return ("label", "fieldtype", "options", "reqd", "unique", "in_list_view", "read_only", "default")


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last _history_turns() messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-_history_turns() :]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def extract_json(raw: str) -> dict | None:
	"""The first JSON object found in a model reply: whole, fenced, or embedded in prose.

	Literal newlines inside string values are accepted, since models often write them.
	"""
	import json
	import re

	if not raw:
		return None
	stripped = raw.strip()
	candidates = [stripped]
	fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
	if fenced:
		candidates.append(fenced.group(1).strip())
	greedy = re.search(r"\{[\s\S]*\}", raw)
	if greedy:
		candidates.append(greedy.group(0))
	if stripped.startswith("```"):
		unfenced = stripped.split("\n", 1)[-1]
		if unfenced.rstrip().endswith("```"):
			unfenced = unfenced.rstrip()[: unfenced.rstrip().rfind("```")]
		candidates.append(unfenced.strip())
	start = raw.find("{")
	if start != -1:
		depth = 0
		for i in range(start, len(raw)):
			if raw[i] == "{":
				depth += 1
			elif raw[i] == "}":
				depth -= 1
				if depth == 0:
					candidates.append(raw[start : i + 1])
					break
	for candidate in candidates:
		try:
			parsed = json.loads(candidate, strict=False)
		except json.JSONDecodeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None


def validate_doctype_ir(ir: dict, existing_fieldnames: set | None = None) -> dict:
	"""Validate a Docu DocType IR.

	Returns ``{valid, violations, warnings, fix_hints}``: ``violations`` and ``warnings``
	are lists of strings, and ``fix_hints`` holds one guidance string when invalid, else is empty.
	A non-dict IR returns no ``warnings`` key.

	``existing_fieldnames`` is the set of fieldnames already on the target DocType
	when customizing an existing type. Those fields are not being (re)created -
	Docu only edits their allowed properties via Customize Form (which validates
	the change itself) - so the strict new-field checks are skipped for them. This
	lets a standard DocType's own fields (e.g. the reserved ``amended_from``) pass
	through untouched while new fields are still fully validated.
	"""
	import re

	existing_fieldnames = existing_fieldnames or set()
	violations: list[str] = []

	if not isinstance(ir, dict):
		return {
			"valid": False,
			"violations": ["The DocType definition must be a JSON object."],
			"fix_hints": [_fix_hint()],
		}

	# ── DocType name ─────────────────────────────────────────────────────────
	name = (ir.get("doctype_name") or "").strip()
	if not name:
		violations.append("Missing 'doctype_name'.")
	else:
		if not _doctype_name_re().match(name):
			violations.append(
				f"DocType name '{name}' is invalid - use letters, digits and single "
				f"spaces, starting with a letter (e.g. 'Vehicle Inspection')."
			)
		if name in _reserved_doctype_names():
			violations.append(f"DocType name '{name}' collides with a Frappe core DocType.")

	# ── Fields ───────────────────────────────────────────────────────────────
	fields = ir.get("fields")
	if not isinstance(fields, list) or not fields:
		violations.append("A DocType needs a non-empty 'fields' array.")
		fields = []

	if len(fields) > _max_fields():
		violations.append(f"Too many fields ({len(fields)}); maximum is {_max_fields()}.")

	seen: set[str] = set()
	has_data_field = False
	for idx, field in enumerate(fields):
		pos = f"field #{idx + 1}"
		if not isinstance(field, dict):
			violations.append(f"{pos} is not an object.")
			continue

		fieldtype = (field.get("fieldtype") or "").strip()
		fieldname = (field.get("fieldname") or "").strip()
		label = (field.get("label") or "").strip()

		# Field already present on the target DocType (customizing an existing
		# type). Docu never redefines it here - at most it edits allowed props via
		# Customize Form, which validates the change itself. Skip the new-field
		# structural checks (allowed types, reserved names, snake_case, required
		# label/options) so a standard DocType's own fields pass through.
		if fieldname and fieldname in existing_fieldnames:
			if fieldname in seen:
				violations.append(f"{pos}: duplicate fieldname '{fieldname}'.")
			else:
				seen.add(fieldname)
			has_data_field = True
			continue

		if fieldtype not in _allowed_fieldtypes():
			violations.append(
				f"{pos}: field type '{fieldtype or '(missing)'}' is not allowed. "
				f"Use one of the supported types."
			)
			continue

		if fieldtype in _layout_fieldtypes():
			# Layout breaks don't need a fieldname/label and can repeat.
			continue

		has_data_field = True

		if not fieldname:
			violations.append(f"{pos} ({label or fieldtype}): missing 'fieldname'.")
		elif not _fieldname_re().match(fieldname):
			violations.append(
				f"{pos}: fieldname '{fieldname}' must be snake_case "
				f"(lowercase letters, digits, underscores; starting with a letter)."
			)
		elif fieldname in reserved_fieldnames():
			violations.append(
				f"{pos}: fieldname '{fieldname}' is a reserved Frappe field and cannot be redefined."
			)
		elif fieldname in seen:
			violations.append(f"{pos}: duplicate fieldname '{fieldname}'.")
		else:
			seen.add(fieldname)

		if not label:
			violations.append(f"{pos} ({fieldname or fieldtype}): missing 'label'.")

		# A Table / Table MultiSelect field is a "repeating list". It may point at an
		# existing child DocType via 'options', OR define its rows inline via
		# 'child_fields' - in which case apply_doctype auto-creates the child DocType.
		child_fields = field.get("child_fields")
		is_table = fieldtype in _table_fieldtypes()
		has_inline_child = is_table and isinstance(child_fields, list) and bool(child_fields)
		if has_inline_child:
			child_seen: set[str] = set()
			child_has_data = False
			for cidx, cf in enumerate(child_fields):
				cpos = f"{pos} → repeating-list column #{cidx + 1}"
				if not isinstance(cf, dict):
					violations.append(f"{cpos} is not an object.")
					continue
				cft = (cf.get("fieldtype") or "").strip()
				cfn = (cf.get("fieldname") or "").strip()
				clabel = (cf.get("label") or "").strip()
				if cft not in _allowed_fieldtypes():
					violations.append(f"{cpos}: field type '{cft or '(missing)'}' is not allowed.")
					continue
				if cft in _table_fieldtypes():
					violations.append(
						f"{cpos}: a repeating list cannot itself contain another repeating list."
					)
					continue
				if cft in _layout_fieldtypes():
					continue
				child_has_data = True
				if not cfn:
					violations.append(f"{cpos} ({clabel or cft}): missing 'fieldname'.")
				elif not _fieldname_re().match(cfn):
					violations.append(f"{cpos}: fieldname '{cfn}' must be snake_case.")
				elif cfn in reserved_fieldnames():
					violations.append(f"{cpos}: fieldname '{cfn}' is a reserved Frappe field.")
				elif cfn in child_seen:
					violations.append(f"{cpos}: duplicate fieldname '{cfn}'.")
				else:
					child_seen.add(cfn)
				if not clabel:
					violations.append(f"{cpos} ({cfn or cft}): missing 'label'.")
				if cft in _options_required() and not (cf.get("options") or "").strip():
					violations.append(f"{cpos} ({cfn or clabel}): a '{cft}' field requires 'options'.")
			if not child_has_data:
				violations.append(f"{pos} ({label or fieldname}): the repeating list has no data columns.")

		if (
			fieldtype in _options_required()
			and not (field.get("options") or "").strip()
			and not has_inline_child
		):
			hint = {
				"Link": "the target DocType name",
				"Table": "the child-table DocType name (or provide 'child_fields')",
				"Table MultiSelect": "the child-table DocType name (or provide 'child_fields')",
				"Dynamic Link": "the fieldname holding the target DocType",
				"Select": "newline-separated choices",
			}[fieldtype]
			violations.append(
				f"{pos} ({fieldname or label}): a '{fieldtype}' field requires 'options' ({hint})."
			)

	if fields and not has_data_field:
		violations.append("The DocType has only layout breaks and no real data fields.")

	violations.extend(_permission_violations(ir.get("permissions")))
	violations.extend(_autoname_violations(ir.get("autoname")))
	violations.extend(_fetch_from_violations(ir))

	return {
		"valid": not violations,
		"violations": violations,
		"warnings": _child_table_warnings(ir.get("fields")),
		"fix_hints": [] if not violations else [_fix_hint()],
	}


def child_table_is_editable(name: str) -> bool:
	"""True for a custom child DocType, the only kind whose columns Docu may change."""
	return bool(
		frappe.db.get_value("DocType", name, "custom") and frappe.db.get_value("DocType", name, "istable")
	)


def _child_table_warnings(fields) -> list:
	"""One line per inline column change aimed at a table Docu cannot change."""
	warnings = []
	for field in fields or []:
		if not isinstance(field, dict) or field.get("fieldtype") not in _table_fieldtypes():
			continue
		target = (field.get("options") or "").strip()
		if (
			field.get("child_fields")
			and frappe.db.exists("DocType", target)
			and not child_table_is_editable(target)
		):
			warnings.append(
				frappe._("{0} is a standard table, so Docu cannot change its columns.").format(target)
			)
	return warnings


def _autoname_violations(autoname) -> list:
	"""A format: rule fills only its braces, so a counter outside them names every record the same."""
	import re

	if not isinstance(autoname, str) or not autoname.startswith("format:"):
		return []
	if "#" not in re.sub(r"\{[^}]*\}", "", autoname):
		return []
	return [
		f"Naming rule '{autoname}' has its counter outside braces, so every record gets the same name. "
		"Use 'format:PREFIX-{#####}', or the naming series 'PREFIX-.#####' without 'format:'."
	]


def _fetch_from_violations(ir: dict) -> list:
	"""A fetch_from must name a Link field on this form and a field the linked DocType has."""
	from frappe.model import default_fields

	fields = [f for f in ir.get("fields") or [] if isinstance(f, dict)]
	links, on_site = {}, {}
	name = (ir.get("doctype_name") or "").strip()
	if name and frappe.db.exists("DocType", name):
		site_fields = frappe.get_meta(name).fields
		links = {df.fieldname: df.options for df in site_fields if df.fieldtype == "Link"}
		on_site = {df.fieldname: df.fetch_from for df in site_fields if df.fetch_from}
	for f in fields:
		if f.get("fieldtype") == "Link" and (f.get("fieldname") or "").strip():
			links[f["fieldname"].strip()] = (f.get("options") or "").strip()

	out = []
	for f in fields:
		fetch = str(f.get("fetch_from") or "").strip()
		if not fetch or on_site.get(f.get("fieldname")) == fetch:
			continue
		label = f.get("label") or f.get("fieldname") or "?"
		link, _sep, target = fetch.partition(".")
		if " " in fetch or not link or not target:
			out.append(
				frappe._("'{0}': fetch_from '{1}' must read link_field.field_name, with no spaces.").format(
					label, fetch
				)
			)
			continue
		linked = links.get(link)
		if not linked:
			out.append(
				frappe._(
					"'{0}': fetch_from '{1}' starts with '{2}', which is not a Link field on this form."
				).format(label, fetch, link)
			)
			continue
		if target not in default_fields and not (
			frappe.db.exists("DocType", linked) and frappe.get_meta(linked).has_field(target)
		):
			out.append(
				frappe._("'{0}': fetch_from '{1}' reads '{2}', which {3} does not have.").format(
					label, fetch, target, linked
				)
			)
	return out


def _permission_violations(permissions) -> list:
	"""Check the IR's permission rules name real roles and grant nothing twice.

	A role that does not exist is the failure worth catching early: Frappe would
	accept the row and the DocType would then be unreachable by the people the
	process owner meant to name.
	"""
	if permissions in (None, ""):
		return []
	if not isinstance(permissions, list):
		return ["'permissions' must be a list of permission rules."]
	if len(permissions) > _max_permissions():
		return [f"Too many permission rules ({len(permissions)}); maximum is {_max_permissions()}."]

	out, seen = [], set()
	for i, rule in enumerate(permissions, start=1):
		if not isinstance(rule, dict):
			out.append(f"Permission rule {i} must be an object.")
			continue
		role = (rule.get("role") or "").strip()
		if not role:
			out.append(f"Permission rule {i} has no role.")
			continue
		if not frappe.db.exists("Role", role):
			out.append(f"Permission rule {i}: there is no role named '{role}'.")
			continue
		try:
			level = int(rule.get("permlevel") or 0)
		except (TypeError, ValueError):
			out.append(f"Permission rule {i} ('{role}'): level must be a whole number.")
			continue
		if level < 0 or level > 9:
			out.append(f"Permission rule {i} ('{role}'): level must be between 0 and 9.")
			continue
		# Frappe pairs two rules for one role at one level to mean "anyone may
		# read, only the owner may edit", so if_owner is part of what makes a
		# rule distinct. Note and Kanban Board ship exactly that shape.
		owner_only = int(bool(rule.get("if_owner")))
		if (role, level, owner_only) in seen:
			out.append(f"Permission rule {i}: '{role}' already has this rule at level {level}.")
		seen.add((role, level, owner_only))
	return out


def validate_doctype_json(ir: str = "{}") -> str:
	"""Tool wrapper: parse the IR JSON string and run the schema-safety gate."""
	import json

	try:
		data = json.loads(ir) if isinstance(ir, str) else ir
	except (json.JSONDecodeError, TypeError, ValueError) as exc:
		return json.dumps({"valid": False, "violations": [f"Not valid JSON: {exc}"], "fix_hints": []})
	return json.dumps(validate_doctype_ir(data))


def _field_index(ir: dict) -> dict:
	"""Map fieldname to field dict for every IR field that has a fieldname."""
	out = {}
	for f in ir.get("fields") or []:
		fn = (f.get("fieldname") or "").strip()
		if fn:
			out[fn] = f
	return out


def diff_ir(original: dict, modified: dict) -> dict:
	"""Field-level diff between two DocType IRs: added, removed, changed and a short summary for a chat bubble."""
	orig = _field_index(original or {})
	new = _field_index(modified or {})

	added = [new[fn] for fn in new if fn not in orig]
	removed = [orig[fn] for fn in orig if fn not in new]
	changed = []
	for fn in new:
		if fn not in orig:
			continue
		before, after = orig[fn], new[fn]
		attr_changes = {}
		for attr in _diff_attrs():
			b, a = before.get(attr), after.get(attr)
			if (b or "") != (a or "") and b != a:
				attr_changes[attr] = {"from": b, "to": a}
		if attr_changes:
			changed.append({"fieldname": fn, "changes": attr_changes})

	lines = []
	for f in added:
		lines.append(f"+ add field '{f.get('label') or f.get('fieldname')}' ({f.get('fieldtype')})")
	for f in removed:
		lines.append(f"- remove field '{f.get('label') or f.get('fieldname')}'")
	for c in changed:
		attrs = ", ".join(f"{k}: {v['from']!r}→{v['to']!r}" for k, v in c["changes"].items())
		lines.append(f"~ change '{c['fieldname']}' ({attrs})")

	return {"added": added, "removed": removed, "changed": changed, "summary": "\n".join(lines)}


def merge_into_live_fields(current_ir: dict, proposed_ir: dict) -> None:
	"""Make a proposed field that repeats a live one, by fieldname or by label under a new fieldname, an update of it."""
	live = {}
	for field in current_ir.get("fields") or []:
		label = (field.get("label") or "").strip().lower()
		if label and field.get("fieldname") and field.get("fieldtype") not in frappe.model.display_fieldtypes:
			live.setdefault(label, field["fieldname"])
	live_names = set(live.values())
	by_name = {}
	merged = []
	for field in proposed_ir.get("fields") or []:
		fieldname = field.get("fieldname")
		label = (field.get("label") or "").strip().lower()
		if (
			field.get("fieldtype") not in frappe.model.display_fieldtypes
			and fieldname not in live_names
			and label in live
		):
			field = {**field, "fieldname": live[label]}
			fieldname = field["fieldname"]
		if fieldname in by_name and field.get("fieldtype") not in frappe.model.display_fieldtypes:
			by_name[fieldname].update(field)
			continue
		if fieldname:
			by_name[fieldname] = field
		merged.append(field)
	proposed_ir["fields"] = merged


def _docfield_flags():
	return (
		"reqd",
		"unique",
		"in_list_view",
		"in_standard_filter",
		"in_global_search",
		"in_preview",
		"in_filter",
		"allow_in_quick_entry",
		"bold",
		"translatable",
		"fetch_if_empty",
		"hidden",
		"read_only",
		"search_index",
		"set_only_once",
		"allow_bulk_edit",
		"ignore_user_permissions",
		"allow_on_submit",
		"report_hide",
		"remember_last_selected_value",
		"ignore_xss_filter",
		"no_copy",
		"print_hide",
		"print_hide_if_no_value",
		"hide_days",
		"hide_seconds",
		"non_negative",
		"is_virtual",
		"sort_options",
		"show_on_timeline",
		"make_attachment_public",
		"collapsible",
	)


def _docfield_ints():
	return ("length", "columns", "permlevel")


def _docfield_strs():
	return (
		"options",
		"default",
		"description",
		"depends_on",
		"mandatory_depends_on",
		"read_only_depends_on",
		"fetch_from",
		"precision",
		"print_width",
		"width",
		"max_height",
		"documentation_url",
		"placeholder",
	)


def _doctype_setting_flags():
	return (
		"is_submittable",
		"issingle",
		"editable_grid",
		"quick_entry",
		"track_changes",
		"track_seen",
		"track_views",
		"beta",
		"hide_toolbar",
		"allow_copy",
		"allow_rename",
		"allow_import",
		"allow_events_in_timeline",
		"allow_auto_repeat",
		"show_preview_popup",
		"show_name_in_global_search",
		"show_title_field_in_link",
		"translated_doctype",
		"make_attachments_public",
		"is_tree",
	)


def _doctype_setting_strs():
	return (
		"description",
		"image_field",
		"title_field",
		"search_fields",
		"default_print_format",
		"sort_field",
		"sort_order",
		"document_type",
	)


def _doctype_permission_flags():
	return (
		"select",
		"read",
		"write",
		"create",
		"delete",
		"submit",
		"cancel",
		"amend",
		"report",
		"export",
		"import",
		"share",
		"print",
		"email",
		"if_owner",
	)


def timed(timings: list, call: str):
	"""A with-block that appends when it started and ended, and its length in ms, to timings."""
	import time

	class _Timed:
		def __enter__(self):
			self.started_at = frappe.utils.now_datetime()
			self.t0 = time.perf_counter()

		def __exit__(self, *exc):
			timings.append(
				{
					"call": call,
					"started_at": str(self.started_at),
					"ended_at": str(frappe.utils.now_datetime()),
					"ms": round((time.perf_counter() - self.t0) * 1000),
				}
			)
			return False

	return _Timed()


def _enveloped(title: str, fallback, tool, *args):
	"""tool(*args); on an error, log it under title and return fallback(*args), since a Server Script cannot catch it."""
	try:
		return tool(*args)
	except Exception:
		frappe.log_error(title=title, message=frappe.get_traceback())
		return fallback(*args)


def list_doctypes(search: str = "") -> str:
	"""Up to 50 non-child DocTypes (name, module, custom), newest modified first, optionally filtered by *search*."""
	import json

	def read(search):
		filters = {"istable": 0}
		if search:
			filters["name"] = ["like", f"%{search}%"]
		rows = frappe.get_all(
			"DocType",
			filters=filters,
			fields=["name", "module", "custom"],
			order_by="modified desc",
			limit_page_length=50,
		)
		return json.dumps(rows)

	return _enveloped("Docu Tool - list_doctypes", lambda search: json.dumps([]), read, search)


def doctype_exists(doctype: str) -> str:
	"""Return whether a DocType exists and whether it is a custom DocType."""
	import json

	def read(doctype):
		exists = bool(frappe.db.exists("DocType", doctype))
		is_custom = bool(frappe.db.get_value("DocType", doctype, "custom")) if exists else False
		return json.dumps({"exists": exists, "custom": is_custom})

	return _enveloped(
		"Docu Tool - doctype_exists",
		lambda doctype: json.dumps({"exists": False, "custom": False}),
		read,
		doctype,
	)


def list_roles(search: str = "") -> str:
	"""Role names a permission rule may name, as JSON, filtered by the search substring."""
	import json

	def read(search):
		filters = {"disabled": 0, "name": ["not in", ("All", "Guest")]}
		if (search or "").strip():
			filters["name"] = ["like", f"%{search.strip()}%"]
		names = frappe.get_all("Role", filters=filters, pluck="name", order_by="name asc", limit=400)
		return json.dumps({"roles": names})

	return _enveloped(
		"Docu Tool - list_roles",
		lambda search: json.dumps({"roles": [], "error": "Could not read the role list."}),
		read,
		search,
	)


def get_doctype_definition(doctype: str) -> str:
	"""Full definition (every field + all its properties + naming) of a DocType, as JSON."""
	import json

	def read(doctype):
		ir = read_doctype_definition(doctype)
		if ir is None:
			return json.dumps({"error": f"DocType '{doctype}' does not exist."})
		return json.dumps(ir)

	return _enveloped(
		"Docu Tool - get_doctype_definition",
		lambda doctype: json.dumps({"error": f"Failed to read DocType '{doctype}'."}),
		read,
		doctype,
	)


def get_doctype_fields(doctype: str) -> str:
	"""The fieldname, fieldtype, label and reqd of each DocType field except Section Break, Column Break, HTML and Heading, as JSON."""
	import json

	def read(doctype):
		if not frappe.db.exists("DocType", doctype):
			return json.dumps({"error": f"DocType '{doctype}' does not exist."})
		fields = [
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label or f.fieldname,
				"reqd": bool(f.reqd),
			}
			for f in frappe.get_meta(doctype).fields
			if f.fieldtype not in ("Section Break", "Column Break", "HTML", "Heading")
		]
		return json.dumps(fields)

	return _enveloped(
		"Logix Tool - get_doctype_fields",
		lambda doctype: json.dumps({"error": f"Failed to fetch fields for DocType '{doctype}'."}),
		read,
		doctype,
	)


def read_doctype_definition(doctype: str) -> dict | None:
	"""An existing DocType in the full Docu IR shape, or None when it does not exist."""
	if not frappe.db.exists("DocType", doctype):
		return None
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return None
	flags, ints = _docfield_flags(), _docfield_ints()
	fields = []
	for f in meta.fields:
		# A layout break keeps an empty label, so Customize Form writes no label Property Setter for it.
		label = f.label or ("" if f.fieldtype in _layout_fieldtypes() else f.fieldname)
		row = {"fieldname": f.fieldname, "fieldtype": f.fieldtype, "label": label}
		for attr in _docfield_strs() + ints + flags:
			val = f.get(attr)
			if attr in flags:
				row[attr] = int(bool(val))
			elif attr in ints:
				row[attr] = int(val or 0)
			else:
				row[attr] = val or ""
		fields.append(row)
	out = {
		"doctype_name": doctype,
		"module": meta.get("module"),
		"is_child_table": int(bool(meta.get("istable"))),
		"custom": int(bool(meta.get("custom"))),
		"autoname": meta.get("autoname") or "",
		"fields": fields,
	}
	for attr in _doctype_setting_flags():
		out[attr] = int(bool(meta.get(attr)))
	out["max_attachments"] = int(meta.get("max_attachments") or 0)
	for attr in _doctype_setting_strs():
		out[attr] = meta.get(attr) or ""
	out["permissions"] = _read_doctype_permissions(doctype)
	return out


def _read_doctype_permissions(doctype: str) -> list:
	source = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
	filters = {"parent": doctype}
	if source == "DocPerm":
		filters["parenttype"] = "DocType"
	rows = []
	for p in frappe.get_all(
		source,
		filters=filters,
		fields=["role", "permlevel", *_doctype_permission_flags()],
		order_by="idx asc",
	):
		row = {"role": p.get("role") or "", "permlevel": int(p.get("permlevel") or 0)}
		for flag in _doctype_permission_flags():
			row[flag] = int(bool(p.get(flag)))
		rows.append(row)
	return rows


def keep_unrequested_fields(current_ir: dict, proposed_ir: dict, request: str) -> str:
	"""Put back into proposed_ir each field and child table column the request did not ask to remove; the reply line or ""."""
	kept = _restore_fields(current_ir.get("fields") or [], proposed_ir.setdefault("fields", []), request)
	for field in proposed_ir["fields"]:
		if field.get("fieldtype") not in frappe.model.table_fields or not field.get("child_fields"):
			continue
		live = read_doctype_definition((field.get("options") or "").strip())
		if live:
			kept += _restore_fields(live["fields"], field["child_fields"], request)
	if not kept:
		return ""
	return frappe._("I kept {0}, which your request did not ask to remove.").format(", ".join(kept))


def _restore_fields(current: list, proposed: list, request: str) -> list:
	present = {f.get("fieldname") for f in proposed}
	kept = []
	for position, field in enumerate(current):
		fieldname = field.get("fieldname")
		if not fieldname or fieldname in present:
			continue
		if _asked_to_remove(field, request):
			continue
		before = next(
			(f.get("fieldname") for f in reversed(current[:position]) if f.get("fieldname") in present), None
		)
		at = next((i + 1 for i, f in enumerate(proposed) if f.get("fieldname") == before), 0)
		proposed.insert(at, field)
		present.add(fieldname)
		kept.append(field.get("label") or fieldname)
	return kept


def _asked_to_remove(field: dict, request: str) -> bool:
	import re

	if field["fieldname"] in reserved_fieldnames():
		return False
	removal = r"\b(?:remove|delete|drop|get\s+rid\s+of|take\s+out|replace|without)\b"
	if not re.search(removal, request, re.I):
		return False
	names = {(field.get("label") or "").strip(), field["fieldname"].replace("_", " ")}
	names.discard("")
	return any(re.search(r"\b" + re.escape(name) + r"\b", request, re.I) for name in names)
