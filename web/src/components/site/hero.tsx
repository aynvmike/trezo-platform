import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ProtectiveRings } from "./protective-rings";

export function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-4 sm:px-6 pt-16 pb-12 sm:pt-24 sm:pb-20">
      <div className="grid items-center gap-10 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            Wealth that compounds
          </p>
          <h1 className="mt-3 font-serif text-4xl sm:text-5xl lg:text-6xl text-weave-800 tracking-tight leading-[1.05]">
            Layer by Layer.
            <br />
            <span className="text-treasure-400">Trade by Trade.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-weave-600 leading-relaxed">
            Trezo is a multi-layer automated wealth-building platform — a woven
            basket of seven protective layers that work together to build
            wealth slowly, safely, and ethically.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/sign-up">
              <Button size="lg" className="bg-[#c4964a] text-[#1c130a] hover:bg-[#b3863f]">Begin weaving</Button>
            </Link>
            <Link href="/sign-in">
              <Button variant="outline" size="lg">I have an account</Button>
            </Link>
          </div>
          <p className="mt-6 text-xs text-weave-500">
            You own your accounts. Trezo never custodies funds.
          </p>
        </div>

        <ProtectiveRings />
      </div>
    </section>
  );
}
