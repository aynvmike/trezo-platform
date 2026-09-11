const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

function loadTypeScript(relativePath, mocks = {}) {
  const filename = path.join(__dirname, "..", relativePath);
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  });
  const module = { exports: {} };
  new Function("module", "exports", "require", compiled.outputText)(module, module.exports, (name) => mocks[name] ?? require(name));
  return module.exports;
}

const { messageBelongsToBooks } = loadTypeScript("src/lib/agent-book-scope.ts");
const { optionExposure } = loadTypeScript("src/lib/trade-exposure.ts");
const owned = ["book-one", "book-two"];
const trade = (overrides = {}) => ({ user_id: null, agent_name: "trade_execution", kind: "execute", payload: {}, ...overrides });

test("book feed separates accounts even when the legacy bus stores ownership in payload", () => {
  const message = trade({ payload: { user_id: "book-two", ticker: "SPY" } });
  assert.equal(messageBelongsToBooks(message, owned, "owner", "book-two"), true);
  assert.equal(messageBelongsToBooks(message, owned, "owner", "book-one"), false);
  assert.equal(messageBelongsToBooks(message, owned, "owner"), true);
});

test("foreign top-level, payload, and nested account data cannot appear in an owned feed", () => {
  for (const message of [
    trade({ user_id: "foreign" }),
    trade({ payload: { user_id: "foreign" } }),
    trade({ user_id: "book-one", payload: { summary: { per_book: [{ book_id: "foreign" }] } } }),
  ]) assert.equal(messageBelongsToBooks(message, owned, "owner"), false);
});

test("only account-free market reports are shared; unattributed trades remain hidden", () => {
  assert.equal(messageBelongsToBooks(trade(), owned, "owner"), false);
  const report = trade({ agent_name: "market_horizon", kind: "info", payload: { note: "Market update" } });
  assert.equal(messageBelongsToBooks(report, owned, "owner", "book-one"), true);
  const contaminated = { ...report, payload: { books: [{ account_key: "foreign" }] } };
  assert.equal(messageBelongsToBooks(contaminated, owned, "owner"), false);
});

test("option exposure distinguishes bought puts, written puts, and bearish spreads", () => {
  assert.equal(optionExposure("long_put"), "Bearish · purchased put");
  assert.equal(optionExposure("long_call"), "Bullish · purchased call");
  assert.equal(optionExposure("option_day", "SPY260918P00500000", "long"), "Bearish · purchased put");
  assert.equal(optionExposure("", "SPY260918P00500000", "short"), "Bullish · written put");
  assert.equal(optionExposure("bear_call_spread"), "Bearish");
  assert.equal(optionExposure("wheel_cc"), "Neutral / bullish · capped upside");
  assert.equal(optionExposure("option_day"), "Option direction unverified");
});

function routeFixture(relativePath) {
  const inserts = [];
  const client = {
    from(table) {
      let requested;
      return {
        select() { return this; },
        eq(key, value) { if (key === "account_key") requested = value; return this; },
        async maybeSingle() { return { data: owned.includes(requested) ? { account_key: requested } : null, error: null }; },
        async insert(row) { inserts.push({ table, row }); return { error: null }; },
      };
    },
  };
  const route = loadTypeScript(relativePath, {
    "@/lib/supabase/server": { createClient: () => client },
    "@/lib/auth-guards": { requireOwner: async () => ({ ok: true, user: { id: "owner" } }) },
  });
  return { route, inserts };
}

const orderBody = { leg: "csp", underlying: "SPY", target_strike: 500, target_exp: "2026-09-18", contracts: 1 };
function request(body) { return new Request("https://trezo.test/api", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }

test("Wheel order rejects absent and foreign books before any broker call", async () => {
  const { route } = routeFixture("src/app/api/wheel/place-leg/route.ts");
  const originalFetch = global.fetch;
  global.fetch = async () => { throw new Error("Broker must not be contacted"); };
  try {
    assert.equal((await route.POST(request(orderBody))).status, 400);
    assert.equal((await route.POST(request({ ...orderBody, account_key: "foreign" }))).status, 404);
  } finally { global.fetch = originalFetch; }
});

test("Wheel orders route to the selected book and do not duplicate backend tracking", async () => {
  const { route, inserts } = routeFixture("src/app/api/wheel/place-leg/route.ts");
  const originalFetch = global.fetch;
  const upstream = [];
  global.fetch = async (url) => {
    upstream.push(new URL(url));
    return Response.json({ ok: true, recorded: true, strike: 500, expiration: "2026-09-18", contracts: 1 });
  };
  try {
    const response = await route.POST(request({ ...orderBody, account_key: "book-two" }));
    assert.equal((await response.json()).recorded, true);
    assert.equal(upstream[0].searchParams.get("user_id"), "book-two");
    assert.deepEqual(inserts, []);
  } finally { global.fetch = originalFetch; }
});

test("Wheel tracking recovery keeps the selected book and backend contract quantity", async () => {
  const { route, inserts } = routeFixture("src/app/api/wheel/place-leg/route.ts");
  const originalFetch = global.fetch;
  global.fetch = async () => Response.json({ ok: true, recorded: false, strike: 500, expiration: "2026-09-18", contracts: 1, premium: 2 });
  try {
    const response = await route.POST(request({ ...orderBody, contracts: 3, account_key: "book-two" }));
    assert.equal((await response.json()).recorded, true);
    assert.equal(inserts[0].row.user_id, "book-two");
    assert.equal(inserts[0].row.contracts, 1);
    assert.equal(inserts[0].row.net_premium_usd, 200);
  } finally { global.fetch = originalFetch; }
});

test("Wheel reconcile requires an owned book and forwards that exact book", async () => {
  const { route } = routeFixture("src/app/api/wheel/reconcile/route.ts");
  const originalFetch = global.fetch;
  const upstream = [];
  global.fetch = async (url) => { upstream.push(new URL(url)); return Response.json({ ok: true }); };
  try {
    assert.equal((await route.POST(request({}))).status, 400);
    assert.equal((await route.POST(request({ account_key: "foreign" }))).status, 404);
    assert.equal(upstream.length, 0);
    assert.equal((await route.POST(request({ account_key: "book-two" }))).status, 200);
    assert.equal(upstream[0].searchParams.get("user_id"), "book-two");
  } finally { global.fetch = originalFetch; }
});

test("capability partial failures remain visible without exposing foreign books or diagnostics", async () => {
  const client = { from: () => ({ select() { return this; }, eq() { return this; }, async order() {
    return { data: owned.map((key) => ({ account_key: key, label: key })), error: null };
  } }) };
  const route = loadTypeScript("src/app/api/agents/capabilities/route.ts", {
    "@/lib/supabase/server": { createClient: () => client },
    "@/lib/auth-guards": { requireUser: async () => ({ ok: true, user: { id: "owner" } }) },
  });
  const originalFetch = global.fetch;
  global.fetch = async () => Response.json({
    error: "Account directory unavailable",
    configuration_notes: ["foreign owner's confidential account configuration"],
    books: [
      { book_id: "book-one", label: "Engine label", note: "This book uses its own capital.", capabilities: [{ id: "stock_long", label: "Stocks", status: "enabled", reason: "Enabled", directions: ["bullish"] }] },
      { book_id: "foreign", label: "Confidential", note: "Private", capabilities: [] },
    ],
  });
  try {
    const response = await route.GET();
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.deepEqual(body.books.map((book) => book.book_id), owned);
    assert.equal(body.books[0].note, "This book uses its own capital.");
    assert.equal(body.books[1].capabilities[0].status, "unverified");
    assert.equal(body.warnings.length, 2);
    assert.match(body.warnings[0], /account directory/);
    assert.doesNotMatch(JSON.stringify(body), /foreign|Confidential|Private/);
  } finally { global.fetch = originalFetch; }
});
