import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  type RowSelectionState,
  useReactTable,
} from "@tanstack/react-table"
import { Loader2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  bulkReassignSegments,
  cancelSegmentGeneration,
  errorMessage,
  generateSegment,
  patchSegment,
  segmentAudioUrl,
  type Character,
  type Segment,
} from "@/api/client"
import { GenerateStopPlayButton } from "@/components/GenerateStopPlayButton"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { useGenerateStopPlay } from "@/hooks/useGenerateStopPlay"

interface SegmentTableProps {
  segments: Segment[]
  characters: Character[]
  onSegmentChange: (segment: Segment) => void
  generationLocked: boolean
  onRefresh: () => void
}

const columnHelper = createColumnHelper<Segment>()

/** TBL-04/GEN-06/GEN-09: a thin wrapper over the shared
 * useGenerateStopPlay hook + <GenerateStopPlayButton> — generates on first
 * click (no audio yet), auto-plays the result once it lands, and toggles
 * play/pause on subsequent clicks once audio exists. Reuses
 * CharacterCard's play/pause + isPlaying + hidden <audio> pattern; the
 * poll/settle/error state machine (including the "Stopping…" sub-state,
 * D-03/D-05) now lives in the shared hook instead of being duplicated
 * here. */
function GeneratePlayButton({
  segment,
  onRefresh,
  generationLocked,
}: {
  segment: Segment
  onRefresh: () => void
  generationLocked: boolean
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const autoplayRef = useRef(false)
  const hasAudio = Boolean(segment.audio_path)

  const { status, error, handleGenerate, handleStop } = useGenerateStopPlay({
    hasAudio,
    isExternallyGenerating: segment.generation_status === "generating",
    poll: true,
    onGenerate: () => generateSegment(segment.id),
    onStop: () => cancelSegmentGeneration(segment.id),
    onRefresh,
  })

  useEffect(() => {
    if (autoplayRef.current && hasAudio && audioRef.current) {
      autoplayRef.current = false
      void audioRef.current.play()
    }
  }, [hasAudio, segment.audio_path])

  function handleGenerateClick() {
    autoplayRef.current = true
    void handleGenerate()
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

  return (
    <div className="flex flex-col gap-1">
      <GenerateStopPlayButton
        size="sm"
        status={status}
        isPlaying={isPlaying}
        disabled={generationLocked && status === "idle"}
        disabledReason="Another generation is already running."
        subjectLabel={`audio for segment ${segment.order + 1}`}
        onGenerate={handleGenerateClick}
        onStop={() => void handleStop()}
        onTogglePlay={togglePlayback}
      />
      {hasAudio && (
        <audio
          ref={audioRef}
          src={segmentAudioUrl(segment.id)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
        />
      )}
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

function NarratorCell({
  segment,
  characters,
  onSegmentChange,
}: {
  segment: Segment
  characters: Character[]
  onSegmentChange: (segment: Segment) => void
}) {
  const [error, setError] = useState<string | null>(null)

  function handleChange(value: string) {
    if (value === segment.character_id) return
    setError(null)
    patchSegment(segment.id, { character_id: value })
      .then(onSegmentChange)
      .catch((err: unknown) => setError(errorMessage(err, "Couldn't reassign narrator.")))
  }

  return (
    <div className="flex flex-col gap-1">
      <Select value={segment.character_id} onValueChange={handleChange}>
        <SelectTrigger size="sm" aria-label={`Narrator for segment ${segment.order + 1}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {characters.map((character) => (
            <SelectItem key={character.id} value={character.id}>
              {character.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** Pattern 1/Pitfall 6: local state, commit onBlur only — never on
 * keystroke. The segmentIdRef guard (CharacterCard's convention) means a
 * background regen updating this same row's props mid-edit never clobbers
 * the user's in-progress local buffer; only a genuine row-identity change
 * resets it. */
function EditableTextCell({
  segment,
  field,
  label,
  onSegmentChange,
}: {
  segment: Segment
  field: "voice_instructions" | "text"
  label: string
  onSegmentChange: (segment: Segment) => void
}) {
  const initialValue = segment[field]
  const [value, setValue] = useState(initialValue)
  const [error, setError] = useState<string | null>(null)
  const segmentIdRef = useRef(segment.id)

  useEffect(() => {
    if (segmentIdRef.current !== segment.id) {
      segmentIdRef.current = segment.id
      setValue(initialValue)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segment.id])

  function handleBlur() {
    if (value === initialValue) return
    setError(null)
    patchSegment(segment.id, { [field]: value })
      .then(onSegmentChange)
      .catch((err: unknown) => setError(errorMessage(err, "Couldn't save edit.")))
  }

  return (
    <div className="flex flex-col gap-1">
      <Textarea
        aria-label={`${label} for segment ${segment.order + 1}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleBlur}
        className="min-h-16 bg-background text-sm"
      />
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** TBL-03: 48px bulk-action toolbar (UI-SPEC), rendered above the table
 * only while 1+ rows are selected. Non-destructive, no confirmation
 * dialog — matches D-06's "no separate Save/confirm" copywriting
 * contract already used for per-cell edits. */
function BulkReassignToolbar({
  selectedIds,
  characters,
  onReassigned,
}: {
  selectedIds: string[]
  characters: Character[]
  onReassigned: (characterId: string) => void
}) {
  const [targetId, setTargetId] = useState<string>("")
  const [isReassigning, setIsReassigning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    if (!targetId) return
    setIsReassigning(true)
    setError(null)
    try {
      await bulkReassignSegments(selectedIds, targetId)
      onReassigned(targetId)
    } catch (err) {
      setError(errorMessage(err, "Couldn't reassign segments."))
    } finally {
      setIsReassigning(false)
    }
  }

  return (
    <div className="mb-2 flex flex-col gap-1">
      <div className="flex h-12 items-center gap-3 rounded-lg bg-secondary px-3">
        <span className="text-xs font-semibold text-muted-foreground">
          {selectedIds.length} selected
        </span>
        <Select value={targetId} onValueChange={setTargetId}>
          <SelectTrigger size="sm" aria-label="Reassign narrator to">
            <SelectValue placeholder="Reassign narrator to…" />
          </SelectTrigger>
          <SelectContent>
            {characters.map((character) => (
              <SelectItem key={character.id} value={character.id}>
                {character.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="button"
          size="sm"
          disabled={!targetId || isReassigning}
          onClick={() => void handleConfirm()}
        >
          {isReassigning ? (
            <Loader2 className="animate-spin" />
          ) : (
            `Reassign ${selectedIds.length} segment${selectedIds.length === 1 ? "" : "s"}`
          )}
        </Button>
      </div>
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** TBL-01/02/03/04, GEN-02/03: the editable segment table — extends
 * SegmentPreview.tsx's read-only TanStack setup with editable Narrator/
 * Text cells (commit onBlur), a per-row generate/play control, and
 * checkbox row selection + bulk-reassign toolbar. */
export function SegmentTable({
  segments,
  characters,
  onSegmentChange,
  generationLocked,
  onRefresh,
}: SegmentTableProps) {
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const data = useMemo(
    () => [...segments].sort((a, b) => a.order - b.order),
    [segments]
  )

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllRowsSelected()}
            onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}
            aria-label="Select all segments"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label={`Select segment ${row.original.order + 1}`}
          />
        ),
      }),
      columnHelper.display({
        id: "narrator",
        header: "Narrator",
        cell: ({ row }) => (
          <NarratorCell
            segment={row.original}
            characters={characters}
            onSegmentChange={onSegmentChange}
          />
        ),
      }),
      columnHelper.display({
        id: "voice_instructions",
        header: "Voice Instructions",
        cell: ({ row }) => (
          <EditableTextCell
            segment={row.original}
            field="voice_instructions"
            label="Voice Instructions"
            onSegmentChange={onSegmentChange}
          />
        ),
      }),
      columnHelper.display({
        id: "text",
        header: "Text",
        cell: ({ row }) => (
          <EditableTextCell
            segment={row.original}
            field="text"
            label="Text"
            onSegmentChange={onSegmentChange}
          />
        ),
      }),
      columnHelper.display({
        id: "controls",
        header: "",
        cell: ({ row }) => (
          <GeneratePlayButton
            segment={row.original}
            onRefresh={onRefresh}
            generationLocked={generationLocked}
          />
        ),
      }),
    ],
    [characters, onSegmentChange, generationLocked, onRefresh]
  )

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (segment) => segment.id,
    state: { rowSelection },
    onRowSelectionChange: setRowSelection,
  })

  const selectedIds = Object.keys(rowSelection)

  function handleReassigned(targetCharacterId: string) {
    const targetName =
      characters.find((character) => character.id === targetCharacterId)?.name ?? null
    for (const segment of segments) {
      if (selectedIds.includes(segment.id)) {
        onSegmentChange({
          ...segment,
          character_id: targetCharacterId,
          character_name: targetName,
        })
      }
    }
    setRowSelection({})
  }

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">Segments</h2>
      {selectedIds.length > 0 && (
        <BulkReassignToolbar
          selectedIds={selectedIds}
          characters={characters}
          onReassigned={handleReassigned}
        />
      )}
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row, index) => (
            <TableRow
              key={row.id}
              className={index % 2 === 1 ? "bg-secondary" : undefined}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id} className="align-top py-3 whitespace-normal">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
