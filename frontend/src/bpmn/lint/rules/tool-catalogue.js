/**
 * An ad-hoc sub-process that an AI Agent Task names in aiToolsAdhoc, or one marked as a Libraries box, has no arrows into it.
 */

import { is } from "bpmnlint-utils";

/** An ad-hoc sub-process marked as a Libraries box. */
export function isLibrariesBox(node) {
	return is(node, "bpmn:AdHocSubProcess") && node.get("spiffworkflow:scriptLibrary") === "true";
}

function isToolCatalogue(node) {
	if (!is(node, "bpmn:AdHocSubProcess")) {
		return false;
	}
	if (isLibrariesBox(node)) {
		return true;
	}
	return node.$parent.flowElements.some((element) => element.get("spiffworkflow:aiToolsAdhoc") === node.id);
}

/** The given bpmnlint rule factory, skipping tool catalogues. */
export default function exemptToolCatalogues(ruleFactory) {
	return function () {
		const rule = ruleFactory();
		return {
			...rule,
			check(node, reporter) {
				if (!isToolCatalogue(node)) {
					rule.check(node, reporter);
				}
			},
		};
	};
}
