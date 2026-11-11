export async function resolve(specifier, context, next) {
	if (specifier === "typebox") {
		return { shortCircuit: true, url: "data:text/javascript,export const Type = { Object: (s) => s, String: (o) => o, Optional: (t) => t };export const StringEnum = (v) => v;" };
	}
	return next(specifier, context);
}
