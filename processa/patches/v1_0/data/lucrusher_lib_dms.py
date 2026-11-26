# LuCrusher document search: find the DMS documents that match a request.
# ruff: noqa: F821 - import_script gives a library frappe; it has no imports at the top level.


def _doctype():
	return "Document Register"


def _document_types():
	return ("Policy", "SOP", "Manual", "Guideline", "Knowledge Base")


def _fields():
	return [
		"name",
		"title",
		"document_code",
		"document_type",
		"current_version",
		"drive_file_link",
		"content",
	]


def _chunk_word_count():
	return 600


def _chunk_overlap():
	return 80


def _keyword_min_share():
	return 0.34


def _max_results():
	return 4


def search_dms_documents(query: str, document_type: str | None = None, instance=None) -> dict:
	"""Best matching excerpts from the Active documents the person in the conversation can read."""
	from processa.ai_agent_memory.tools import query_tokens

	if document_type and document_type not in _document_types():
		return {"error": frappe._("document_type must be one of: {0}").format(", ".join(_document_types()))}

	tokens = [_stem(token) for token in query_tokens(query)]
	if not tokens:
		return {"results": []}

	filters = {"lifecycle_state": "Active"}
	if document_type:
		filters["document_type"] = document_type

	# ponytail: reads every readable Active document per query, index them if the register outgrows a few hundred
	user = _chatting_user(instance) or frappe.session.user
	frappe.has_permission(_doctype(), "read", user=user, throw=True)
	documents = [
		document
		for document in frappe.get_all(_doctype(), filters=filters, fields=_fields(), limit_page_length=0)
		if frappe.has_permission(_doctype(), "read", doc=document.name, user=user)
	]

	hits = []
	for document in documents:
		for chunk in _chunk_words(document.content or ""):
			score = _score(f"{document.title} {chunk}", tokens)
			if score >= _keyword_min_share():
				hits.append((score, document, chunk))
	hits.sort(key=lambda hit: hit[0], reverse=True)

	return {
		"results": [
			{
				"title": document.title,
				"document_code": document.document_code,
				"document_type": document.document_type,
				"version": document.current_version,
				"excerpt": chunk,
				"url": document.drive_file_link,
			}
			for _hit_score, document, chunk in hits[: _max_results()]
		]
	}


def _chatting_user(instance) -> str | None:
	"""The person the conversation belongs to; the agent's own user holds no roles, so reads are checked as this person."""
	if getattr(instance, "context_doctype", "") != "Chat Conversation":
		return None
	return frappe.db.get_value("Chat Conversation", instance.context_docname, "owner")


def _score(text: str, tokens: list) -> float:
	"""Share of the query keywords that appear in the text."""
	text = text.lower()
	return sum(token in text for token in tokens) / len(tokens)


def _stem(token: str) -> str:
	"""Lower-case and drop a plural s, so "fonts" matches "font"."""
	token = token.lower()
	return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _chunk_words(text: str) -> list[str]:
	words = text.split()
	if not words:
		return []
	step = _chunk_word_count() - _chunk_overlap()
	return [
		" ".join(words[start : start + _chunk_word_count()])
		for start in range(0, max(len(words) - _chunk_overlap(), 1), step)
	]
