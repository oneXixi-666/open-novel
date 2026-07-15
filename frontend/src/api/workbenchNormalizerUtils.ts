import { authorText } from "../utils/authorText";

export function safeDisplayText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text) {
    return "";
  }
  if (/token|password|secret|bearer/i.test(text)) {
    return "[已隐藏敏感内容]";
  }
  if (/(^|[\s(["'：:])(?:\/Users\/|\/private\/|\/var\/|\/tmp\/|[A-Za-z]:\\)/.test(text)) {
    return "[已隐藏本地路径]";
  }
  return authorText(text);
}

export function asArray<T>(value: T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : [];
}

export function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(safeDisplayText).filter(Boolean) : [];
}

export function normalizeIdList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? "").trim()).filter(Boolean) : [];
}

export function normalizeNonNegativeNumber(value: unknown): number {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Math.max(0, Math.round(numberValue)) : 0;
}

export function normalizePercent(value: unknown): number {
  return Math.min(100, Math.max(0, normalizeNonNegativeNumber(value)));
}

export function normalizeDetails(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => [authorText(key), safeDisplayText(item)])
      .filter(([key, item]) => key && item)
  );
}
