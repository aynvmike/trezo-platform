import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { OnboardingForm } from "./onboarding-form";

export default async function OnboardingPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/sign-in?redirect=/onboarding");
  }

  // If already onboarded, skip ahead.
  const { data: profile } = await supabase
    .from("profiles")
    .select("onboarding_complete")
    .eq("user_id", user.id)
    .maybeSingle();

  if (profile?.onboarding_complete) {
    redirect("/dashboard");
  }

  return (
    <div className="min-h-screen bg-treasure-50">
      <div className="mx-auto max-w-2xl px-4 py-12 sm:py-16">
        <header className="mb-8">
          <p className="text-sm font-medium uppercase tracking-widest text-treasure-600">
            Welcome
          </p>
          <h1 className="mt-2 font-serif text-3xl text-weave-800 tracking-tight">
            Let&apos;s set the first layer.
          </h1>
          <p className="mt-3 text-weave-600 leading-relaxed">
            A few questions so Trezo can right-size every trade and tax estimate.
            Nothing here leaves your account.
          </p>
        </header>
        <OnboardingForm />
      </div>
    </div>
  );
}
