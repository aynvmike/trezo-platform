/** Legacy bus rows sometimes carry the book in payload instead of user_id. */
type ScopedMessage = {
  user_id?: string | null;
  agent_name: string;
  kind: string;
  payload?: Record<string, unknown> | null;
};

const BOOK_FIELDS = new Set(["user_id", "book_id", "account_key"]);
const SHARED_REPORT_AGENTS = new Set([
  "market_sentiment", "market_horizon", "research", "strategy_discovery",
]);

export function messageBelongsToBooks(
  message: ScopedMessage,
  bookKeys: string[],
  ownerId: string,
  selectedBook?: string,
): boolean {
  const owned = new Set([...bookKeys, ownerId]);
  const references: string[] = [];
  function collect(value: unknown): void {
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
      if (BOOK_FIELDS.has(key) && typeof item === "string" && item) references.push(item);
      else if (item && typeof item === "object") collect(item);
    }
  }
  if (message.user_id) references.push(message.user_id);
  collect(message.payload);
  if (references.some((key) => !owned.has(key))) return false;
  if (references.length > 0) {
    return !selectedBook || references.includes(selectedBook);
  }
  // Only account-free research/market reports can be shared. Unattributed
  // executions must not masquerade as activity in the selected book.
  return SHARED_REPORT_AGENTS.has(message.agent_name)
    && ["info", "metrics", "alert", "report"].includes(message.kind);
}
