import { SiteNav } from "@/components/site/nav";
import { SiteFooter } from "@/components/site/footer";
import { Hero } from "@/components/site/hero";
import { SevenLayers } from "@/components/site/seven-layers";

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col depth-page">
      <SiteNav />
      <main className="flex-1">
        <Hero />
        <SevenLayers />
      </main>
      <SiteFooter />
    </div>
  );
}
