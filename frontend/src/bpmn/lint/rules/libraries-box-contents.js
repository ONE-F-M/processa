/** Flags a Libraries box that holds anything other than script tasks, a sequence flow included. */

import { is } from "bpmnlint-utils";

import { isLibrariesBox } from "./tool-catalogue.js";

const named = (element) => element.name || element.id;

export default function () {
	function check(node, reporter) {
		if (!isLibrariesBox(node)) {
			return;
		}
		const stray = (node.flowElements || []).find((element) => !is(element, "bpmn:ScriptTask"));
		if (!stray) {
			return;
		}
		reporter.report(
			node.id,
			`A Libraries box holds only library script tasks. Move "${named(stray)}" out of "${named(node)}".`
		);
	}

	return { check };
}
