import { test } from "vitest"
import assert from "node:assert/strict"

import { BpmnModdle } from "bpmn-moddle"
import traverse from "bpmnlint/lib/traverse.js"
import noDisconnected from "bpmnlint/rules/no-disconnected"
import noImplicitEnd from "bpmnlint/rules/no-implicit-end"
import noImplicitStart from "bpmnlint/rules/no-implicit-start"

import aiToolsBoxUnreferenced from "@/bpmn/lint/rules/ai-tools-box-unreferenced.js"
import librariesBoxContents from "@/bpmn/lint/rules/libraries-box-contents.js"
import scriptTaskMissingScript from "@/bpmn/lint/rules/script-task-missing-script.js"
import exemptToolCatalogues from "@/bpmn/lint/rules/tool-catalogue.js"
import { toolBoxOptions } from "@/bpmn/shared/toolBoxOptions.js"

const diagram = (body, executable = "true") => `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d">
  <bpmn:process id="p" isExecutable="${executable}">${body}</bpmn:process>
</bpmn:definitions>`

const marked = 'spiffworkflow:scriptLibrary="true"'
const box = (inner, attrs = marked) => `<bpmn:adHocSubProcess id="box" name="Libraries" ${attrs}>${inner}</bpmn:adHocSubProcess>`
const lib = (attrs = 'spiffworkflow:serverScript="P: Lib Replies"', id = "lib") =>
	`<bpmn:scriptTask id="${id}" name="Lib Replies" ${attrs} />`

async function parse(xml) {
	return (await new BpmnModdle().fromXML(xml)).rootElement
}

async function ids(rule, xml) {
	const check = rule().check
	const reported = []
	traverse(await parse(xml), { enter: (node) => check(node, { report: (id) => reported.push(id) }) })
	return reported
}

async function messages(rule, xml) {
	const check = rule().check
	const reported = []
	traverse(await parse(xml), { enter: (node) => check(node, { report: (id, message) => reported.push(message) }) })
	return reported
}

test("a marked box of linked script tasks with no arrows gets no finding", async () => {
	const xml = diagram(box(lib()))
	assert.deepEqual(await ids(exemptToolCatalogues(noDisconnected), xml), [])
	assert.deepEqual(await ids(exemptToolCatalogues(noImplicitStart), xml), [])
	assert.deepEqual(await ids(exemptToolCatalogues(noImplicitEnd), xml), [])
	assert.deepEqual(await ids(aiToolsBoxUnreferenced, xml), [])
	assert.deepEqual(await ids(librariesBoxContents, xml), [])
})

test("a script task with no script in a Libraries box is still reported", async () => {
	const xml = diagram(box(lib("")))
	assert.ok((await ids(scriptTaskMissingScript, xml)).includes("lib"))
})

test("a user task or a sequence flow in a Libraries box is reported on the box", async () => {
	const userTask = '<bpmn:userTask id="ask" name="Ask" />'
	assert.deepEqual(await ids(librariesBoxContents, diagram(box(lib() + userTask))), ["box"])
	assert.deepEqual(await messages(librariesBoxContents, diagram(box(lib() + userTask))), [
		'A Libraries box holds only library script tasks. Move "Ask" out of "Libraries".',
	])
	const flow = '<bpmn:sequenceFlow id="flow" sourceRef="lib" targetRef="other" />'
	assert.deepEqual(await ids(librariesBoxContents, diagram(box(lib() + lib("", "other") + flow))), ["box"])
})

test("the same box without the mark is still reported as not connected", async () => {
	const reported = await ids(exemptToolCatalogues(noDisconnected), diagram(box(lib(), "")))
	assert.ok(reported.includes("box"))
})

test("a Libraries box is not offered as an agent's Tools box, an unmarked one is", async () => {
	const optionValues = async (attrs) => {
		const root = await parse(diagram(box(lib(), attrs)))
		const options = toolBoxOptions(root.rootElements[0].flowElements, "", (text) => text)
		return options.map((option) => option.value)
	}
	assert.deepEqual(await optionValues(marked), [""])
	assert.deepEqual(await optionValues(""), ["", "box"])
})
