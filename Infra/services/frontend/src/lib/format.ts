const brlFmt = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const brlCompact = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 });

export const brl = (n: number) => brlFmt.format(n);
export const brlShort = (n: number) => brlCompact.format(n);
export const pct = (n: number, digits = 1, sign = true) =>
  `${sign && n > 0 ? "+" : ""}${n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;
export const pp = (n: number) =>
  `${n > 0 ? "+" : ""}${n.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} p.p.`;
export const dateBR = (iso: string) => new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("pt-BR");
const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
export const monthLabel = (ym: string) => {
  const [yearPart, monthPart] = ym.split("-");
  const monthIndex = Number(monthPart ?? "1") - 1;
  return `${MONTHS[monthIndex] ?? ""}/${String(yearPart ?? "").slice(2)}`;
};
