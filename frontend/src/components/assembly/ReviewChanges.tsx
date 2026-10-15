import type {AssemblyStep} from './guide'
import type {Build} from './buildContent'

// Set to false to remove the review boxes and their toolbar control together.
export const SHOW_ASSEMBLY_REVIEW_NOTES = true
type Changes = {structure?:string; content?:string; images?:string; unresolved?:string}
const CHANGES:Record<string,Changes>={
 p1:{structure:'The chapter sidebar can collapse to give the model more room. Configuration controls, BOM and explicit completion checks are retained.',content:'Touch builds now include sensor preparation, installation and connector-board work before the palm is closed.',images:'The recent tendon framing and joint-context improvements are included on this branch.'},
 p6:{structure:'The Ashley stopper lesson and its controls are retained alongside the guided instructions.'},
 p23:{structure:'The existing interactive hand-label reference is retained.'},
 p15:{content:'AP liners are cut to the measured channel depth plus approximately 1 mm at each end. The feedback’s 5–8 mm suggestion is a starting estimate, not a universal dimension.'},
 p18:{content:'Removed the instruction to choose an unspecified screw by trial. Only loose debris is cleared until the correct cleanup tool is confirmed.',unresolved:'The source does not specify the cleanup screw diameter or thread. A hardware owner must confirm it before a screw-based method can be documented.'},
 p29:{content:'Joint bearing dimensions are listed in Parts before assembly.'},
 p33:{content:'The pin dimensions are explicit in Parts; joint seating and friction checks stay with the assembly action.'},
 p35:{images:'The pin-clearance image now includes the complete DP/PP bodies and tendon ends. Live views fit the available width.'},
 'finishing-pp':{content:'The Parts box distinguishes Base skins from Touch fingertip modules and gives the selected PP bearing dimensions.'},
 p37:{images:'The tucked-tail image includes the complete free tendon beyond the AP housing.'},
 p42:{content:'Bearing sizes and pins appear in Parts; named tendon routes are retained.'},
 p46:{unresolved:'The feedback specifies a 5 mm thumb PP pin but does not identify its diameter or exact hole. The finger pin recipe must not be copied blindly to the thumb.'},
 p52:{images:'The thumb AP tucked-tail view includes the full tendon geometry.'},
 p54:{content:'Thumb AP bearings are corrected to 4×8×3 mm, including Touch.',unresolved:'The feedback says the thumb AP route is reversed but does not identify the swapped holes or viewing direction. The existing routing cannot be signed off until this is resolved.'},
 p62:{content:'Thumb TP bearings are corrected to 4×8×3 mm, including Touch. The premature “all fingers assembled” instruction is removed.',images:'The guide-pin and bearing images include translucent DP/PP context and complete tendon paths.'},
 p68:{images:'Eight named tendon controls highlight the selected route and mark its TP exit and carpal entrance in the existing CAD model.',structure:'For Touch, sensor installation and bench flashing follow here while the carpals are accessible.',unresolved:'Thumb AP channel reversal also needs confirmation before the complete thumb route can be treated as verified.'},
 p73:{content:'Forward-looking motor-pulley commentary is removed; this step describes the hand-side pulley.'},
 p89:{content:'Removed the reference to parts fitted in a later chapter.'},
 p93:{content:'The Parts box states the current CAD fan screw size and the earlier written size together, before assembly.',unresolved:'Current Base/Touch Dynamixel CAD uses M3×12; the earlier written guide says M3×14. Confirm the supplied kit and clearance.'},
 p101:{structure:'For Touch, board identification moves ahead of palm closure so flashing can happen on the bench.',images:'Adds the actual OH-board CAD identification render alongside the labeled connector diagram; the diagram retains the port labels.'},
 p105:{structure:'Flashing-method selection is first. The ORCA Console link is alongside its opening instruction.'},
 p110:{structure:'Flashing-method selection is first; Touch board mounting follows successful flashing.',content:'The Touch probe must contact the back-side six-pad footprint. ORCA Console connector flashing is described explicitly.',images:'The misleading Touch probe-placement image is omitted; the board identification image is retained.'},
 p150:{structure:'Flashing-method selection is first. Setup and flash commands sit directly after the instruction that uses each one.'},
 p154:{structure:'The side-specific flash command sits directly below the matching instruction.',content:'The Touch back-side programming pads are explicitly identified.',images:'The older ambiguous probe-placement photograph is omitted for Touch.'},
 p112:{structure:'The motor-configuration command is next to the instruction that starts it; hardware operations remain in their existing tools.'},
 p126:{images:'The animation seats the bearing in the loose spool before moving them together onto the motor. The outdated static sequence is omitted.',content:'Seat the bearing while supporting the loose top spool on the bench, before installing it on the tower. The current CAD screw size is stated in Parts.',unresolved:'The earlier written guide says M2×8; the current CAD uses M2.5×8. Check the actual supplied screw and spool thread.'},
 p139:{structure:'The Final assembly checklist precedes the completed-hand render. Completion still requires all checks.'},
 p141:{content:'The guide hands off to the live Setup workflow instead of duplicating tensioning instructions that become separated from the controls.'},
 p145:{images:'Adds transparent mold renders from the matching V2 Base or Touch 3MF print project; print layouts are identified as such, not build quantities.',content:'The recipe is written explicitly instead of referring to unspecified materials.',unresolved:'The silicone product and demolding schedule are not identified in the supplied guide. Confirm them before mixing; Base quantities do not establish a Touch recipe.'},
 p147:{images:'Adds the selected hand’s existing CAD skin renders with quantities.',content:'Touch skins are distinguished from the Base casting recipe; Touch batch masses remain unspecified.'},
 p148:{images:'Adds the matching mold backs, clips and funnel renders.',content:'The 20-minute pot-life claim is identified as a value from the earlier recipe that must be checked against the actual product.'},
}
const TOUCH:Record<string,Changes>={
 'touch-parts':{content:'Adds the five sensor sizes, three short/two long cables, copper wire and screw sizes from the Touch instructions.',unresolved:'The opening Touch kit list says six M1.4×6 screws. The installation diagrams allocate four (two thumb, two board), plus eight M1.4×3 and ten M1.4×4. The remaining two M1.4×6 have no specified destination. Left/right CAD screw counts also differ: the BOM adds only missing sensor screws by area and retains other CAD hardware. The CAD’s two carpal M1.4×8 screws conflict with the new board instruction’s M1.4×6 and need reconciliation.'},
 'touch-ids':{content:'Adds one-at-a-time sensor ID assignment and response checks using the Windows Paxini tool and adapter.'},
 'touch-wrap-short':{content:'Adds 0.2 mm wire, approximately 50 cm per cable, clove-hitch ends, 1 mm turn spacing, pictured short-cable dimensions and tails under 2 mm.'},
 'touch-wrap-long':{content:'Adds the two 280 mm cables with the same wrapping technique.',unresolved:'The long-cable wrap offset/length and the allocation of short/long cables to fingers are absent from the supplied document. Do not copy short-cable dimensions.'},
 'touch-paint':{content:'Adds black marker coloring of the copper wraps.'},
 'touch-route':{content:'Adds gentle bottom-to-top routing with the wraps at the APs.',unresolved:'The finger allocation of 130 mm and 280 mm cables needs confirmation.'},
 'touch-connect':{content:'Adds correct versus reversed sensor connector orientation; contact faces, not wire colors alone, determine orientation.'},
 'touch-mount':{content:'Adds the finger and thumb screw maps, hand tightening and flush sensor seating.'},
 'touch-board-mount':{content:'Adds two M1.4×6 self-tapping screws and mounting only after flashing, while the back pads are still accessible.'},
 'touch-board-connect':{content:'Adds correct versus reversed plugs, physical PCB port assignments and cable-clearance checks. The physical board map is not mirrored for a left hand.'},
 'touch-test':{structure:'Placed after the assembled electronics and before final inspection.',content:'Adds an installed response check for all five finger IDs.'},
}
export function ReviewChanges({step,build}:{step:AssemblyStep;build:Build}){
 const touch=TOUCH[step.id],changes=touch??CHANGES[step.id]??{}
 const guided=!['p1','p23'].includes(step.id)
 return <aside className="assembly-review-notes" aria-label="Changes in this review version">
  <details open><summary>Review notes · changes on this step</summary><dl>
   <div><dt>Structure</dt><dd>{changes.structure??(guided?'One instruction is shown at a time by default. Associated images and commands follow that instruction; Show all keeps the full sequence available.':'The existing interactive layout is retained.')}</dd></div>
   <div><dt>Content</dt><dd>{changes.content??(touch?'New Touch installation instructions.':'Assembly meaning and completion checks are retained. Parts and tools are grouped at the top where specified.')}</dd></div>
   <div><dt>Images</dt><dd>{changes.images??(touch?(step.id==='touch-ids'||step.id==='touch-test'?'Finger IDs are presented as a text table; no new hardware image is invented.':'Relevant images are extracted from the supplied Touch instructions and placed beside their instruction.'):'Existing images and interactive models are retained; each static image follows its matching instruction.')}</dd></div>
  </dl>{changes.unresolved&&<p className="assembly-review-open"><strong>Needs confirmation:</strong> {changes.unresolved}</p>}
  {build.version==='touch'&&['p54','p62'].includes(step.id)&&<p className="assembly-review-open">The supplied Touch CAD labels these bearings as 2 mm wide. The assembly instruction follows the newer 3 mm correction; the CAD asset still needs reconciliation.</p>}
  </details>
 </aside>
}
