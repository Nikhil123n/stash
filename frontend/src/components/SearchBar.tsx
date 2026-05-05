import { Search, X } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import type { ArtifactOut } from "@/api"
import { searchArtifacts } from "@/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { formatDate } from "@/lib/format"

type SearchBarProps = {
  onSelect: (artifact: ArtifactOut) => void
}

export function SearchBar({ onSelect }: SearchBarProps) {
  const [q, setQ] = useState("")
  const [debounced, setDebounced] = useState("")

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(q.trim()), 300)
    return () => window.clearTimeout(handle)
  }, [q])

  const { data: results = [], isFetching } = useQuery({
    queryKey: ["artifact-search", debounced],
    queryFn: () => searchArtifacts(debounced),
    enabled: debounced.length >= 2,
  })

  const showOverlay = debounced.length >= 2 && (isFetching || results.length > 0)

  return (
    <div className="relative w-full sm:w-80">
      <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
      <Input
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="Search Stash"
        className="h-9 pl-8 pr-8"
      />
      {q && (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => {
            setQ("")
            setDebounced("")
          }}
          className="absolute right-1 top-1"
        >
          <X className="size-4" />
          <span className="sr-only">Clear search</span>
        </Button>
      )}

      {showOverlay && (
        <div className="absolute right-0 z-30 mt-2 max-h-96 w-full overflow-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg">
          {isFetching ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">Searching...</div>
          ) : (
            results.map((artifact) => (
              <button
                key={artifact.id}
                type="button"
                onClick={() => {
                  onSelect(artifact)
                  setQ("")
                  setDebounced("")
                }}
                className="w-full rounded-md px-3 py-2 text-left hover:bg-muted"
              >
                <div className="line-clamp-1 text-sm font-medium">{artifact.ai_title}</div>
                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="truncate">{artifact.category.name}</span>
                  <span className="shrink-0">{formatDate(artifact.created_at)}</span>
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
