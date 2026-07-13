import { useEffect, useState } from "react"

import { getGenerationLockStatus } from "@/api/client"

const POLL_INTERVAL_MS = 1500

/** Polls the backend's global single-flight generation lock
 * (GET /generation-status) while mounted. True while ANY generation — a
 * character preview, a per-row segment, or a batch run, in any project —
 * is in flight, so a screen can disable every OTHER generation-triggering
 * control while one is active (only one generation at a time, app-wide). */
export function useGenerationLock(): boolean {
  const [isActive, setIsActive] = useState(false)

  useEffect(() => {
    let cancelled = false
    function poll() {
      getGenerationLockStatus()
        .then(({ active }) => {
          if (!cancelled) setIsActive(active)
        })
        .catch(() => {
          // Transient fetch failure — keep the last known value rather
          // than flipping (possibly wrongly) to idle.
        })
    }
    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  return isActive
}
