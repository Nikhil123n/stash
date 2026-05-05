import Masonry from "react-masonry-css"
import { ArrowLeft, Loader2 } from "lucide-react"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"

import type { ArtifactOut } from "@/api"
import { getArtifacts, getCategories } from "@/api"
import { ArtifactCard } from "@/components/ArtifactCard"
import { ArtifactModal } from "@/components/ArtifactModal"
import { SearchBar } from "@/components/SearchBar"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

const breakpointCols = { default: 4, 1100: 3, 700: 2, 500: 1 }

export function CategoryDetail() {
  const { slug } = useParams()
  const [selectedSub, setSelectedSub] = useState("all")
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactOut | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: getCategories,
  })
  const categories = categoriesQuery.data ?? []
  const category = categories.find((item) => item.slug === slug)
  const subcategorySlugs = category?.subcategories.map((subcategory) => subcategory.slug) ?? []
  const activeSub = selectedSub === "all" || subcategorySlugs.includes(selectedSub) ? selectedSub : "all"

  const artifactsQuery = useInfiniteQuery({
    queryKey: ["artifacts", slug, activeSub],
    queryFn: ({ pageParam }) =>
      getArtifacts({
        category: slug,
        sub: activeSub === "all" ? undefined : activeSub,
        page: pageParam,
        limit: 24,
      }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => (lastPage.page < lastPage.pages ? lastPage.page + 1 : undefined),
    enabled: !!slug,
  })

  useEffect(() => {
    const element = sentinelRef.current
    if (!element) return
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0]
      if (entry.isIntersecting && artifactsQuery.hasNextPage && !artifactsQuery.isFetchingNextPage) {
        void artifactsQuery.fetchNextPage()
      }
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [artifactsQuery])

  const artifacts = useMemo(
    () => artifactsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [artifactsQuery.data],
  )

  if (categoriesQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-48" />
        <Skeleton className="h-72 w-full rounded-lg" />
      </div>
    )
  }

  if (!category) {
    return (
      <div className="rounded-lg border bg-card p-6">
        <p className="text-sm text-muted-foreground">Category not found.</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/">Back</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Button asChild variant="ghost" className="-ml-2">
            <Link to="/">
              <ArrowLeft className="size-4" />
              Back
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">{category.name}</h1>
            <p className="text-sm text-muted-foreground">{category.item_count} saved items</p>
          </div>
        </div>
        <SearchBar onSelect={setSelectedArtifact} />
      </div>

      {!!category.subcategories.length && (
        <Tabs value={activeSub} onValueChange={setSelectedSub}>
          <TabsList className="flex h-auto flex-wrap justify-start">
            <TabsTrigger value="all">All</TabsTrigger>
            {category.subcategories.map((subcategory) => (
              <TabsTrigger key={subcategory.id} value={subcategory.slug}>
                {subcategory.name}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

      {artifactsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-56 rounded-lg" />
          ))}
        </div>
      ) : artifacts.length ? (
        <Masonry breakpointCols={breakpointCols} className="masonry-grid" columnClassName="masonry-grid-column">
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} onClick={() => setSelectedArtifact(artifact)} />
          ))}
        </Masonry>
      ) : (
        <div className="rounded-lg border border-dashed bg-card p-8 text-center text-sm text-muted-foreground">
          No artifacts in this view.
        </div>
      )}

      <div ref={sentinelRef} className="flex h-12 items-center justify-center">
        {artifactsQuery.isFetchingNextPage && <Loader2 className="size-5 animate-spin text-muted-foreground" />}
      </div>

      <ArtifactModal
        artifact={selectedArtifact}
        categories={categories}
        open={!!selectedArtifact}
        onOpenChange={(open) => {
          if (!open) setSelectedArtifact(null)
        }}
      />
    </div>
  )
}
