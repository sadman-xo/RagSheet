import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { AlertTriangle, Info, Loader2, Lock, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ title, subtitle, actions, children, className, bodyClass, testId }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
  testId?: string;
}) {
  return (
    <section className={cn("card flex min-w-0 flex-col", className)} data-testid={testId}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-2 px-4 pt-3.5">
          <div className="min-w-0">
            {title && <h3 className="truncate text-[13.5px] font-semibold text-slate-900">{title}</h3>}
            {subtitle && <p className="mt-0.5 truncate text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
        </header>
      )}
      <div className={cn("min-h-0 flex-1 p-4 pt-3", bodyClass)}>{children}</div>
    </section>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-slate-400", className)} />;
}

export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex h-full min-h-[120px] items-center justify-center gap-2 text-sm text-slate-400", className)}>
      <Spinner /> {label}
    </div>
  );
}

export function ErrorState({ message, className }: { message: string; className?: string }) {
  return (
    <div className={cn("flex h-full min-h-[100px] items-center justify-center gap-2 rounded-md border border-red-200 bg-red-50/60 p-4 text-sm text-red-800", className)}>
      <AlertTriangle className="h-4 w-4 shrink-0" /> {message}
    </div>
  );
}

export function Empty({ message = "No data for these filters.", className }: { message?: string; className?: string }) {
  return <div className={cn("flex h-full min-h-[100px] items-center justify-center text-sm text-slate-400", className)}>{message}</div>;
}

export function Badge({ children, tone = "slate", className, title }: {
  children: ReactNode;
  tone?: "slate" | "blue" | "green" | "amber" | "red" | "violet";
  className?: string;
  title?: string;
}) {
  const tones: Record<string, string> = {
    slate: "border-slate-200 bg-white text-slate-700",
    blue: "border-brand-200 bg-brand-50 text-brand-800",
    green: "border-emerald-200 bg-emerald-50/70 text-emerald-800",
    amber: "border-amber-200 bg-amber-50/70 text-amber-900",
    red: "border-red-200 bg-red-50/70 text-red-800",
    violet: "border-violet-200 bg-violet-50/70 text-violet-800",
  };
  return (
    <span className={cn("chip", tones[tone], className)} title={title}>
      {children}
    </span>
  );
}

export function LockedChip({ label }: { label: string }) {
  return (
    <Badge tone="slate" title="Set by your role. You cannot change it.">
      <Lock className="h-3 w-3" /> {label}
    </Badge>
  );
}

export function Notes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return (
    <div className="space-y-1">
      {notes.map((n) => (
        <p key={n} className="flex items-start gap-1.5 text-xs text-amber-800">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {n}
        </p>
      ))}
    </div>
  );
}

export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={4} className="z-50 max-w-xs rounded bg-slate-900 px-2 py-1 text-xs leading-snug text-slate-50 shadow-pop">
            {content}
            <Tooltip.Arrow className="fill-slate-900" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function Modal({ open, onOpenChange, title, children, wide }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-900/40" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[92vw] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-pop",
            wide ? "max-w-4xl" : "max-w-lg",
          )}
        >
          <div className="mb-3 flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="btn-ghost" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Dialog</Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Drawer({ open, onOpenChange, title, children, width = "max-w-xl" }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  width?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange} modal={false}>
      <Dialog.Portal>
        <Dialog.Content
          onInteractOutside={(e) => e.preventDefault()}
          className={cn("fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-slate-200 bg-white shadow-pop", width)}
        >
          <div className="flex h-14 items-center justify-between border-b border-slate-200 px-4">
            <Dialog.Title className="text-sm font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="btn-ghost" aria-label="Close">
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">Panel</Dialog.Description>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function Segmented<T extends string>({ value, options, onChange, size = "sm" }: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  size?: "sm" | "xs";
}) {
  return (
    <div className="inline-flex rounded-md border border-slate-200 bg-slate-100 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded font-medium transition",
            size === "xs" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-xs",
            value === o.value ? "bg-white text-slate-900 shadow-[0_0_0_1px_rgba(27,26,24,.08)]" : "text-slate-500 hover:text-slate-800",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 pt-1">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold leading-tight tracking-[-0.01em] text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
