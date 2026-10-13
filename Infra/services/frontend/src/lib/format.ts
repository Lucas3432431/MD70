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

export function maskCpf(v: string): string {
  const d = v.replace(/\D/g, "").slice(0, 11);
  if (d.length <= 3) return d;
  if (d.length <= 6) return `${d.slice(0, 3)}.${d.slice(3)}`;
  if (d.length <= 9) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6)}`;
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
}

export function maskPhone(v: string): string {
  const d = v.replace(/\D/g, "").slice(0, 11);
  if (d.length === 0) return "";
  if (d.length <= 2) return `(${d}`;
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

export function maskBRL(v: string): string {
  const digits = v.replace(/\D/g, "");
  if (!digits) return "";
  const n = parseInt(digits, 10);
  return (n / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function parseBRL(masked: string): number {
  return parseFloat(masked.replace(/\./g, "").replace(",", ".")) || 0;
}

function _countWeekdays(start: Date, endExclusive: Date): number {
  let count = 0;
  const d = new Date(start);
  while (d < endExclusive) {
    const dow = d.getDay();
    if (dow >= 1 && dow <= 5) count++;
    d.setDate(d.getDate() + 1);
  }
  return count;
}

function _parseDay(s: string): Date {
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function calcCdiFactor(fromDateStr: string, toDateStr: string, ratesMap: Map<string, number>): number {
  const from = _parseDay(fromDateStr);
  const to = _parseDay(toDateStr);
  if (from >= to) return 1.0;
  let factor = 1.0;
  let cur = new Date(from);
  while (cur < to) {
    const year = cur.getFullYear();
    const month = cur.getMonth();
    const monthStart = new Date(year, month, 1);
    const monthEnd = new Date(year, month + 1, 1);
    const periodEnd = monthEnd < to ? monthEnd : to;
    const ym = `${year}-${String(month + 1).padStart(2, "0")}`;
    const monthlyRate = (ratesMap.get(ym) ?? 0) / 100;
    if (monthlyRate > 0) {
      const totalBdays = _countWeekdays(monthStart, monthEnd);
      const periodBdays = _countWeekdays(cur, periodEnd);
      if (totalBdays > 0 && periodBdays > 0)
        factor *= Math.pow(1 + monthlyRate, periodBdays / totalBdays);
    }
    cur = new Date(monthEnd);
  }
  return factor;
}

export function calcCdiGrowth(fromDateStr: string, principal: number, ratesMap: Map<string, number>): number {
  if (principal <= 0) return principal;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  return principal * calcCdiFactor(fromDateStr, todayStr, ratesMap);
}

export function maskCnpjCpf(v: string): string {
  const d = v.replace(/\D/g, "");
  if (d.length <= 11) return maskCpf(d);
  const s = d.slice(0, 14);
  if (s.length <= 2) return s;
  if (s.length <= 5) return `${s.slice(0, 2)}.${s.slice(2)}`;
  if (s.length <= 8) return `${s.slice(0, 2)}.${s.slice(2, 5)}.${s.slice(5)}`;
  if (s.length <= 12) return `${s.slice(0, 2)}.${s.slice(2, 5)}.${s.slice(5, 8)}/${s.slice(8)}`;
  return `${s.slice(0, 2)}.${s.slice(2, 5)}.${s.slice(5, 8)}/${s.slice(8, 12)}-${s.slice(12)}`;
}
