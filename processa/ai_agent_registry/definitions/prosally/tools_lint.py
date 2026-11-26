"""ProsAlly turns diagram lint findings into a fix request and a reply."""

import re



LINT_FIX_REQUEST = re.compile(
	r"\b(?:fix|resolve|clear|clean\s*up|correct|repair|solve|sort\s*out)\b[^.:]{0,60}\b(?:lint(?:ing)?|linter|warnings?|errors?|issues?|problems?)\b"
	r"(?!\s+(?:handler|step|task|event|gateway|flow|path|boundary|code))"
	r"|\blint(?:ing)?\b[^.:]{0,40}\b(?:fix|resolve|clear|clean\s*up|correct|repair)",
	re.I,
)
LINT_NOT_FIXABLE = frozenset(
	(
		"no-overlapping-elements",
		"no-crossing-edges",
		"script-task-missing-script",
		"call-activity-missing-process",
		"no-prohibited-shapes",
		"no-bpmndi",
		"ad-hoc-sub-process",
	)
)
LINT_ABOUT_CONTENTS = frozenset(
	("start-event-required", "end-event-required", "sub-process-blank-start-event", "single-blank-start-event")
)
MAX_LINT_FINDINGS = 40


