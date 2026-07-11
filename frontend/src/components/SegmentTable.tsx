import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
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
  generateSegment,
  patchSegment,
  segmentAudioUrl,
  type Character,
  type GenerationStatus,
  type Segment,
} from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
}: {
  segment: Segment
  onSegmentChange: (segment: Segment) => void
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const autoplayRef = useRef(false)
  const hasAudio = Boolean(segment.audio_path)

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
        disabled={isGenerating}
        onClick={() => void handleClick()}
        aria-label={label}
      >
        {isGenerating ? (
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

/** TBL-01/02/04, GEN-02/03: the editable segment table — extends
 * SegmentPreview.tsx's read-only TanStack setup with editable Narrator/
 * Voice Instructions/Text cells (commit onBlur) and a per-row generate/
 * play control. Bulk row selection (TBL-03) is a later plan's scope. */
export function SegmentTable({ segments, characters, onSegmentChange }: SegmentTableProps) {
  const data = useMemo(
    () => [...segments].sort((a, b) => a.order - b.order),
    [segments]
  )

  const columns = useMemo(
    () => [
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
        id: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.generation_status} />,
      }),
      columnHelper.display({
        id: "controls",
        header: "",
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            <GeneratePlayButton segment={row.original} onSegmentChange={onSegmentChange} />
          </div>
        ),
      }),
    ],
    [characters, onSegmentChange]
  )

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (segment) => segment.id,
  })

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">Segments</h2>
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
