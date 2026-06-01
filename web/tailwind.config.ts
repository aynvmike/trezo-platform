import type { Config } from "tailwindcss";

/**
 * Trezo palette — warm, calm, protective.
 *
 * Phase 12b (dark mode): the `treasure` and `weave` scales, and the
 * card surface (`white`), are CSS-variable-backed. The actual colours
 * live in globals.css under `:root` (light) and `.dark` (dark), so
 * every existing `bg-treasure-50`, `text-weave-800`, `bg-white` class
 * flips theme automatically — no per-component dark: variants needed.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        // Card / panel surface — was literal white; themed so cards
        // flip to a dark surface in dark mode.
        white: "rgb(var(--surface) / <alpha-value>)",
        treasure: {
          50: "rgb(var(--treasure-50) / <alpha-value>)",
          100: "rgb(var(--treasure-100) / <alpha-value>)",
          200: "rgb(var(--treasure-200) / <alpha-value>)",
          300: "rgb(var(--treasure-300) / <alpha-value>)",
          400: "rgb(var(--treasure-400) / <alpha-value>)",
          500: "rgb(var(--treasure-500) / <alpha-value>)",
          600: "rgb(var(--treasure-600) / <alpha-value>)",
          700: "rgb(var(--treasure-700) / <alpha-value>)",
          800: "rgb(var(--treasure-800) / <alpha-value>)",
          900: "rgb(var(--treasure-900) / <alpha-value>)"
        },
        weave: {
          50: "rgb(var(--weave-50) / <alpha-value>)",
          100: "rgb(var(--weave-100) / <alpha-value>)",
          200: "rgb(var(--weave-200) / <alpha-value>)",
          300: "rgb(var(--weave-300) / <alpha-value>)",
          400: "rgb(var(--weave-400) / <alpha-value>)",
          500: "rgb(var(--weave-500) / <alpha-value>)",
          600: "rgb(var(--weave-600) / <alpha-value>)",
          700: "rgb(var(--weave-700) / <alpha-value>)",
          800: "rgb(var(--weave-800) / <alpha-value>)",
          900: "rgb(var(--weave-900) / <alpha-value>)"
        },
        emerald: {
          50: "rgb(var(--emerald-50) / <alpha-value>)",
          100: "rgb(var(--emerald-100) / <alpha-value>)",
          200: "rgb(var(--emerald-200) / <alpha-value>)",
          300: "rgb(var(--emerald-300) / <alpha-value>)",
          400: "rgb(var(--emerald-400) / <alpha-value>)",
          500: "rgb(var(--emerald-500) / <alpha-value>)",
          600: "rgb(var(--emerald-600) / <alpha-value>)",
          700: "rgb(var(--emerald-700) / <alpha-value>)",
          800: "rgb(var(--emerald-800) / <alpha-value>)",
          900: "rgb(var(--emerald-900) / <alpha-value>)"
        },
        red: {
          50: "rgb(var(--red-50) / <alpha-value>)",
          100: "rgb(var(--red-100) / <alpha-value>)",
          200: "rgb(var(--red-200) / <alpha-value>)",
          300: "rgb(var(--red-300) / <alpha-value>)",
          400: "rgb(var(--red-400) / <alpha-value>)",
          500: "rgb(var(--red-500) / <alpha-value>)",
          600: "rgb(var(--red-600) / <alpha-value>)",
          700: "rgb(var(--red-700) / <alpha-value>)",
          800: "rgb(var(--red-800) / <alpha-value>)",
          900: "rgb(var(--red-900) / <alpha-value>)"
        },
        amber: {
          50: "rgb(var(--amber-50) / <alpha-value>)",
          100: "rgb(var(--amber-100) / <alpha-value>)",
          200: "rgb(var(--amber-200) / <alpha-value>)",
          300: "rgb(var(--amber-300) / <alpha-value>)",
          400: "rgb(var(--amber-400) / <alpha-value>)",
          500: "rgb(var(--amber-500) / <alpha-value>)",
          600: "rgb(var(--amber-600) / <alpha-value>)",
          700: "rgb(var(--amber-700) / <alpha-value>)",
          800: "rgb(var(--amber-800) / <alpha-value>)",
          900: "rgb(var(--amber-900) / <alpha-value>)"
        }
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        serif: ["ui-serif", "Georgia", "Cambria", "serif"]
      }
    }
  },
  plugins: []
};

export default config;
