"use client";

import { useEffect, useState } from "react";
import { Sidebar } from "./sidebar";
import { Menu, X } from "lucide-react";

export function MobileNav() {
  const [open, setOpen] = useState(false);

  // Lock body scroll while drawer is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="md:hidden p-2 rounded-md text-weave-700 hover:bg-weave-50"
        aria-label="Open navigation menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 bg-weave-800/40 z-40 md:hidden"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="fixed inset-y-0 left-0 w-72 bg-treasure-50 z-50 md:hidden border-r border-weave-100 pt-4 overflow-y-auto">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute top-3 right-3 p-1 rounded-md text-weave-700 hover:bg-weave-50"
              aria-label="Close navigation menu"
            >
              <X className="h-5 w-5" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </>
      )}
    </>
  );
}
