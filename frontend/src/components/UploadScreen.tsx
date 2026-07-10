import { useRef, useState } from "react"

import { createProject } from "@/api/client"
import { Button } from "@/components/ui/button"

interface UploadScreenProps {
  onUploaded: (projectId: string) => void
}

/** WIZ-01/ING-02 landing screen: empty-state copy + "Upload & Analyze" CTA
 * (Copywriting Contract, UI-SPEC). */
export function UploadScreen({ onUploaded }: UploadScreenProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return

    setSubmitting(true)
    setError(null)
    try {
      const { id } = await createProject(file)
      onUploaded(id)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Couldn't analyze this file."
      )
    } finally {
      setSubmitting(false)
      event.target.value = ""
    }
  }

  return (
    <div className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-2xl font-semibold">No book uploaded yet</h1>
      <p className="text-sm text-muted-foreground">
        Upload a .txt or .epub file to auto-detect its cast of characters and
        split it into narrated segments.
      </p>
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.epub"
        className="hidden"
        onChange={handleFileChange}
        aria-label="Choose a .txt or .epub file to upload"
      />
      <Button
        onClick={() => fileInputRef.current?.click()}
        disabled={submitting}
      >
        {submitting ? "Uploading…" : "Upload & Analyze"}
      </Button>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          Couldn&apos;t analyze this file. {error} Fix the file and upload
          again.
        </p>
      )}
    </div>
  )
}
