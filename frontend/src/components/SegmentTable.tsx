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

/** TBL-04: one icon button does double duty — generates on first click
 * (no audio yet), auto-plays the result once it lands, and toggles
 * play/pause on subsequent clicks once audio exists. Reuses
 * CharacterCard's play/pause + isPlaying + hidden <audio> pattern. */
function GeneratePlayButton({
  segment,
  onSegmentChange,
  generationLocked,
}: {
  segment: Segment
  onSegmentChange: (segment: Segment) => void
  generationLocked: boolean
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const autoplayRef = useRef(false)
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
  const isDisabled = isRowGenerating || (!hasAudio && generationLocked)

  useEffect(() => {
    if (autoplayRef.current && hasAudio && audioRef.current) {
      autoplayRef.current = false
      void audioRef.current.play()
    }
  }, [hasAudio, segment.audio_path])

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
    autoplayRef.current = true
    try {
      const updated = await generateSegment(segment.id)
      onSegmentChange(updated)
    } finally {
      setIsGenerating(false)
    }
  }

  const label = hasAudio
    ? isPlaying
      ? `Pause segment ${segment.order + 1}`
      : `Play segment ${segment.order + 1}`
    : `Generate audio for segment ${segment.order + 1}`

  return (
    <>
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
      {hasAudio && (
        <audio
          ref={audioRef}
          src={segmentAudioUrl(segment.id)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
        />
      )}
    </>
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
  function handleChange(value: string) {
    if (value === segment.character_id) return
    void patchSegment(segment.id, { character_id: value }).then(onSegmentChange)
  }

  return (
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
    void patchSegment(segment.id, { [field]: value }).then(onSegmentChange)
  }

  return (
    <Textarea
      aria-label={`${label} for segment ${segment.order + 1}`}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={handleBlur}
      className="min-h-16 bg-background text-sm"
    />
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

  async function handleConfirm() {
    if (!targetId) return
    setIsReassigning(true)
    try {
      await bulkReassignSegments(selectedIds, targetId)
      onReassigned(targetId)
    } finally {
      setIsReassigning(false)
    }
  }

  return (
    <div className="mb-2 flex h-12 items-center gap-3 rounded-lg bg-secondary px-3">
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
          <div className="flex items-center gap-1">
            <GeneratePlayButton
              segment={row.original}
              onSegmentChange={onSegmentChange}
              generationLocked={generationLocked}
            />
          </div>
        ),
      }),
    ],
    [characters, onSegmentChange, generationLocked]
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
