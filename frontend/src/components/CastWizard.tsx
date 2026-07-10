import type { Character, Segment } from "@/api/client"

interface CastWizardProps {
  projectId: string
  initialCast: Character[]
  initialSegments: Segment[]
}

// Placeholder — fleshed out into the full single-page cast list +
// segment preview in Task 2/3 of this plan.
export function CastWizard({ projectId, initialCast, initialSegments }: CastWizardProps) {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">Review Cast</h1>
      <p className="text-sm text-muted-foreground">
        Project {projectId}: {initialCast.length} characters,{" "}
        {initialSegments.length} segments.
      </p>
    </div>
  )
}
