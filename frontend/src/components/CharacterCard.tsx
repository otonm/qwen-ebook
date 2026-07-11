import { Merge as MergeIcon, Pause, Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  mergeCharacter,
  patchCharacter,
  previewUrl,
  type Character,
  type MergeUndoSnapshot,
  type VoicePreset,
} from "@/api/client"
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
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

// Radix Select forbids an empty-string item value — the backend's "auto"
// preset uses "" server-side, so map it to this sentinel client-side only.
const AUTO_PRESET_VALUE = "__auto__"

interface CharacterCardProps {
  character: Character
  otherCharacters: Character[]
  voices: VoicePreset[]
  onCastRefresh: () => void
  onMerged: (undo: MergeUndoSnapshot) => void
}

export function CharacterCard({
  character,
  otherCharacters,
  voices,
  onCastRefresh,
  onMerged,
}: CharacterCardProps) {
  const [name, setName] = useState(character.name)
  const [voiceInstructions, setVoiceInstructions] = useState(
    character.voice_instructions
  )
  const [isPlaying, setIsPlaying] = useState(false)
  const [mergeTargetId, setMergeTargetId] = useState<string | null>(null)
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)

  // Keep local edit buffers aligned when the underlying character record
  // changes for a reason other than this card's own edits (merge, initial
  // load) — never overwrite mid-typing state for the same character id.
  const characterIdRef = useRef(character.id)
  useEffect(() => {
    if (characterIdRef.current !== character.id) {
      characterIdRef.current = character.id
      setName(character.name)
      setVoiceInstructions(character.voice_instructions)
    }
  }, [character.id, character.name, character.voice_instructions])

  async function saveField(patch: Parameters<typeof patchCharacter>[1]) {
    await patchCharacter(character.id, patch)
    onCastRefresh()
  }

  function handleNameBlur() {
    if (name !== character.name) void saveField({ name })
  }

  function handleVoiceInstructionsBlur() {
    if (voiceInstructions !== character.voice_instructions) {
      void saveField({ voice_instructions: voiceInstructions })
    }
  }

  function handlePresetChange(value: string) {
    const preset = value === AUTO_PRESET_VALUE ? "" : value
    void saveField({ voice_preset: preset })
  }

  function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      void audio.play()
    }
  }

  async function confirmMerge() {
    if (!mergeTargetId) return
    const { undo } = await mergeCharacter(character.id, mergeTargetId)
    setMergeDialogOpen(false)
    setMergeTargetId(null)
    onMerged(undo)
  }

  function closeMergeDialog(open: boolean) {
    setMergeDialogOpen(open)
    if (!open) setMergeTargetId(null)
  }

  const mergeTarget = otherCharacters.find((c) => c.id === mergeTargetId)
  const hasPreview = Boolean(character.preview_audio_path)

  return (
    <div className="flex flex-col gap-4 rounded-lg bg-secondary p-4">
      <div className="flex items-start justify-between gap-2">
        <Input
          aria-label={`Name for ${character.name}`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={handleNameBlur}
          className="border-none bg-transparent p-0 text-lg font-semibold shadow-none focus-visible:ring-0"
        />
        {character.is_narrator && (
          <Badge variant="secondary" className="shrink-0 text-xs font-semibold">
            NARRATOR
          </Badge>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs font-semibold text-muted-foreground">Preset</label>
        <Select
          value={character.voice_preset || AUTO_PRESET_VALUE}
          onValueChange={handlePresetChange}
        >
          <SelectTrigger aria-label={`Voice preset for ${character.name}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {voices.map((voice) => (
              <SelectItem
                key={voice.name || AUTO_PRESET_VALUE}
                value={voice.name || AUTO_PRESET_VALUE}
              >
                {voice.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs font-semibold text-muted-foreground">
          Voice Instructions
        </label>
        <Textarea
          aria-label={`Voice instructions for ${character.name}`}
          value={voiceInstructions}
          onChange={(e) => setVoiceInstructions(e.target.value)}
          onBlur={handleVoiceInstructionsBlur}
          className="min-h-32 bg-background text-sm"
        />
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="icon"
          variant={isPlaying ? "default" : "outline"}
          disabled={!hasPreview}
          onClick={togglePlayback}
          aria-label={
            isPlaying
              ? `Pause preview for ${character.name}`
              : `Play preview for ${character.name}`
          }
        >
          {isPlaying ? <Pause /> : <Play />}
        </Button>
        {hasPreview && (
          <Badge className="bg-primary text-primary-foreground">Voice assigned</Badge>
        )}
        {hasPreview && (
          <audio
            ref={audioRef}
            src={previewUrl(character.id)}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
          />
        )}

        {otherCharacters.length > 0 && (
          <Button
            type="button"
            size="icon"
            variant="outline"
            className="ml-auto"
            onClick={() => setMergeDialogOpen(true)}
            aria-label={`Merge ${character.name} into another character`}
          >
            <MergeIcon />
          </Button>
        )}
      </div>

      <Dialog open={mergeDialogOpen} onOpenChange={closeMergeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {mergeTarget ? `Merge into ${mergeTarget.name}?` : "Merge character"}
            </DialogTitle>
            <DialogDescription>
              {mergeTarget
                ? `This removes '${character.name}' from the cast and reassigns its segments to ${mergeTarget.name}. You can undo this right after.`
                : "Choose which character to merge this one into."}
            </DialogDescription>
          </DialogHeader>
          <Select
            value={mergeTargetId ?? undefined}
            onValueChange={setMergeTargetId}
          >
            <SelectTrigger aria-label={`Merge target for ${character.name}`}>
              <SelectValue placeholder="Choose a character…" />
            </SelectTrigger>
            <SelectContent>
              {otherCharacters.map((other) => (
                <SelectItem key={other.id} value={other.id}>
                  {other.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <DialogFooter>
            <Button variant="outline" onClick={() => closeMergeDialog(false)}>
              Cancel
            </Button>
            <Button disabled={!mergeTargetId} onClick={() => void confirmMerge()}>
              Merge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
