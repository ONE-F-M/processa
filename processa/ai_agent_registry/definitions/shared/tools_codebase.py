"""Free-text search over the source files of the installed apps, for Server Scripts that cannot import subprocess."""

import json
import os
import re
import subprocess

import frappe

from processa.ai_agent_registry.definitions.shared.helpers import tool_envelope

MAX_QUERY_LENGTH = 200
MAX_RESULTS = 100
GREP_TIMEOUT_SECONDS = 5

INCLUDE_PATTERNS = ("*.py", "*.js", "*.json", "*.html", "*.css", "*.scss", "*.vue", "*.md")
EXCLUDE_PATTERNS = (
	"site_config.json",
	"common_site_config.json",
	"*.pem",
	"*.key",
	"*.crt",
	"*.env",
	"*.env.*",
)
EXCLUDE_DIRS = ("node_modules", ".git", "__pycache__", ".cache", "dist", "build")

# Applied in this order; group 1 is the name that stays in front of the redacted value.
_REDACTION_PATTERNS = (
	r"""(password|passwd|pwd)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
	r"""(secret|secret_key)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
	r"""(api_key|apikey|api_secret)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
	r"""(token|auth_token|access_token)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
	r"""(db_password|encryption_key)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
	r"""(private_key|ssh_key)\s*[=:]\s*["']?[^\s"'`,\)]+["']?""",
)


@tool_envelope("Shared Tool - search_codebase", lambda **_: json.dumps({"error": "Codebase search failed."}))
def search_codebase(query: str, path: str = ".", app: str | None = None) -> str:
	"""Lines of the installed apps' source files that contain query, as JSON with query, results, count and searched_apps."""
	if len(query) > MAX_QUERY_LENGTH:
		return json.dumps({"error": f"Query too long. Maximum {MAX_QUERY_LENGTH} characters allowed."})
	if not query.strip():
		return json.dumps({"error": "Query cannot be empty."})

	if app:
		if app not in frappe.get_installed_apps():
			return json.dumps({"error": f"App '{app}' is not installed on this site."})
		app_names = [app]
	else:
		app_names = list(frappe.get_installed_apps())

	command = ["grep", "-rnI", f"--max-count={MAX_RESULTS}"]
	for pattern in INCLUDE_PATTERNS:
		command += ["--include", pattern]
	for pattern in EXCLUDE_PATTERNS:
		command += ["--exclude", pattern]
	for directory in EXCLUDE_DIRS:
		command += ["--exclude-dir", directory]

	results, timed_out_apps = [], []
	for app_name in app_names:
		if len(results) >= MAX_RESULTS:
			break
		app_path = os.path.realpath(frappe.get_app_path(app_name))
		search_path = os.path.realpath(os.path.join(app_path, path))
		if os.path.commonpath([search_path, app_path]) != app_path:
			return json.dumps({"error": f"Path '{path}' is outside the app."})

		# "--" makes a query that starts with a dash text to search for, not a grep option.
		process = subprocess.Popen(
			[*command, "--", query, search_path],
			stdout=subprocess.PIPE,
			stderr=subprocess.DEVNULL,
			text=True,
			errors="replace",
		)
		try:
			stdout, _ = process.communicate(timeout=GREP_TIMEOUT_SECONDS)
		except subprocess.TimeoutExpired:
			process.kill()
			process.communicate()
			timed_out_apps.append(app_name)
			continue

		for line in stdout.splitlines()[: MAX_RESULTS - len(results)]:
			results.append(f"[{app_name}] {_sanitize_codebase_output(line)}")

	response = {"query": query, "results": results, "count": len(results), "searched_apps": app_names}
	if timed_out_apps:
		response["timed_out_apps"] = timed_out_apps
	return json.dumps(response)


def _sanitize_codebase_output(line: str) -> str:
	"""line with the value of any password, secret, key or token assignment replaced by REDACTED."""
	for pattern in _REDACTION_PATTERNS:
		line = re.sub(pattern, r"\1=***REDACTED***", line, flags=re.IGNORECASE)
	return line
