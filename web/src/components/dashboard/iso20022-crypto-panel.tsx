import { Disclosure } from "@/components/ui/disclosure";

/**
 * Plain-language explainer for why Trezo's crypto watchlist now
 * includes the ISO 20022-aligned cluster (XRP / XLM / ALGO / HBAR /
 * QNT / XDC / IOTA / XYO).
 *
 * Important: this is awareness + market context, not investment
 * advice. The ISO 20022 standard does NOT endorse coins; these
 * projects are positioned by themselves as technically compatible
 * with ISO 20022-formatted messages.
 *
 * Rendered as a Disclosure so it doesn't grow the page when collapsed.
 * Mike can re-read it whenever and the casual user can skip it.
 */
export function Iso20022CryptoPanel() {
  return (
    <Disclosure title="Why the crypto watchlist is wider now (ISO 20022)">
      <div className="space-y-3 text-sm text-weave-700 leading-relaxed">
        <p>
          Trezo&apos;s payments foundation runs on ISO 20022 — the global
          messaging standard now used by Fedwire, FedNow, RTP, CHAPS,
          SEPA Inst, and the SWIFT MX migration. The same horizon
          applies to crypto: the coins below are the ones the
          institutional-payments narrative most often names as
          positioned to interoperate with that standard.
        </p>

        <div className="rounded-lg border border-weave-100 bg-white p-3">
          <p className="text-xs font-medium uppercase tracking-widest text-weave-500 mb-2">
            Coins added to the awareness set
          </p>
          <ul className="grid sm:grid-cols-2 gap-y-1.5 text-xs font-mono">
            <li>
              <span className="text-weave-800">XRP</span> — cross-border
              settlement (Ripple)
            </li>
            <li>
              <span className="text-weave-800">XLM</span> — remittance +
              tokenised assets (Stellar)
            </li>
            <li>
              <span className="text-weave-800">ALGO</span> — central-bank
              pilots (Algorand)
            </li>
            <li>
              <span className="text-weave-800">HBAR</span> —
              enterprise-governed DLT (Hedera)
            </li>
            <li>
              <span className="text-weave-800">QNT</span> — banking ↔ DLT
              interop (Quant / Overledger)
            </li>
            <li>
              <span className="text-weave-800">XDC</span> — trade finance,
              tokenised RWAs (XinFin)
            </li>
            <li>
              <span className="text-weave-800">IOTA</span> — M2M
              settlement (IOTA Foundation)
            </li>
            <li>
              <span className="text-weave-800">XYO</span> — geospatial
              proof-of-location (XYO Network)
            </li>
          </ul>
        </div>

        <p>
          <span className="font-medium">How Trezo uses this list.</span>{" "}
          The bot now reads price + volume for all of these coins so the
          Cross-asset Awareness panel reflects the full picture, and the
          Crypto Scanner can place trades on them when its setup
          conditions fire. Stops and targets are sized by{" "}
          <span className="font-mono">liquidity tier</span>: high-liquidity
          names like XRP and ALGO get tighter risk; thinner names like
          XDC and XYO get wider stops automatically.
        </p>

        <p className="text-xs text-weave-500 italic">
          Awareness, not endorsement. ISO 20022 is a messaging standard
          — it does not endorse individual coins. These projects
          position themselves as technically compatible. Trezo&apos;s
          risk rules apply per coin regardless.
        </p>
      </div>
    </Disclosure>
  );
}
