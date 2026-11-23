// How many E-STOPs this page has sent, so a start queued before one never goes ahead after it.
let fired = 0

export function noteEstop(): void {
  fired += 1
}

export function estopsFired(): number {
  return fired
}
