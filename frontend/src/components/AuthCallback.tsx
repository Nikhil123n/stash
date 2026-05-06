import { Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"

import { exchangeMagicLink } from "@/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

type AuthCallbackProps = {
  onAuthenticated: (token: string) => void
}

export function AuthCallback({ onAuthenticated }: AuthCallbackProps) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const magicToken = searchParams.get("token")
    if (!magicToken) {
      setError("This dashboard link is missing its token.")
      return
    }
    const token = magicToken

    let cancelled = false

    async function authenticate() {
      try {
        const response = await exchangeMagicLink(token)
        if (cancelled) return
        localStorage.setItem("stash_token", response.token)
        onAuthenticated(response.token)
        navigate("/", { replace: true })
      } catch {
        if (!cancelled) setError("This dashboard link is invalid or expired.")
      }
    }

    void authenticate()

    return () => {
      cancelled = true
    }
  }, [navigate, onAuthenticated, searchParams])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md rounded-lg">
        <CardHeader>
          <CardTitle className="text-xl">Stash</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error ? (
            <>
              <p className="text-sm text-destructive">{error}</p>
              <Button type="button" variant="outline" onClick={() => navigate("/", { replace: true })}>
                Request a new link
              </Button>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Opening dashboard...
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
