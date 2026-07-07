// Fixed-capacity ring for sparkline history. Filled from the WS handler (so
// no samples are lost to display-rate coalescing), snapshotted by uPlot.

export class RingBuffer {
  readonly capacity: number
  private data: Float32Array
  private head = 0
  private count = 0

  constructor(capacity = 1024) {
    this.capacity = capacity
    this.data = new Float32Array(capacity)
  }

  push(value: number): void {
    this.data[this.head] = value
    this.head = (this.head + 1) % this.capacity
    if (this.count < this.capacity) this.count += 1
  }

  get length(): number {
    return this.count
  }

  /** Oldest-to-newest copy of the last `n` samples (default: all). */
  snapshot(n?: number): Float32Array {
    const take = Math.min(n ?? this.count, this.count)
    const out = new Float32Array(take)
    for (let i = 0; i < take; i++) {
      out[i] = this.data[(this.head - take + i + this.capacity * 2) % this.capacity]
    }
    return out
  }
}
