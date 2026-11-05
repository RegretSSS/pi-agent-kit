const FOLD_INDEX_WITH_HISTORY = [
	"In addition, the summary MUST start with a fold-index header:",
	"<fold-index>",
	'- <topic> | <mNNNNN-mNNNNN span> | <key fact, keep under 40 chars> | trace: history_search("<topic>")',
	"</fold-index>",
	"One line per major phase of the folded span. The trace column is the single drill-down entry: history_search retrieves the compressed block, history_read reads it.",
	"If an earlier <fold-index> is present in the conversation, distill and merge its still-relevant lines into the new one so at most one fold-index stays alive.",
].join("\n");

const FOLD_INDEX_WITHOUT_HISTORY = [
	"In addition, the summary MUST start with a fold-index header:",
	"<fold-index>",
	"- <topic> | <mNNNNN-mNNNNN span or turn range> | <key fact, keep under 40 chars>",
	"</fold-index>",
	"One line per major phase of the folded span.",
	"If an earlier <fold-index> is present in the conversation, distill and merge its still-relevant lines into the new one so at most one fold-index stays alive.",
].join("\n");

export function buildCompactInstructions(brief: string, historyActive: boolean): string {
	const indexSpec = historyActive ? FOLD_INDEX_WITH_HISTORY : FOLD_INDEX_WITHOUT_HISTORY;
	return `${brief}\n\n${indexSpec}`;
}
