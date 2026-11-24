/**
 * Custom Moddle Extension for Text Styling
 * 
 * Defines a custom namespace whose text style properties are XML
 * attributes on any bpmn:BaseElement.
 */

export default {
	name: "customTextStyle",
	uri: "http://custom/text-style",
	prefix: "custom",
	xml: {
		tagAlias: "lowerCase"
	},
	types: [
		{
			name: "TextStyleProperties",
			extends: ["bpmn:BaseElement"],
			properties: [
				{
					name: "fontWeight",
					isAttr: true,
					type: "String"
				},
				{
					name: "fontStyle",
					isAttr: true,
					type: "String"
				},
				{
					name: "textDecoration",
					isAttr: true,
					type: "String"
				},
				{
					name: "fontSize",
					isAttr: true,
					type: "String"
				},
				{
					name: "textColor",
					isAttr: true,
					type: "String"
				},
				{
					name: "fontFamily",
					isAttr: true,
					type: "String"
				}
			]
		}
	]
};
