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
        {/* Neo-Obsidian typography — DM Sans (UI), Playfair Display
            (serif headers), JetBrains Mono (numbers). Loaded via a head
            <link> rather than a CSS @import so it never participates in
            Tailwind/PostCSS ordering (the @import broke a clean build). */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500;1,600&display=swap"
          rel="stylesheet"
        />
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
              + "var l=localStorage.getItem('trezo_lite');"
              + "document.documentElement.setAttribute('data-lite',l==='on'?'on':'off');"
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
