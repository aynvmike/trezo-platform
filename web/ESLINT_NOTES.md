# ESLint configuration notes

(.eslintrc.json cannot carry comments -- a top-level "//" key made the whole config invalid and `next lint` refused to run at all, 2026-09-01.)

next/core-web-vitals is the base. The explicit @typescript-eslint plugin registration (2026-08-23) is what makes rules like @typescript-eslint/no-explicit-any RESOLVABLE. Several files carry eslint-disable-next-line comments for that rule; without the plugin registered, ESLint reports 'Definition for rule was not found' as an ERROR and next build fails - which is what turned CI red. This registers the plugin WITHOUT enabling any of its rule sets, so no new rules switch on and no existing code newly fails.
