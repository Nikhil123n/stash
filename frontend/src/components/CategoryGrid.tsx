import { Archive, ImageIcon } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"

import { getCategories } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export function CategoryGrid() {
  const navigate = useNavigate()
  const { data: categories = [], isLoading } = useQuery({
    queryKey: ["categories"],
    queryFn: getCategories,
  })

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-44 rounded-lg" />
        ))}
      </div>
    )
  }

  if (!categories.length) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed bg-card px-6 text-center">
        <Archive className="mb-3 size-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">No content yet - forward something to @StashBot</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {categories.map((category) => (
        <Card
          key={category.id}
          role="button"
          tabIndex={0}
          onClick={() => navigate(`/c/${category.slug}`)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") navigate(`/c/${category.slug}`)
          }}
          className="rounded-lg transition duration-200 hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <CardContent className="space-y-4 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-sm font-semibold">
                  {category.icon || category.name.slice(0, 1)}
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-semibold">{category.name}</h2>
                  <Badge variant="secondary" className="mt-1">
                    {category.item_count}
                  </Badge>
                </div>
              </div>
            </div>

            <div className="flex h-12 gap-1 overflow-hidden rounded-md bg-muted p-1">
              {category.recent_thumbnails.length ? (
                category.recent_thumbnails.slice(0, 3).map((thumbnail) => (
                  <img
                    key={thumbnail}
                    src={thumbnail}
                    alt=""
                    className="h-full min-w-0 flex-1 rounded object-cover"
                  />
                ))
              ) : (
                <div className="flex w-full items-center justify-center text-muted-foreground">
                  <ImageIcon className="size-4" />
                </div>
              )}
            </div>

            {!!category.subcategories.length && (
              <div className="flex flex-wrap gap-1">
                {category.subcategories.slice(0, 3).map((subcategory) => (
                  <span
                    key={subcategory.id}
                    className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground"
                  >
                    {subcategory.name}
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
