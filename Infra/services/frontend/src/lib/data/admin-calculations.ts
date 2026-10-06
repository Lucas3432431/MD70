import type { AdminData, Purchase, Quote } from "./admin-types";

export const quoteTotal = (quote: Quote) => quote.value + quote.shipping - quote.discount;
export const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
export function projectSummary(data: AdminData, projectId: string) {
  const project = data.projects.find((p) => p.id === projectId);
  const lines = data.budgets.filter((line) => line.projectId === projectId);
  const movements = data.movements.filter((m) => m.projectId === projectId);
  const spent = sum(movements.filter((m) => m.direction === "Saída" && m.status === "Realizado" && m.category !== "Capital").map((m) => m.value));
  const committed = sum(data.purchases.filter((p) => p.projectId === projectId && (p.status === "Aguardando entrega" || p.status === "Entregue") && !p.paidAt).map((p) => {
    const chosen = p.quotes.find((q) => q.id === p.selectedQuoteId);
    return chosen ? quoteTotal(chosen) : 0;
  })) + sum(movements.filter((m) => m.status === "Comprometido" && m.direction === "Saída" && !m.purchaseId).map((m) => m.value));
  const estimatedRemaining = sum(lines.map((l) => l.remaining));
  const budget = sum(lines.map((l) => l.planned));
  const forecast = spent + committed + estimatedRemaining;
  const capitalEntradas = sum(movements.filter((m) => m.category === "Capital" && m.direction === "Entrada" && m.status === "Realizado").map((m) => m.value));
  const capitalSaidas = sum(movements.filter((m) => m.category === "Capital" && m.direction === "Saída" && m.status === "Realizado").map((m) => m.value));
  const capitalValue = capitalEntradas - capitalSaidas;
  return { project, capital: capitalValue, spent, committed, estimatedRemaining, budget, forecast, cash: capitalValue - spent, saldoForecast: forecast - spent };
}
export type BudgetStatus = "ok" | "warn" | "over";
export function budgetStatus(balance: number, budget: number): BudgetStatus {
  if (balance >= 0) return "ok";
  if (budget > 0 && -balance / budget < 0.1) return "warn";
  return "over";
}

export function canApprove(purchase: Purchase, selectedQuoteId: string, reason: string, minimum: number) {
  const chosen = purchase.quotes.find((q) => q.id === selectedQuoteId);
  if (!chosen) return false;
  const cheapest = Math.min(...purchase.quotes.map(quoteTotal));
  return (purchase.quotes.length >= minimum && quoteTotal(chosen) <= cheapest) || reason.trim().length > 0;
}