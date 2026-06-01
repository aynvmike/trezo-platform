import Link from "next/link";

export default function AuthLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-treasure-50 flex flex-col">
      <header className="border-b border-weave-100 bg-treasure-50/80 backdrop-blur">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 h-16 flex items-center">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-weave-600 text-treasure-50 font-serif text-lg">T</span>
            <span className="font-serif text-xl tracking-tight text-weave-800">Trezo</span>
          </Link>
        </div>
      </header>
      <main className="flex-1 grid place-items-center px-4 py-12">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
