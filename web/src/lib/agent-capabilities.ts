export type TradingCapability = {
  id: string;
  label: string;
  status: "enabled" | "disabled" | "unavailable" | "unverified";
  reason: string;
  directions: string[];
};

export type BookCapabilities = {
  book_id: string;
  label: string;
  capabilities: TradingCapability[];
  note?: string;
};

export type CapabilitiesResponse = {
  books?: BookCapabilities[];
  generated_at?: string;
  error?: string;
  warnings?: string[];
};
