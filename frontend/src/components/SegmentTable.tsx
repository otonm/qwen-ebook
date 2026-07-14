import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  type RowSelectionState,
  useReactTable,
} from "@tanstack/react-table"
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  Pause,
  Play,
} from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import {
  bulkReassignSegments,
  cancelSegmentGeneration,
  errorMessage,
  GENERATION_POLL_CEILING_MS,
  generateSegment,
  patchSegment,
  segmentAudioUrl,
  type Character,
  type GenerationStatus,
  type Segment,
} from "@/api/client"
import { Badge } from "@/components/ui/badge"
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

interface SegmentTableProps {
  segments: Segment[]
  characters: Character[]
  onSegmentChange: (segment: Segment) => void
  generationLocked: boolean
  onRefresh: () => void
}

const columnHelper = createColumnHelper<Segment>()

// UI-SPEC Generation Status Indicators table — prescriptive badge/icon
// mapping so no per-status color/icon is invented ad hoc. "queued" shares
// "pending"'s look (batch-only sub-state, no visual distinction needed).
const STATUS_BADGE: Record<
  GenerationStatus,
  {
    label: string
    icon: typeof Clock
    variant: "outline" | "default" | "secondary" | "destructive"
  }
> = {
  pending: { label: "Pending", icon: Clock, variant: "outline" },
  queued: { label: "Pending", icon: Clock, variant: "outline" },
  generating: { label: "Generating…", icon: Loader2, variant: "default" },
  complete: { label: "Complete", icon: CheckCircle2, variant: "secondary" },
  error: { label: "Error", icon: AlertCircle, variant: "destructive" },
}

function StatusBadge({ status }: { status: GenerationStatus }) {
  const { label, icon: Icon, variant } = STATUS_BADGE[status]
  return (
    <Badge variant={variant} className="gap-1 whitespace-nowrap">
      <Icon className={status === "generating" ? "size-3 animate-spin" : "size-3"} />
      {label}
    </Badge>
  )
}

/** TBL-04/GEN-06: one icon button does double duty — generates on first
 * click (no audio yet), auto-plays the result once it lands, and toggles
 * play/pause on subsequent clicks once audio exists. Reuses
 * CharacterCard's play/pause + isPlaying + hidden <audio> pattern.
 *
 * Since 04-03, generateSegment fires-and-returns (202) instead of awaiting
 * a result — this polls `onRefresh` (mirroring ConfigPanel's
 * CharacterPreviewRow) until the row settles out of "generating". A
 * bare-bones Stop button (D-04) appears whenever the row is generating and
 * shows a distinct "Stopping…" state (D-03/D-05) held until a refetch
 * confirms the backend has actually released the row. */
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
  const [isGenerating, setIsGenerating] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const autoplayRef = useRef(false)
  // Tracks whether we've actually seen this row hit "generating" (from
  // either our own trigger or an external one, e.g. a batch run) since the
  // last settle — the signal a poll/refetch uses to know the row has since
  // left "generating" for real, rather than reading a stale pre-click
  // status as "already settled".
  const hasObservedGeneratingRef = useRef(false)
  const hasAudio = Boolean(segment.audio_path)
  // T-03-29: a row already 'generating' via a batch (or another trigger)
  // must disable/spin this button too, not just its own local click flag —
  // otherwise a second click fires a duplicate POST /segments/{id}/generate.
  const isRowGenerating = isGenerating || segment.generation_status === "generating"
  // Only one generation may be in flight app-wide (backend-enforced global
  // lock) — disable the GENERATE half of this button while something else
  // holds it. Playback of already-generated audio doesn't touch the GPU,
  // so it stays enabled regardless (hasAudio already routes handleClick to
  // the play branch in that case).
  const isDisabled = isRowGenerating || isStopping || (!hasAudio && generationLocked)

  useEffect(() => {
    if (autoplayRef.current && hasAudio && audioRef.current) {
      autoplayRef.current = false
      void audioRef.current.play()
    }
  }, [hasAudio, segment.audio_path])

  // Poll for the 202+background-task result while we're the one waiting on
  // a generation we triggered — mirrors CharacterPreviewRow's 1500ms
  // interval + poll ceiling (WR-04 fix: GENERATION_POLL_CEILING_MS, well
  // above the backend's own 300s synth timeout) so a legitimately slow
  // call isn't abandoned mid-poll — only a genuinely failed/hung one is.
  useEffect(() => {
    if (!isGenerating) return undefined
    const interval = setInterval(onRefresh, 1500)
    const timeout = setTimeout(() => clearInterval(interval), GENERATION_POLL_CEILING_MS)
    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [isGenerating, onRefresh])

  // The row settles (leaves "generating") once a refetch/SSE update lands —
  // clear both the generating and stopping flags only once we've genuinely
  // observed the transition, never on the first stale render.
  useEffect(() => {
    if (segment.generation_status === "generating") {
      hasObservedGeneratingRef.current = true
      return
    }
    if (hasObservedGeneratingRef.current) {
      hasObservedGeneratingRef.current = false
      setIsGenerating(false)
      setIsStopping(false)
    }
  }, [segment.generation_status])

  async function handleClick() {
    if (hasAudio) {
      const audio = audioRef.current
      if (!audio) return
      if (isPlaying) {
        audio.pause()
      } else {
        void audio.play()
      }
      return
    }
    setIsGenerating(true)
    setError(null)
    autoplayRef.current = true
    try {
      await generateSegment(segment.id)
      onRefresh()
    } catch (err) {
      setIsGenerating(false)
      setError(errorMessage(err, "Couldn't start generation."))
    }
  }

  async function handleStop() {
    setIsStopping(true)
    setError(null)
    try {
      // cancelSegmentGeneration's await only resolves once the backend has
      // genuinely finished the underlying call and released the lock
      // (04-03) — that's the confirmed-stopped signal itself, not an
      // optimistic guess, so clearing local state here is honest per
      // D-03/D-05.
      await cancelSegmentGeneration(segment.id)
    } catch (err) {
      setError(errorMessage(err, "Couldn't stop generation."))
    } finally {
      setIsGenerating(false)
      setIsStopping(false)
      onRefresh()
    }
  }

  const label = hasAudio
    ? isPlaying
      ? `Pause segment ${segment.order + 1}`
      : `Play segment ${segment.order + 1}`
    : `Generate audio for segment ${segment.order + 1}`

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1">
        <Button
          type="button"
          size="icon-sm"
          variant={isPlaying ? "default" : "outline"}
          disabled={isDisabled}
          onClick={() => void handleClick()}
          aria-label={label}
        >
          {isRowGenerating ? (
            <Loader2 className="animate-spin" />
          ) : hasAudio ? (
            isPlaying ? (
              <Pause />
            ) : (
              <Play />
            )
          ) : (
            <Play />
          )}
        </Button>
        {isRowGenerating && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isStopping}
            onClick={() => void handleStop()}
            aria-label={`Stop generating segment ${segment.order + 1}`}
          >
            {isStopping ? "Stopping…" : "Stop"}
          </Button>
        )}
        {hasAudio && (
          <audio
            ref={audioRef}
            src={segmentAudioUrl(segment.id)}
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onEnded={() => setIsPlaying(false)}
          />
        )}
      </div>
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
        id: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.generation_status} />,
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
