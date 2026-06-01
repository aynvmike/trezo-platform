import Link from "next/link";

export const metadata = { title: "Contact — Trezo" };

export default function ContactPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 sm:px-6 py-16">
      <Link href="/" className="text-sm text-weave-600 hover:underline">
        ← Back to Trezo
      </Link>
      <h1 className="mt-4 font-serif text-3xl text-weave-800 tracking-tight">
        Contact
      </h1>
      <div className="mt-6 space-y-4 text-weave-600 leading-relaxed">
        <p>
          Trezo is a personal project, built and maintained by its owner as a
          research preview.
        </p>
        <p>
          Questions, feedback, or issues are welcome. A contact address will
          be published here before Trezo is opened to anyone beyond its owner.
        </p>
        <p className="text-sm text-weave-500">
          Placeholder page — the owner can replace this with a preferred
          contact method (email, form, or support address) when ready.
        </p>
      </div>
    </main>
  );
}
