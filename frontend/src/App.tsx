import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { BrowserRouter, Route, Routes } from "react-router-dom"

import type { ArtifactOut } from "@/api"
import { getCategories, getStats } from "@/api"
import { ArtifactModal } from "@/components/ArtifactModal"
import { CategoryDetail } from "@/components/CategoryDetail"
import { CategoryGrid } from "@/components/CategoryGrid"
import { SearchBar } from "@/components/SearchBar"
import { TelegramLogin } from "@/components/TelegramLogin"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"

const queryClient = new QueryClient()

function Home() {
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactOut | null>(null)
  const categoriesQuery = useQuery({ queryKey: ["categories"], queryFn: getCategories })
  const statsQuery = useQuery({ queryKey: ["stats"], queryFn: getStats })

  const stats = statsQuery.data
  const categories = categoriesQuery.data ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-normal">Stash</h1>
          <p className="mt-1 text-sm text-muted-foreground">Browse saved content by category or search everything.</p>
        </div>
        <SearchBar onSelect={setSelectedArtifact} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="rounded-lg">
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">Artifacts</div>
            <div className="mt-1 text-2xl font-semibold">{stats?.total_artifacts ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="rounded-lg">
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">Needs review</div>
            <div className="mt-1 text-2xl font-semibold">{stats?.needs_review_count ?? 0}</div>
          </CardContent>
        </Card>
        <Card className="rounded-lg">
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">Top category</div>
            <div className="mt-2 flex min-h-8 items-center gap-2">
              {stats?.top_categories[0] ? (
                <>
                  <span className="truncate text-sm font-medium">{stats.top_categories[0].name}</span>
                  <Badge variant="secondary">{stats.top_categories[0].count}</Badge>
                </>
              ) : (
                <span className="text-sm text-muted-foreground">None yet</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <CategoryGrid />

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

function AppRoutes() {
  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/c/:slug" element={<CategoryDetail />} />
      </Routes>
    </main>
  )
}

function App() {
  const skipAuth = import.meta.env.VITE_SKIP_AUTH === "true"
  const [token, setToken] = useState(() => localStorage.getItem("stash_token"))
  const authed = useMemo(() => skipAuth || !!token, [skipAuth, token])

  return (
    <QueryClientProvider client={queryClient}>
      {authed ? (
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      ) : (
        <TelegramLogin onAuthenticated={setToken} />
      )}
    </QueryClientProvider>
  )
}

export default App
