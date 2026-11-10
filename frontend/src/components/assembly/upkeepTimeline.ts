export const REPAIR_DURATIONS = [12, 7, 9, 13, 13, 34, 14, 18, 13]
export const REPAIR_POSES = [0.42, 1, 1, 0.7, 1, 0.94, 0.72, 0.86, 1]
export function repairCue(step: number, p: number) {
  const cues = [
    [
      'Disconnect and power off. Gently wiggle the index finger; watch the matching motors.',
      'Bend the tip: motor 2 turns.',
      'Bend the middle joint: motor 3 turns.',
      'Move the base sideways: motor 4 turns.',
    ],
    ['Move to the spool holder.', 'Undo the holder screw.', 'Slide the spool holder up and away.'],
    ['Unscrew the three top-spool screws.', 'Lift the top spools. Their bearings stay seated.'],
    [
      'Counter-rotate the top and bottom spools to release the cord.',
      'Loosen all six ends. Keep the four motor 2/3 ends anchored.',
      'Fully unwind the motor 4 pair.',
      'Free both motor 4 ends from their spool channels before opening the finger.',
    ],
    [
      'Move to the finger.',
      'Pop the finger out. Pins and bearings stay fitted.',
      'Pop the tip-and-middle unit off the AP for access.',
      'Pull the freed AP ends back through the wrist and carpals.',
    ],
    [
      'Look inside the AP anchor.',
      'Pull out the broken cord and both broken pieces.',
      'Feed the new cord through the AP anchor channel.',
      'Tie the Ashley stopper, exactly as in the assembly guide.',
      'Tie one single knot over the stopper, then seat it.',
    ],
    [
      'Feed the replacement through the finger.',
      'Continue through the carpal channel.',
      'Continue through the wrist channel.',
      'Bring the end into the tower. Restore the opposing AP cord too.',
    ],
    [
      'Pop the tip-and-middle unit back onto the AP.',
      'Pop the finger back into the hand; keep the cord routes clear.',
      'Thread the freed pair through their spool channels and seat the stoppers.',
      'Rewind the freed pair. Turn the other spools to take up their slack.',
    ],
    [
      'Refit all three top spools with their bearings seated.',
      'Start the matching screws.',
      'Use Setup to tension and check the finger.',
      'Disconnect and power off again. Tighten the screws.',
      'Slide the holder back into its slots and secure its screw.',
    ],
  ]
  const thresholds = [
    [0.15, 0.43, 0.71],
    [0.2, 0.4],
    [0.45],
    [0.3, 0.55, 0.85],
    [0.22, 0.45, 0.65],
    [0.08, 0.2, 0.36, 0.85],
    [0.2, 0.48, 0.76],
    [0.2, 0.4, 0.68],
    [0.35, 0.5, 0.7, 0.78],
  ]
  return cues[step][thresholds[step].filter((t) => p >= t).length]
}
export function repairLesson(step: number, p: number) {
  if (step !== 5 || p < 0.36 || p >= 0.94) return null
  return p < 0.85
    ? { kind: 'ashley' as const, frame: Math.min(10, Math.floor(((p - 0.36) / 0.49) * 11)) }
    : { kind: 'reinforce' as const, frame: Math.min(2, Math.floor(((p - 0.85) / 0.09) * 3)) }
}
