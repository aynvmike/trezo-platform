import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trezo — Layer by Layer. Trade by Trade.",
  description:
    "Trezo is a multi-layer automated wealth-building platform. Like maternal love — every layer protects the one beneath it.",
  applicationName: "Trezo",
  authors: [{ name: "Trezo" }],
  icons: {
    icon: "/favicon.svg"
  }
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Applies the saved theme and experience level before paint —
            no flash of the wrong mode. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{"
              + "var t=localStorage.getItem('trezo_theme');"
              + "var d=t==='dark'||(!t&&window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches);"
              + "if(d){document.documentElement.classList.add('dark');}"
              + "var x=localStorage.getItem('trezo_experience');"
              + "document.documentElement.setAttribute('data-experience',x==='pro'?'pro':'beginner');"
              + "}catch(e){}})();"
          }}
        />
      </head>
      <body className="min-h-screen bg-treasure-50 text-weave-800 antialiased">
        {children}
      </body>
    </html>
  );
}
