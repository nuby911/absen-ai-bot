export const DAY_NAMES_ID: Record<number, string> = {
  1: "Senin",
  2: "Selasa",
  3: "Rabu",
  4: "Kamis",
  5: "Jumat",
  6: "Sabtu",
  7: "Minggu",
};

const WA_JID_SUFFIX_RE = /(?::\d+)?@(?:c\.us|s\.whatsapp\.net)$/i;

function parseIsoAsUtc(iso: string): Date {
  const trimmed = iso.trim().replace(" ", "T");
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(trimmed)
    ? trimmed
    : `${trimmed}Z`;
  return new Date(normalized);
}

export function formatDayOfWeek(day: number): string {
  return DAY_NAMES_ID[day] ?? `Hari ${day}`;
}

export function formatTimeShort(timeStr: string | null | undefined): string {
  if (!timeStr) return "-";
  const parts = timeStr.split(":");
  if (parts.length >= 2) {
    return `${parts[0].padStart(2, "0")}:${parts[1].padStart(2, "0")}`;
  }
  return timeStr;
}

export function formatWibDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "-";
  const trimmed = isoDate.trim();
  const date = /^\d{4}-\d{2}-\d{2}$/.test(trimmed)
    ? new Date(`${trimmed}T00:00:00Z`)
    : parseIsoAsUtc(trimmed);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat("id-ID", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatWibDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const date = parseIsoAsUtc(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return (
    new Intl.DateTimeFormat("id-ID", {
      timeZone: "Asia/Jakarta",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date) + " WIB"
  );
}

export function formatWibTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const date = parseIsoAsUtc(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return (
    new Intl.DateTimeFormat("id-ID", {
      timeZone: "Asia/Jakarta",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date) + " WIB"
  );
}

export function formatTodayWibIso(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const year = parts.find((p) => p.type === "year")?.value ?? "2026";
  const month = parts.find((p) => p.type === "month")?.value ?? "01";
  const day = parts.find((p) => p.type === "day")?.value ?? "01";
  return `${year}-${month}-${day}`;
}

export function normalizeWaPhoneForMatch(raw: string): string {
  const cleaned = raw.trim().replace(WA_JID_SUFFIX_RE, "");
  let digits = cleaned.replace(/\D/g, "");
  if (!digits) return "";
  if (digits.startsWith("0062")) {
    digits = "62" + digits.slice(4);
  } else if (digits.startsWith("620")) {
    digits = "62" + digits.slice(3);
  } else if (digits.startsWith("0")) {
    digits = "62" + digits.slice(1);
  } else if (digits.startsWith("8")) {
    digits = "62" + digits;
  }
  return digits;
}

export function isValidWaPhone(raw: string): boolean {
  const cleaned = raw.trim().replace(WA_JID_SUFFIX_RE, "");
  if (!cleaned || /[a-zA-Z]/.test(cleaned)) return false;
  const digits = normalizeWaPhoneForMatch(cleaned);
  return digits.startsWith("628") && digits.length >= 10 && digits.length <= 15;
}

export function formatWaPhonePreview(raw: string): string | null {
  const cleaned = raw.trim().replace(WA_JID_SUFFIX_RE, "");
  if (!cleaned || /[a-zA-Z]/.test(cleaned)) return null;
  const digits = normalizeWaPhoneForMatch(cleaned);
  if (!digits.startsWith("628") || digits.length < 4) return null;
  const local = digits.slice(2);
  const groups = [
    local.slice(0, 3),
    local.slice(3, 7),
    local.slice(7, 11),
    local.slice(11),
  ].filter(Boolean);
  return `+62 ${groups.join("-")}`;
}

export function matchesPhoneQuery(
  phoneWa: string | null | undefined,
  rawQuery: string
): boolean {
  if (!phoneWa) return false;
  const q = rawQuery.trim().toLowerCase();
  if (!q) return true;
  if (phoneWa.toLowerCase().includes(q)) return true;
  const normalizedPhone = normalizeWaPhoneForMatch(phoneWa);
  const normalizedQuery = normalizeWaPhoneForMatch(q);
  if (normalizedQuery.length >= 3 && normalizedPhone.includes(normalizedQuery)) {
    return true;
  }
  const rawDigits = q.replace(/\D/g, "");
  if (rawDigits.length >= 3 && phoneWa.replace(/\D/g, "").includes(rawDigits)) {
    return true;
  }
  return false;
}

export function formatWaPhoneDisplay(phone: string | null | undefined): string {
  if (!phone) return "-";
  const cleaned = phone.trim();
  if (!cleaned) return "-";
  if (cleaned.startsWith("+")) return cleaned;
  const normalized = normalizeWaPhoneForMatch(cleaned);
  if (normalized.startsWith("62")) {
    return `+${normalized}`;
  }
  return cleaned;
}

export function getInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}
