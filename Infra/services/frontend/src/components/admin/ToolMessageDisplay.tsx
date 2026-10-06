import { useState } from "react";
import {
  Building2, ShoppingCart, Users, Wallet,
  Search, Brain, Wrench, Layers,
  ChevronDown, ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Tool meta ───────────────────────────────────────────────────────────────
const TOOL_META: Record<string, { label: string; icon: React.ElementType }> = {
  md70_projetos:      { label: "Projetos",      icon: Building2    },
  md70_compras:       { label: "Compras",        icon: ShoppingCart },
  md70_crm:           { label: "CRM",            icon: Users        },
  md70_financeiro:    { label: "Financeiro",     icon: Wallet       },
  "web-search":       { label: "Busca na web",   icon: Search       },
  "chain-of-thought": { label: "Raciocínio",     icon: Brain        },
};

function getSummary(tool: string, parsed: Record<string, unknown>): string | null {
  if (!parsed?.success) return typeof parsed?.error === "string" ? parsed.error : null;
  const counts: [string, string][] = [
    ["projects",     "projeto"],
    ["purchases",    "compra"],
    ["leads",        "lead"],
    ["transactions", "transação"],
    ["items",        "item"],
  ];
  for (const [key, label] of counts) {
    const arr = parsed[key];
    if (Array.isArray(arr)) {
      const n = arr.length;
      return `${n} ${label}${n !== 1 ? (label.endsWith("ão") ? "ões" : "s") : ""}`;
    }
  }
  if (typeof parsed.total === "number") return `${parsed.total} resultado${parsed.total !== 1 ? "s" : ""}`;
  return null;
}

// ── Single tool card (shown inside the open group) ──────────────────────────
function ToolCard({ content, tool }: { content: string; tool: string | null }) {
  const toolKey = tool ?? "";
  const meta = TOOL_META[toolKey] ?? { label: toolKey || "Tool", icon: Wrench };
  const Icon = meta.icon;

  let parsed: Record<string, unknown> | null = null;
  try { parsed = JSON.parse(content); } catch { /* raw string */ }

  const summary = parsed ? getSummary(toolKey, parsed) : null;
  const isError = parsed?.success === false;

  return (
    <div className={cn(
      "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5",
      isError
        ? "border-destructive/30 bg-destructive/5"
        : "border-border/50 bg-muted/30",
    )}>
      <Icon className={cn("size-3.5 shrink-0", isError ? "text-destructive" : "text-muted-foreground")} />
      <span className={cn("text-sm font-medium", isError ? "text-destructive" : "text-foreground/80")}>
        {meta.label}
      </span>
      {summary && (
        <span className="text-xs text-muted-foreground">— {summary}</span>
      )}
    </div>
  );
}

// ── Group wrapper — "Uso de ferramentas" collapsible ────────────────────────
export interface ToolMessage {
  content: string;
  tool: string | null;
}

export function ToolCallGroup({ tools }: { tools: ToolMessage[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="my-0.5 ml-0.5">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <Layers className="size-3 shrink-0" />
        <span>Uso de ferramentas</span>
        {open
          ? <ChevronUp className="size-3 shrink-0" />
          : <ChevronDown className="size-3 shrink-0" />
        }
      </button>
      {open && (
        <div className="mt-1.5 flex flex-col gap-1.5">
          {tools.map((t, i) => (
            <ToolCard key={i} content={t.content} tool={t.tool} />
          ))}
        </div>
      )}
    </div>
  );
}
