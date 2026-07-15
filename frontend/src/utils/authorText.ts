export function authorText(value: unknown) {
  const text = value == null ? "" : String(value);
  return text
    .replace(/(?:^|[\s(["'：:])(?:\/Users\/|\/private\/|\/var\/|\/tmp\/|[A-Za-z]:\\)[^\s，。；;、)）\]"']+/g, " [已隐藏本地路径]")
    .replace(/\b(?:job|run)[_-]?[a-z0-9]{4,}\b/gi, "[已隐藏运行编号]")
    .replace(/\b(?:job|run)[-_ ]?id[:：]?\s*[A-Za-z0-9_.:-]+/gi, "任务编号已隐藏")
    .replace(/\b[a-f0-9]{8,}-[a-f0-9-]{12,}\b/gi, "[已隐藏运行编号]")
    .replace(/\b(?:output|draft|report)?path[:：]?\s*[^\s，。；;]+/gi, "路径已隐藏");
}
