// Data-retrieval guide — how to export spending data from common apps.
// Phase 11a; collapsed into a Help disclosure (testing feedback 2026-05-22).
// Static content; a server component.

type Guide = { name: string; steps: string; note: string };

const GUIDES: Guide[] = [
  {
    name: "Uber & Uber Eats",
    steps:
      "Open the Uber app or riders.uber.com, go to Account, then Privacy, then Download your data. Request the archive — it arrives by email as a set of CSV files (trips and orders).",
    note: "Trip totals are included; some service fees are bundled into the fare."
  },
  {
    name: "DoorDash",
    steps:
      "On the DoorDash website, go to Account, then Manage Account, then Request Archive. The export arrives by email.",
    note: "Order totals are included; the fee breakdown may be partial."
  },
  {
    name: "Grubhub",
    steps:
      "Grubhub does not offer a one-click export. Open Order history in the app, or pull the charges from the card you pay with (see Card statement below).",
    note: "A card-statement export is the most reliable source for Grubhub."
  },
  {
    name: "Lyft",
    steps:
      "At account.lyft.com, go to Privacy and data, then Request my data. Ride history arrives by email as a CSV.",
    note: "Ride totals, dates, and distance are included."
  },
  {
    name: "Instacart",
    steps:
      "On the Instacart website, open Account settings, then download your order history, or pull the charges from your card statement.",
    note: "Order totals are included; per-item detail varies."
  },
  {
    name: "Amazon",
    steps:
      "Go to amazon.com, Account, then Request your data, choose Your Orders, and submit. Or use Order history reports for a direct CSV.",
    note: "Order totals and dates are included."
  },
  {
    name: "Bank or credit-card statement",
    steps:
      "Log in to your bank or card issuer, open the transactions or activity page, and use Export or Download — choose CSV. This is the catch-all when an app has no export of its own.",
    note: "Has every merchant and amount; Budget Mirror reads the date, amount, and description columns."
  }
];

export function DataGuide() {
  return (
    <details className="rounded-xl border border-weave-100 bg-white">
      <summary className="cursor-pointer list-none px-5 py-4 font-medium text-weave-800 select-none">
        Help — how to get your data from each app
        <span className="ml-2 text-sm font-normal text-weave-500">
          (CSV exports for Uber, DoorDash, Lyft, banks, and more)
        </span>
      </summary>
      <div className="border-t border-weave-50 px-5 py-4 space-y-3">
        <p className="text-sm text-weave-600 leading-relaxed">
          Budget Mirror reads a CSV export — you do not type transactions
          in by hand. Here is where each app keeps its export. Any CSV with
          a date, an amount, and a description will work.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {GUIDES.map((g) => (
            <div
              key={g.name}
              className="rounded-lg border border-weave-100 bg-weave-50/40 p-4"
            >
              <p className="font-medium text-weave-800">{g.name}</p>
              <p className="mt-1.5 text-sm text-weave-600 leading-relaxed">
                {g.steps}
              </p>
              <p className="mt-2 text-xs text-weave-500 leading-relaxed">
                {g.note}
              </p>
            </div>
          ))}
        </div>
        <p className="text-xs text-weave-500 leading-relaxed">
          Privacy: the file you choose is read inside your browser to build
          the view above. It is not uploaded to Trezo, stored, or sent
          anywhere.
        </p>
      </div>
    </details>
  );
}
