import { Copy, Send } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function MagicLinkLogin() {
  const [copied, setCopied] = useState(false)
  const botName = import.meta.env.VITE_TELEGRAM_BOT_NAME as string | undefined
  const botUrl = botName ? `https://t.me/${botName}` : undefined

  async function copyDashboardCommand() {
    await navigator.clipboard.writeText("/dashboard")
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md rounded-lg">
        <CardHeader>
          <CardTitle className="text-xl">Stash</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Send /dashboard to your Telegram bot, then open the private dashboard link it replies with.
          </p>
          <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted px-3 py-2">
            <code className="text-sm font-medium">/dashboard</code>
            <Button type="button" variant="outline" size="sm" onClick={copyDashboardCommand}>
              <Copy className="size-3.5" />
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          {botUrl ? (
            <Button asChild>
              <a href={botUrl} rel="noreferrer" target="_blank">
                <Send className="size-4" />
                Open Telegram bot
              </a>
            </Button>
          ) : (
            <p className="rounded-lg border bg-muted p-3 text-sm text-muted-foreground">
              Send /dashboard to your Stash Telegram bot.
            </p>
          )}
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              localStorage.removeItem("stash_token")
            }}
          >
            Clear saved token
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
