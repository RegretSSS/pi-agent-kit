import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";

const root = process.env.PI_PACKAGE_ROOT;
const TARGETS = {
	"@earendil-works/pi-tui": root && `${root}/node_modules/@earendil-works/pi-tui/dist/index.js`,
	"@earendil-works/pi-coding-agent": root && `${root}/dist/index.js`,
};

export async function resolve(specifier, context, next) {
	const target = TARGETS[specifier];
	if (target && existsSync(target)) {
		return { shortCircuit: true, url: pathToFileURL(target).href };
	}
	return next(specifier, context);
}
