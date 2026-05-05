import { AlertTriangle, FileText, Link2, PlayCircle } from "lucide-react"

import type { ArtifactOut } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { formatDate, getDomain, getFaviconUrl } from "@/lib/format"
import { cn } from "@/lib/utils"

type ArtifactCardProps = {
  artifact: ArtifactOut
  onClick: () => void
}

export function ArtifactCard({ artifact, onClick }: ArtifactCardProps) {
  const favicon = getFaviconUrl(artifact.raw_url)

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onClick()
      }}
      className={cn(
        "group overflow-hidden rounded-lg border bg-card text-left shadow-sm transition duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        artifact.needs_review && "border-amber-300",
      )}
    >
      {artifact.source_type === "image" && artifact.r2_url ? (
        <div className="relative min-h-52 overflow-hidden">
          <img
            src={artifact.r2_url}
            alt={artifact.ai_title}
            className="h-full min-h-52 w-full object-cover"
          />
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-3 pt-12 text-white">
            <p className="line-clamp-2 text-sm font-semibold">{artifact.ai_title}</p>
          </div>
        </div>
      ) : artifact.source_type === "video_file" ? (
        <div className="relative flex min-h-44 items-center justify-center bg-zinc-100">
          {artifact.r2_url ? (
            <video src={artifact.r2_url} className="h-44 w-full object-cover" muted preload="metadata" />
          ) : (
            <div className="flex h-44 w-full items-center justify-center bg-muted">
              <PlayCircle className="size-10 text-muted-foreground" />
            </div>
          )}
          <div className="absolute inset-0 flex items-center justify-center bg-black/10">
            <PlayCircle className="size-12 text-white drop-shadow" />
          </div>
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-3 pt-12 text-white">
            <p className="line-clamp-2 text-sm font-semibold">{artifact.ai_title}</p>
          </div>
        </div>
      ) : artifact.source_type === "text" ? (
        <div className="space-y-3 p-4">
          <FileText className="size-5 text-muted-foreground" />
          <div>
            <h3 className="line-clamp-2 text-sm font-semibold">{artifact.ai_title}</h3>
            <p className="mt-2 line-clamp-4 text-sm text-muted-foreground">
              {artifact.ai_summary.slice(0, 120)}
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3 p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {favicon ? <img src={favicon} alt="" className="size-4" /> : <Link2 className="size-4" />}
            <span className="truncate">{getDomain(artifact.raw_url)}</span>
          </div>
          <h3 className="line-clamp-3 text-sm font-semibold">{artifact.ai_title}</h3>
          <p className="line-clamp-3 text-sm text-muted-foreground">{artifact.ai_summary}</p>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 border-t bg-card/95 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {artifact.needs_review && (
            <span title="Needs review" className="inline-flex text-amber-500">
              <AlertTriangle className="size-3.5" />
            </span>
          )}
          <Badge variant="secondary" className="max-w-36 truncate">
            {artifact.category.name}
          </Badge>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{formatDate(artifact.created_at)}</span>
      </div>
    </Card>
  )
}
