import Link from "next/link";

export const metadata = { title: "Privacy — Trezo" };

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 sm:px-6 py-16">
      <Link href="/" className="text-sm text-weave-600 hover:underline">
        ← Back to Trezo
      </Link>
      <h1 className="mt-4 font-serif text-3xl text-weave-800 tracking-tight">
        Privacy
      </h1>
      <p className="mt-2 text-sm text-weave-500">
        Research preview · last updated {new Date().getFullYear()}
      </p>
      <div className="mt-6 space-y-4 text-weave-600 leading-relaxed">
        <p>
          Trezo is a personal, paper-trading research preview. It does not
          place real-money trades and does not connect to a live brokerage.
        </p>
        <p>
          <span className="font-medium text-weave-800">What Trezo stores:</span>{" "}
          the email address you sign up with, the profile and risk settings
          you enter, and the simulated trading activity the system generates.
          This lives in a Supabase database protected by row-level security,
          so your records are visible only to your own account.
        </p>
        <p>
          <span className="font-medium text-weave-800">What Trezo does not do:</span>{" "}
          it does not sell your data, show ads, or share your information with
          third parties beyond the infrastructure needed to run the app — the
          database host and the market-data sources.
        </p>
        <p>
          Market data is fetched from third-party providers such as Finnhub
          and CoinGecko, each of which has its own privacy practices.
        </p>
        <p className="text-sm text-weave-500">
          This is a working draft for a research-preview product. It should be
          reviewed by a professional before Trezo is offered to anyone beyond
          its owner.
        </p>
      </div>
    </main>
  );
}
