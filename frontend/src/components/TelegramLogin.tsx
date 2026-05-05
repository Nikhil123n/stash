import { useEffect, useRef, useState } from "react"

import { loginWithTelegram } from "@/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

declare global {
  interface Window {
    onTelegramAuth?: (data: Record<string, unknown>) => void
  }
}

type TelegramLoginProps = {
  onAuthenticated: (token: string) => void
}

export function TelegramLogin({ onAuthenticated }: TelegramLoginProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const botName = import.meta.env.VITE_TELEGRAM_BOT_NAME as string | undefined

  useEffect(() => {
    const container = containerRef.current
    if (!botName || !container) return

    window.onTelegramAuth = async (data: Record<string, unknown>) => {
      setError(null)
      try {
        const response = await loginWithTelegram(data)
        localStorage.setItem("stash_token", response.token)
        onAuthenticated(response.token)
      } catch {
        setError("Telegram login failed. Try again.")
      }
    }

    const script = document.createElement("script")
    script.src = "https://telegram.org/js/telegram-widget.js?22"
    script.async = true
    script.setAttribute("data-telegram-login", botName)
    script.setAttribute("data-size", "large")
    script.setAttribute("data-userpic", "false")
    script.setAttribute("data-request-access", "write")
    script.setAttribute("data-onauth", "onTelegramAuth(user)")
    container.replaceChildren(script)

    return () => {
      delete window.onTelegramAuth
      container.replaceChildren()
    }
  }, [botName, onAuthenticated])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md rounded-lg">
        <CardHeader>
          <CardTitle className="text-xl">Stash</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">Sign in with Telegram to open your personal content library.</p>
          {botName ? (
            <div ref={containerRef} className="min-h-12" />
          ) : (
            <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">
              Set VITE_TELEGRAM_BOT_NAME to enable Telegram login.
            </p>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              localStorage.removeItem("stash_token")
              setError(null)
            }}
          >
            Clear saved token
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
