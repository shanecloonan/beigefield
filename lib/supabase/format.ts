export function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

export function rowCountLabel(count: string): string {
  return count === "1" ? "1 row" : `${count} rows`;
}
