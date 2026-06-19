import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/dashboard/sidebar";
import { MobileNav } from "@/components/dashboard/mobile-nav";
import { AgentTicker } from "@/components/dashboard/agent-ticker";
import { HelpNudge } from "@/components/dashboard/help-nudge";
import { ThemeToggle } from "@/components/dashboard/theme-toggle";
import { LiveBanner } from "@/components/dashboard/live-banner";
import { ExperienceToggle } from "@/components/dashboard/experience-toggle";
import { LiteToggle } from "@/components/dashboard/lite-toggle";
import { HelpChat } from "@/components/dashboard/help-chat";
import { RegimeAlertBanner } from "@/components/dashboard/regime-alert-banner";

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode;
}) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) redirect("/sign-in?redirect=/dashboard");

  const { data: profile } = await supabase
    .from("profiles")
    .select("display_name, onboarding_complete")
    .eq("user_id", user.id)
    .maybeSingle();

  if (!profile?.onboarding_complete) redirect("/onboarding");

  return (
    <div className="min-h-screen bg-treasure-50">
      <LiveBanner />
      <header className="border-b border-weave-100 bg-treasure-50/85 backdrop-blur sticky top-0 z-30">
        <div className="flex items-center justify-between px-4 sm:px-6 h-16">
          <div className="flex items-center gap-2">
            <MobileNav />
            <Link href="/dashboard" className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-md bg-weave-600 text-treasure-50 font-serif text-lg">
                T
              </span>
              <span className="font-serif text-xl tracking-tight text-weave-800">Trezo</span>
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <ExperienceToggle />
            <LiteToggle />
            <ThemeToggle />
            <span className="hidden sm:inline text-sm text-weave-500">
              Hi, {profile?.display_name ?? "friend"}
            </span>
            <form action="/auth/sign-out" method="post">
              <Button variant="ghost" size="sm" type="submit">
                Sign out
              </Button>
            </form>
          </div>
        </div>
        {/* Live agent ticker — scrolls latest messages across every dashboard page */}
        <AgentTicker />
      </header>

      <div className="flex">
        <aside className="hidden md:block w-64 shrink-0 border-r border-weave-100 min-h-[calc(100vh-4rem)] bg-treasure-50/40">
          <Sidebar />
        </aside>
        <main className="flex-1 min-w-0 depth-page">{children}</main>
      </div>

      <HelpNudge />
      <HelpChat />
      <RegimeAlertBanner />
    </div>
  );
}
