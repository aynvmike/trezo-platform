import Link from "next/link";
import { Button } from "@/components/ui/button";

export function SiteNav() {
  return (
    <header className="w-full border-b border-weave-100 bg-treasure-50/80 backdrop-blur supports-[backdrop-filter]:bg-treasure-50/60">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-weave-600 text-treasure-50 font-serif text-lg">T</span>
          <span className="font-serif text-xl tracking-tight text-weave-800">Trezo</span>
        </Link>
        <nav className="flex items-center gap-2 sm:gap-3">
          <Link href="/sign-in">
            <Button variant="ghost" size="sm">Sign in</Button>
          </Link>
          <Link href="/sign-up">
            <Button size="sm" className="bg-[#c4964a] text-[#1c130a] hover:bg-[#b3863f]">Get started</Button>
          </Link>
        </nav>
      </div>
    </header>
  );
}
