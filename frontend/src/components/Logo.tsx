import { cn } from "@/lib/cn";

/** Panorama mark: a wide horizon arc over a baseline, with one point of interest. */
export function LogoMark({ className, tone = "light" }: { className?: string; tone?: "light" | "dark" }) {
  const ink = tone === "light" ? "#ffffff" : "#1b1a18";
  return (
    <svg viewBox="0 0 24 24" className={cn("h-6 w-6", className)} aria-hidden fill="none">
      <path d="M3 17.5a9 9 0 0 1 18 0" stroke={ink} strokeWidth="2" strokeLinecap="round" />
      <path d="M7 17.5a5 5 0 0 1 10 0" stroke={ink} strokeOpacity=".45" strokeWidth="2" strokeLinecap="round" />
      <path d="M2 21h20" stroke={ink} strokeWidth="2" strokeLinecap="round" />
      <circle cx="18.4" cy="9.6" r="2.2" fill="#eb6834" />
    </svg>
  );
}

export function Wordmark({ tone = "light", className }: { tone?: "light" | "dark"; className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark tone={tone} />
      <span className={cn("text-[15px] font-semibold tracking-[-0.01em]", tone === "light" ? "text-white" : "text-slate-900")}>Panorama</span>
    </span>
  );
}
