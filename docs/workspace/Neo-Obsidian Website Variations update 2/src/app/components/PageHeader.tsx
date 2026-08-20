import { motion } from "motion/react";
import { useState } from "react";
import { ChevronDown } from "lucide-react";

type Props = {
  eyebrow: string;
  title: string;
  subtitle: string;
  explainer?: string;
  action?: React.ReactNode;
};

export function PageHeader({ eyebrow, title, subtitle, explainer, action }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex items-start justify-between gap-6">
      <div className="flex-1">
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="text-[11px] uppercase tracking-widest mb-2"
          style={{ color: "var(--treasure)", letterSpacing: "0.12em", fontWeight: 600 }}
        >
          {eyebrow}
        </motion.div>
        <h1 style={{ fontFamily: "var(--font-serif)", fontSize: "32px", fontWeight: 500, lineHeight: 1.1, color: "var(--foreground)" }}>
          {title}
        </h1>
        <p className="text-[13px] mt-2 max-w-2xl" style={{ color: "var(--muted-foreground)" }}>
          {subtitle}
        </p>

        {explainer && (
          <div className="mt-3">
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-1.5 text-[11px] transition-colors"
              style={{ color: "var(--muted-foreground)" }}
            >
              <motion.span animate={{ rotate: open ? 0 : -90 }} transition={{ duration: 0.2 }}>
                <ChevronDown size={11} />
              </motion.span>
              <span>{open ? "Hide" : "New here? Quick primer"}</span>
            </button>
            <motion.div
              initial={false}
              animate={{ height: open ? "auto" : 0, opacity: open ? 1 : 0 }}
              transition={{ duration: 0.25 }}
              style={{ overflow: "hidden" }}
            >
              <p className="text-[12px] mt-2 max-w-2xl leading-relaxed px-3 py-2 rounded-md border border-dashed border-border" style={{ color: "var(--muted-foreground)", background: "var(--muted)" }}>
                {explainer}
              </p>
            </motion.div>
          </div>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
