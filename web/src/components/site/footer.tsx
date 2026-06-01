import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-weave-100 bg-treasure-100/60">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        <figure className="mx-auto max-w-2xl text-center">
          <blockquote className="font-serif text-lg italic text-weave-700 leading-relaxed">
            &ldquo;Like maternal love — not everything will be ok, but the love
            tries to keep whatever it is protecting safe, layer after layer,
            giving its all.&rdquo;
          </blockquote>
          <figcaption className="mt-3 text-sm text-weave-500">
            — the Woven Basket philosophy
          </figcaption>
        </figure>
        <div className="mt-10 flex flex-col items-center gap-3 text-sm text-weave-500 sm:flex-row sm:justify-between">
          <p>© {new Date().getFullYear()} Trezo. Built layer by layer.</p>
          <nav className="flex gap-4">
            <Link href="/privacy" className="hover:text-weave-700">Privacy</Link>
            <Link href="/terms" className="hover:text-weave-700">Terms</Link>
            <Link href="/contact" className="hover:text-weave-700">Contact</Link>
          </nav>
        </div>
      </div>
    </footer>
  );
}
