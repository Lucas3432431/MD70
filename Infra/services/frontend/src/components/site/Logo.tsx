import { cn } from "@/lib/utils";

export function Logo({ className, sub = true }: { className?: string; sub?: boolean }) {
  return (
    <span className={cn("inline-flex flex-col leading-none", className)}>
      <span className="flex items-center gap-1.5 text-xl font-extrabold tracking-tight">
        <span className="inline-block h-3.5 w-3.5 bg-current [clip-path:polygon(0_0,100%_0,100%_100%,0_100%,0_40%,40%_40%,40%_0)]" aria-hidden />
        MD70
      </span>
      {sub && <span className="mt-1 text-[0.5rem] font-semibold tracking-[0.18em] opacity-70">IMÓVEIS E NEGÓCIOS</span>}
    </span>
  );
}
