export const UPKEEP_STEPS = [
  {
    id: 'identify',
    title: 'Identify the affected motor',
    instruction:
      'Disconnect and power off. Gently wiggle the finger to identify its motors. Trace the broken tendon to its motor; record each cord’s spool and winding direction.',
    example: 'Wiggle the index tip, middle and base. Motors 2, 3 and 4 move with them.',
    detail:
      'Stop the operation, Disconnect and switch board power off first. A broken cord may not transmit movement: trace its opposing cord and confirm the motor with the matching assembly guide. Keep the recorded top/bottom assignments.',
    check: 'Power is off; the finger’s motors and cord routes are identified.',
  },
  {
    id: 'holder',
    title: 'Remove the spool holder',
    instruction: 'Undo the holder’s screw. Slide the holder out of its slots and put it aside.',
    example: 'Remove the holder covering the index motor column.',
    detail: 'Keep the holder and its matching screw together, clear of the motor column.',
    check: 'The spool holder is removed and kept with its screw.',
  },
  {
    id: 'tops',
    title: 'Lift the top spools',
    instruction:
      'Remove the top-spool screws for this finger. Lift off the top spools with their bearings still seated.',
    example: 'Remove the screws and top spools on motors 2, 3 and 4.',
    detail:
      'Keep each top spool with its original cord. Leave the bottom spools on the motors. Do not pull bearings out of the top spools.',
    check: 'The top spools are off; the bearings remain seated.',
  },
  {
    id: 'slacken',
    title: 'Unwind the tendons',
    instruction:
      'Counter-rotate the spools to slacken all six ends. Fully unwind the motor 4 pair and free both ends from their spool channels before opening the finger. Keep the other four ends anchored.',
    example: 'Loosen all six index ends. Free the motor 4 pair; keep motor 2 and 3 ends anchored.',
    detail:
      'Follow your recorded winding direction in reverse. Motors 2 and 3 keep their four cord ends anchored. Only the motor 4 pair comes fully off its spools.',
    check: 'The finger is slack; only the affected pair is free.',
  },
  {
    id: 'open',
    title: 'Pop the finger out',
    instruction:
      'Pop out the index finger, then lift its tip-and-middle unit off the AP. Keep all pins and bearings fitted. Pull the two freed AP ends back through the wrist and carpals.',
    example: 'Pop out the index. Move its tip-and-middle unit off the AP; pull back the AP pair.',
    detail:
      'Keep the pins and bearings in their parts. Leave intact cords attached to their spools and move them only as far as access requires. Do not drag an anchored knot through a channel.',
    check: 'The damaged cord is accessible; pins and bearings stay fitted.',
  },
  {
    id: 'replace',
    title: 'Replace and tie the cord',
    instruction:
      'Pull out the damaged cord and broken pieces. Insert the new cord. Tie and seat the same anchor knot used in the assembly guide.',
    example:
      'Thread the AP channel, tie an Ashley stopper, add one single knot over it and seat it.',
    detail:
      'Check the liner before inserting new cord. Tie an Ashley stopper, then one single knot directly over it. Seat the knot in the AP anchor. Reuse the opposing AP cord if undamaged.',
    check: 'The broken cord is removed and the replacement is anchored.',
  },
  {
    id: 'route',
    title: 'Thread back to the tower',
    instruction:
      'Follow the original route through the finger, carpals and wrist, then into the motor tower. Restore any displaced cords in order.',
    example:
      'Follow the highlighted new AP cord all the way to motor 4. Restore the opposing AP cord too.',
    detail:
      'Use the original channels, with no crossed cords. Leave enough slack to refit the finger. Keep the original spool assignments and winding directions.',
    check: 'The replacement and displaced cords reach their original spools.',
  },
  {
    id: 'rewind',
    title: 'Pop in and re-spool',
    instruction:
      'Pop the finger back in. Rethread and anchor the freed spool ends. Rewind those spools, then turn the others to take up their slack.',
    example:
      'Refit the index. Rethread the motor 4 spools; rewind motors 2 and 3 without removing their anchors.',
    detail:
      'Use the matching assembly guide’s spool channels and Ashley stoppers. Wind three snug turns where cord length allows. Keep the recorded top/bottom assignments, with no cord crossed or caught behind a spool. Check each tendon with the others loose.',
    check: 'The finger is back in and every cord is on its correct spool.',
  },
  {
    id: 'finish',
    title: 'Refit, tension and close',
    instruction:
      'Refit the top spools and screws. Tension and check the finger, tighten the fixings, then refit and secure the spool holder.',
    example: 'Refit all three top spools, tension the index, tighten and replace the holder.',
    detail:
      'Clear tools before powering on. Use Setup to repeat slack-test, tensioning and calibration for every joint loosened. Disconnect and switch board power off before the final mechanical tightening and holder refit. Test both directions; stop if a cord catches or moves the wrong joint.',
    check: 'The finger is checked, fixings are tight and the holder is secured.',
  },
] as const
export const UPKEEP_BUILD = {
  version: 'base',
  side: 'right',
  motor: 'dynamixel',
  audience: 'external',
} as const
