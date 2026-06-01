/**
 * Broker provider registry — every external account Trezo can connect
 * via OAuth lives here. Adding a provider = one row.
 *
 * Note on "Coming soon" cards: most retail brokers do not publish a
 * public OAuth flow you can register against in 5 minutes. Where we
 * have a real OAuth endpoint we list it; where we do not, the card
 * stays planned with an honest blurb explaining what is required.
 * Trezo will not invent a non-OAuth path that asks the user for
 * passwords — the framework is OAuth-only on purpose.
 */

export type BrokerKey =
  | "alpaca"
  | "alpaca-live"
  | "ibkr"
  | "webull"
  | "robinhood"
  | "coinbase"
  | "kraken"
  | "gemini"
  | "plaid";

export type ProviderStatus = "available" | "planned";

export type ProviderCategory =
  | "brokerage"
  | "crypto"
  | "banking";

export type BrokerProvider = {
  key: BrokerKey;
  label: string;
  blurb: string;
  category: ProviderCategory;
  status: ProviderStatus;
  authorize_url?: string;
  token_url?: string;
  scopes?: string;
  client_id_env?: string;
  client_secret_env?: string;
  redirect_path: string;
  venue?: "paper" | "live";
};

export const CATEGORY_LABEL: Record<ProviderCategory, string> = {
  brokerage: "Brokerage (stocks · options · futures)",
  crypto: "Crypto exchange",
  banking: "Banking & bank aggregation"
};

export const CATEGORY_BLURB: Record<ProviderCategory, string> = {
  brokerage:
    "Where the bot places stock, option and futures trades. Paper first, live after the go-live checklist.",
  crypto:
    "Where the bot buys and holds crypto. OAuth-only — Trezo never sees your password.",
  banking:
    "Where KINDRIP contributions come from and where Budget Mirror reads your spending. Plaid covers most U.S. banks in one connect."
};

export const BROKER_PROVIDERS: BrokerProvider[] = [
  // ---------- Brokerage ----------
  {
    key: "alpaca",
    label: "Alpaca (Paper)",
    blurb:
      "Sign in to Alpaca and authorise Trezo — no keys to copy. Your paper account is the safe one to connect first. Stock + option trades route through your account once connected.",
    category: "brokerage",
    status: "available",
    authorize_url: "https://app.alpaca.markets/oauth/authorize",
    token_url: "https://api.alpaca.markets/oauth/token",
    scopes: "account:write trading data",
    client_id_env: "ALPACA_OAUTH_CLIENT_ID",
    client_secret_env: "ALPACA_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/alpaca/callback",
    venue: "paper"
  },
  {
    key: "alpaca-live",
    label: "Alpaca (Live)",
    blurb:
      "Same OAuth flow against your live Alpaca account. Only enabled once the Live Trading checklist passes — connecting alone does not flip you to real money.",
    category: "brokerage",
    status: "planned",
    authorize_url: "https://app.alpaca.markets/oauth/authorize",
    token_url: "https://api.alpaca.markets/oauth/token",
    scopes: "account:write trading data",
    client_id_env: "ALPACA_LIVE_OAUTH_CLIENT_ID",
    client_secret_env: "ALPACA_LIVE_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/alpaca-live/callback",
    venue: "live"
  },
  {
    key: "ibkr",
    label: "Interactive Brokers",
    blurb:
      "IBKR's OAuth flow — equities, options, futures and forex in one account. Useful when the strategy mix moves beyond stocks. IBKR's flow is more involved than Alpaca; allow time for their developer review when you register the OAuth app.",
    category: "brokerage",
    status: "planned",
    authorize_url: "https://www.interactivebrokers.com/sso/oauth/authorize",
    token_url: "https://www.interactivebrokers.com/sso/oauth/token",
    scopes: "trading account",
    client_id_env: "IBKR_OAUTH_CLIENT_ID",
    client_secret_env: "IBKR_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/ibkr/callback"
  },
  {
    key: "webull",
    label: "Webull",
    blurb:
      "Webull does not currently publish a public OAuth flow for third-party trading apps — connecting requires Webull's partner program. Trezo will not ship a password-based or reverse-engineered path; this card stays parked until the official flow is available.",
    category: "brokerage",
    status: "planned",
    client_id_env: "WEBULL_OAUTH_CLIENT_ID",
    client_secret_env: "WEBULL_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/webull/callback"
  },
  {
    key: "robinhood",
    label: "Robinhood",
    blurb:
      "Robinhood does not currently publish a public OAuth flow for retail third-party trading. The framework is ready — when Robinhood opens a partner OAuth program, this card flips with one row change.",
    category: "brokerage",
    status: "planned",
    client_id_env: "ROBINHOOD_OAUTH_CLIENT_ID",
    client_secret_env: "ROBINHOOD_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/robinhood/callback"
  },

  // ---------- Crypto exchange ----------
  {
    key: "coinbase",
    label: "Coinbase",
    blurb:
      "Most-used U.S. crypto exchange with a real OAuth flow. Sign in there, Trezo gets a per-user token — same shape as Alpaca.",
    category: "crypto",
    status: "planned",
    authorize_url: "https://login.coinbase.com/oauth2/auth",
    token_url: "https://login.coinbase.com/oauth2/token",
    scopes: "wallet:accounts:read wallet:transactions:read wallet:trades:create",
    client_id_env: "COINBASE_OAUTH_CLIENT_ID",
    client_secret_env: "COINBASE_OAUTH_CLIENT_SECRET",
    redirect_path: "/api/brokers/coinbase/callback"
  },
  {
    key: "kraken",
    label: "Kraken",
    blurb:
      "Deep liquidity, lower fees. Kraken's standard auth is API key only — public OAuth is limited. This card stays planned until Kraken Connect is broadly available.",
    category: "crypto",
    status: "planned",
    redirect_path: "/api/brokers/kraken/callback"
  },
  {
    key: "gemini",
    label: "Gemini",
    blurb:
      "Regulated U.S. crypto custodian. Useful for the income-bucket portion of the Crypto layer where custody matters. Same partner-program limitation as Kraken today.",
    category: "crypto",
    status: "planned",
    redirect_path: "/api/brokers/gemini/callback"
  },

  // ---------- Banking ----------
  {
    key: "plaid",
    label: "Plaid",
    blurb:
      "One connect that covers most U.S. banks. KINDRIP funding and Budget Mirror both read through Plaid. Trezo never sees your bank password. Plaid uses Link, a similar consent-and-token model — same framework, slightly different handshake.",
    category: "banking",
    status: "planned",
    redirect_path: "/api/brokers/plaid/callback"
  }
];

export function getProvider(key: string): BrokerProvider | undefined {
  return BROKER_PROVIDERS.find((p) => p.key === key);
}

export function providersByCategory(): Record<ProviderCategory, BrokerProvider[]> {
  const out: Record<ProviderCategory, BrokerProvider[]> = {
    brokerage: [],
    crypto: [],
    banking: []
  };
  for (const p of BROKER_PROVIDERS) out[p.category].push(p);
  return out;
}
