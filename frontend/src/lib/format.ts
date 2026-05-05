export function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value))
}

export function getDomain(url: string | null): string {
  if (!url) return "Saved text"
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return url
  }
}

export function getFaviconUrl(url: string | null): string | null {
  if (!url) return null
  const domain = getDomain(url)
  if (!domain || domain === "Saved text") return null
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=64`
}
