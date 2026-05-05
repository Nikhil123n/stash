import axios from "axios"

export type SubcategoryOut = {
  id: string
  name: string
  slug: string
  item_count: number
  tier: number
  confirmed: boolean
}

export type CategoryOut = {
  id: string
  name: string
  slug: string
  icon: string | null
  item_count: number
  created_at: string
  subcategories: SubcategoryOut[]
  recent_thumbnails: string[]
}

export type ArtifactOut = {
  id: string
  created_at: string
  source_type: string
  raw_url: string | null
  r2_url: string | null
  ai_title: string
  ai_summary: string
  ai_tags: string[]
  ai_confidence: number
  needs_review: boolean
  category: CategoryOut
  subcategory: SubcategoryOut | null
  user_overridden: boolean
  view_count: number
  last_viewed_at: string | null
}

export type ArtifactDetail = ArtifactOut & {
  ai_transcript: string | null
}

export type PaginatedArtifacts = {
  items: ArtifactOut[]
  total: number
  page: number
  pages: number
}

export type StatsOut = {
  total_artifacts: number
  top_categories: Array<{ name: string; count: number }>
  recent: ArtifactOut[]
  needs_review_count: number
}

export type ArtifactListParams = {
  category?: string
  sub?: string
  page?: number
  limit?: number
}

const baseURL = import.meta.env.VITE_API_URL || "/"

export const api = axios.create({ baseURL })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("stash_token")
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export async function getCategories(): Promise<CategoryOut[]> {
  const response = await api.get<CategoryOut[]>("/api/categories")
  return response.data
}

export async function getArtifacts(params: ArtifactListParams): Promise<PaginatedArtifacts> {
  const response = await api.get<PaginatedArtifacts>("/api/artifacts", { params })
  return response.data
}

export async function searchArtifacts(q: string): Promise<ArtifactOut[]> {
  const response = await api.get<ArtifactOut[]>("/api/artifacts/search", { params: { q } })
  return response.data
}

export async function getArtifact(id: string): Promise<ArtifactDetail> {
  const response = await api.get<ArtifactDetail>(`/api/artifacts/${id}`)
  return response.data
}

export async function recategorize(id: string, categoryId: string): Promise<ArtifactOut> {
  const response = await api.patch<ArtifactOut>(`/api/artifacts/${id}`, {
    category_id: categoryId,
  })
  return response.data
}

export async function deleteArtifact(id: string): Promise<void> {
  await api.delete(`/api/artifacts/${id}`)
}

export async function getStats(): Promise<StatsOut> {
  const response = await api.get<StatsOut>("/api/stats")
  return response.data
}

export async function loginWithTelegram(data: Record<string, unknown>): Promise<{ token: string }> {
  const response = await api.post<{ token: string }>("/api/auth/telegram", data)
  return response.data
}
