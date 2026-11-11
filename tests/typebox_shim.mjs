export async function resolve(specifier, context, next) {
	if (specifier === "@earendil-works/pi-tui") {
		return { shortCircuit: true, url: "data:text/javascript,export class Text { constructor(text) { this.text = text; } }" };
	}
	if (specifier === "@earendil-works/pi-ai") {
		return { shortCircuit: true, url: "data:text/javascript,export const StringEnum = (v) => v;" };
	}
	if (specifier === "typebox") {
		return { shortCircuit: true, url: "data:text/javascript,export const Type = { Object: (s) => s, String: (o) => o, Integer: (o) => o, Optional: (t) => t };export const StringEnum = (v) => v;" };
	}
	return next(specifier, context);
}
