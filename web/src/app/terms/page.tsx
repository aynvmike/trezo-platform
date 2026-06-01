import Link from "next/link";

export const metadata = { title: "Terms — Trezo" };

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 sm:px-6 py-16">
      <Link href="/" className="text-sm text-weave-600 hover:underline">
        ← Back to Trezo
      </Link>
      <h1 className="mt-4 font-serif text-3xl text-weave-800 tracking-tight">
        Terms
      </h1>
      <p className="mt-2 text-sm text-weave-500">
        Research preview · last updated {new Date().getFullYear()}
      </p>
      <div className="mt-6 space-y-4 text-weave-600 leading-relaxed">
        <p>
          Trezo is a paper-trading simulator and research preview. Every trade
          it shows is simulated. It is not a brokerage and moves no real money.
        </p>
        <p>
          <span className="font-medium text-weave-800">Not advice.</span>{" "}
          Nothing in Trezo — including signals, scores, tax estimates, and
          strategy notes — is financial, investment, or tax advice. It is
          information to learn from and to take to a qualified professional.
        </p>
        <p>
          <span className="font-medium text-weave-800">No warranty.</span>{" "}
          Trezo is provided as-is, without guarantees of accuracy or
          availability. Market data may be delayed or wrong.
        </p>
        <p>
          <span className="font-medium text-weave-800">Simulated results.</span>{" "}
          Paper-trading performance does not predict real returns. Real trading
          involves real risk, including the loss of capital.
        </p>
        <p className="text-sm text-weave-500">
          This is a working draft for a research-preview product. Proper terms
          of service should be reviewed by a professional before any
          real-money or public launch.
        </p>
      </div>
    </main>
  );
}
