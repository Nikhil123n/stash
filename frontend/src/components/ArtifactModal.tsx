import { ExternalLink, FolderInput, Trash2 } from "lucide-react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import type { ArtifactDetail, ArtifactOut, CategoryOut } from "@/api"
import { deleteArtifact, getArtifact, recategorize } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { formatDate } from "@/lib/format"

type ArtifactModalProps = {
  artifact: ArtifactOut | null
  categories: CategoryOut[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ArtifactModal({ artifact, categories, open, onOpenChange }: ArtifactModalProps) {
  const queryClient = useQueryClient()
  const [showCategoryPicker, setShowCategoryPicker] = useState(false)
  const [selectedCategoryId, setSelectedCategoryId] = useState("")

  const detailQuery = useQuery({
    queryKey: ["artifact", artifact?.id],
    queryFn: () => getArtifact(artifact!.id),
    enabled: open && !!artifact,
  })

  const detail = (detailQuery.data ?? artifact) as ArtifactDetail | ArtifactOut | null

  const recategorizeMutation = useMutation({
    mutationFn: () => recategorize(detail!.id, selectedCategoryId),
    onSuccess: async () => {
      setShowCategoryPicker(false)
      await queryClient.invalidateQueries({ queryKey: ["categories"] })
      await queryClient.invalidateQueries({ queryKey: ["artifacts"] })
      await queryClient.invalidateQueries({ queryKey: ["artifact", detail?.id] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteArtifact(detail!.id),
    onSuccess: async () => {
      onOpenChange(false)
      await queryClient.invalidateQueries({ queryKey: ["categories"] })
      await queryClient.invalidateQueries({ queryKey: ["artifacts"] })
    },
  })

  if (!detail) return null

  const categoryValue = selectedCategoryId || detail.category.id
  const transcript = "ai_transcript" in detail ? detail.ai_transcript : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="pr-10 text-xl">{detail.ai_title}</DialogTitle>
          <DialogDescription>
            {detail.category.name}
            {detail.subcategory ? ` / ${detail.subcategory.name}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {detail.source_type === "image" && detail.r2_url && (
            <img
              src={detail.r2_url}
              alt={detail.ai_title}
              className="max-h-[440px] w-full rounded-lg object-contain bg-muted"
            />
          )}

          <p className="text-sm leading-6 text-foreground">{detail.ai_summary}</p>

          <div className="flex flex-wrap gap-2">
            {detail.ai_tags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
            {detail.needs_review && <Badge className="bg-amber-100 text-amber-800">Low confidence</Badge>}
          </div>

          {transcript && (
            <details className="rounded-lg border bg-muted/35 p-3">
              <summary className="cursor-pointer text-sm font-medium">Transcript</summary>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                {transcript}
              </p>
            </details>
          )}

          <div className="grid gap-3 rounded-lg border bg-card p-3 text-sm text-muted-foreground sm:grid-cols-2">
            <div>
              <span className="font-medium text-foreground">Created</span>
              <div>{formatDate(detail.created_at)}</div>
            </div>
            <div>
              <span className="font-medium text-foreground">Views</span>
              <div>{detail.view_count}</div>
            </div>
          </div>

          {showCategoryPicker && (
            <div className="rounded-lg border bg-muted/35 p-3">
              <label htmlFor="category-picker" className="text-sm font-medium">
                Move to category
              </label>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <select
                  id="category-picker"
                  value={categoryValue}
                  onChange={(event) => setSelectedCategoryId(event.target.value)}
                  className="h-9 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  onClick={() => recategorizeMutation.mutate()}
                  disabled={recategorizeMutation.isPending || categoryValue === detail.category.id}
                >
                  Confirm
                </Button>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          {detail.raw_url && (
            <Button asChild variant="outline">
              <a href={detail.raw_url} target="_blank" rel="noreferrer">
                <ExternalLink className="size-4" />
                Open original
              </a>
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setSelectedCategoryId(detail.category.id)
              setShowCategoryPicker((value) => !value)
            }}
          >
            <FolderInput className="size-4" />
            Re-categorize
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => {
              if (window.confirm("Delete this artifact?")) deleteMutation.mutate()
            }}
            disabled={deleteMutation.isPending}
          >
            <Trash2 className="size-4" />
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
