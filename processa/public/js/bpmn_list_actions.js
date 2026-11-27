/**
 * The Actions menu of a list view for DocTypes Processa runs.
 *
 * Processa owns the lifecycle of those documents, so the native bulk Submit, Cancel and Delete items
 * are hidden and the native workflow transitions are dropped: either would move the document behind
 * the engine's back and strand its instance on a waiting task.
 *
 * In their place, the actions the checked documents have in common are added each time the menu opens,
 * and clicking one completes that task on every selected record. The server decides which actions those
 * are, with the same check complete_task enforces on write.
 */
(function () {
	"use strict";

	const NATIVE_ACTIONS = ["Submit", "Cancel", "Delete"];
	const LABEL_CONTEXT = "Button in list view actions menu";
	const PROCESSA_ITEM_MARKER = "__processa_bulk_action__";
	// Beyond this many, the confirmation names the first few and counts the rest.
	const NAMED_IN_CONFIRM = 5;

	const ListViewProto = frappe.views.ListView.prototype;
	const _original_get_actions_menu_items = ListViewProto.get_actions_menu_items;
	const _original_get_workflow_action_menu_items = ListViewProto.get_workflow_action_menu_items;
	const _original_toggle_workflow_actions = ListViewProto.toggle_workflow_actions;

	function is_processa_doctype(doctype) {
		return (frappe.boot.processa_doctypes || []).includes(doctype);
	}

	ListViewProto.get_actions_menu_items = function () {
		const items = _original_get_actions_menu_items.call(this);
		if (!is_processa_doctype(this.doctype)) return items;

		const hidden = NATIVE_ACTIONS.map((label) => __(label, null, LABEL_CONTEXT));
		return items.filter((item) => !hidden.includes(item.label));
	};

	// A native transition would set workflow_state without the engine, leaving the instance waiting forever.
	ListViewProto.get_workflow_action_menu_items = function () {
		if (is_processa_doctype(this.doctype)) return [];
		return _original_get_workflow_action_menu_items.call(this);
	};

	/**
	 * Frappe calls this every time the Actions dropdown opens, which is when the selection is known.
	 */
	ListViewProto.toggle_workflow_actions = function () {
		if (!is_processa_doctype(this.doctype)) {
			return _original_toggle_workflow_actions.call(this);
		}

		_clear_processa_items(this);

		// A view without row selection (kanban, calendar) has nothing to act on.
		if (typeof this.get_checked_items !== "function") return;

		const docnames = this.get_checked_items(true) || [];
		if (!docnames.length) return;

		const me = this;
		_add_note(this, __("Checking actions…"));

		frappe
			.xcall("processa.api.bulk_actions.get_bulk_action_context", {
				doctype: this.doctype,
				docnames: JSON.stringify(docnames),
			})
			.then((context) => {
				_clear_processa_items(me);
				_render(me, context, docnames);
			})
			.catch(() => _clear_processa_items(me));
	};

	function _render(listview, context, docnames) {
		if (!context) return;

		if (context.mixed) {
			// Half the selection is outside Processa, so no action can be applied to all of it.
			_add_note(listview, __("Selection mixes Processa and non-Processa documents"));
			return;
		}

		if (!context.actions || !context.actions.length) {
			_add_note(listview, __("No action available on this selection"));
			return;
		}

		context.actions.forEach((action) => {
			const $link = listview.page.add_actions_menu_item(
				__(action),
				() => _confirm_and_apply(listview, action, docnames, context),
				false
			);
			if ($link) $link.closest("li").attr("data-processa-action", PROCESSA_ITEM_MARKER);
		});
	}

	/**
	 * The same confirmation the form asks for before a single action, naming the records it covers
	 * and how many of them will be skipped.
	 */
	function _confirm_and_apply(listview, action, docnames, context) {
		const blocked = Object.keys(context.blocked || {}).length;
		let message = __("Apply {0} to {1}?", [action, _record_list(docnames)]);
		if (blocked) {
			message += " " + __("{0} of them cannot be actioned and will be skipped.", [blocked]);
		}

		frappe.confirm(message, () => _apply(listview, action, docnames));
	}

	/**
	 * The selected records by name, kept short enough to read in a dialog.
	 */
	function _record_list(docnames) {
		const names = docnames.map((name) => frappe.utils.escape_html(name));
		if (names.length === 1) return names[0];

		const shown = names.slice(0, NAMED_IN_CONFIRM).join(", ");
		const rest = names.length - NAMED_IN_CONFIRM;
		if (rest > 0) {
			return __("{0} documents ({1} and {2} more)", [names.length, shown, rest]);
		}
		return __("{0} documents ({1})", [names.length, shown]);
	}

	function _apply(listview, action, docnames) {
		listview.disable_list_update = true;
		frappe.dom.freeze(__("Applying {0}…", [action]));

		frappe
			.xcall("processa.api.bulk_actions.bulk_task_action", {
				doctype: listview.doctype,
				docnames: JSON.stringify(docnames),
				action: action,
			})
			.finally(() => {
				frappe.dom.unfreeze();
				listview.disable_list_update = false;
				listview.refresh();
			});
	}

	function _add_note(listview, text) {
		const $link = listview.page.add_actions_menu_item(text, () => {}, false);
		if (!$link) return;
		$link.addClass("disabled text-muted");
		$link.closest("li").attr("data-processa-action", PROCESSA_ITEM_MARKER);
	}

	function _clear_processa_items(listview) {
		if (!listview.page || !listview.page.actions) return;
		listview.page.actions.find(`li[data-processa-action="${PROCESSA_ITEM_MARKER}"]`).remove();
	}
})();
