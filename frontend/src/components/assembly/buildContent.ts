import baseInventory from '../../../public/assembly/parts/base-right-dynamixel/inventory.json'
import leftInventory from '../../../public/assembly/parts/base-left-dynamixel/inventory.json'
import touchRightInventory from '../../../public/assembly/parts/touch-right-dynamixel/inventory.json'
import touchLeftInventory from '../../../public/assembly/parts/touch-left-dynamixel/inventory.json'
import { replaceCadFigures } from './cadIllustrations'
import { MEDIA, STEPS, type AssemblyStep } from './guide'

export type Build = { side: 'right' | 'left'; motor: 'dynamixel' | 'feetech'; version: 'base' | 'touch' | 'full'; audience: 'internal' | 'external' }
export type Figure = { src: string; caption: string; instruction?:number; side?: string | null; wide?:boolean; photo?: {src:string;caption:string} }
export const GLOSSARY = [
  ['DP', 'The outer finger segment, nearest the fingertip.'],
  ['PP', 'The segment behind DP, toward the hand.'],
  ['AP', 'The finger-base part that allows sideways movement.'],
  ['TP', 'The extra thumb-base part between AP and the hand body.'],
  ['PIP / DIP', 'The DP–PP hinge: ORCA uses PIP for the four fingers and DIP for the thumb’s IP hinge.'],
  ['MCP', 'The bending joint between PP and AP.'],
  ['ABD', 'The side-to-side axis at AP, for abduction and adduction.'],
  ['CMC', 'The thumb-base joint between TP and the carpals.'],
  ['Wrist', 'The joint between the hand body and wrist frame.'],
  ['Carpals', 'The hand body where all five fingers attach.'],
  ['Palm / dorsum', 'The inner face / back of the hand.'],
  ['Flexion / extension', 'Bending the finger toward the palm / straightening it away from the palm.'],
  ['Abduction / adduction', 'Moving sideways away / bringing back. In tendon names, p means toward pinky; t means toward thumb.'],
  ['PTFE', 'Low-friction tubing that guides the tendons through the printed channels.'],
  ['Ashley-Stopper (A-S)', 'A bulky end knot that anchors a tendon in its housing.'],
  ['Spool / ratchet', 'The wheel that winds the tendon / the toothed mechanism that locks the adjustment.'],
  ['Daisy chain', 'Connecting one motor to the next along the motor chain.'],
]
export const KITS: Record<string, string[]> = {
  p1: ['Printed parts & skins', 'Tendon cord', 'PTFE tubing', 'Bearings & pins', 'Screws, nuts & magnets', 'Hex keys / screw bits', 'Ruler & cutters', 'File / sandpaper'],
  p7: ['Ruler', 'Cutters', 'Allen key / screw bit'], p13: ['PTFE · OD 1.5 / ID 0.9 mm', '5 AP parts', 'Carpals', 'Wrist'],
  p15: ['10 PTFE pieces · approx. 8–10 mm'], p16: ['32 tubes for carpals', '32 tubes for wrist'],
  p20: ['Tendon with stopper knot', 'PTFE tube'], p22: ['Iron wire · approx. 0.45 mm'],
  p26: ['10 lengths · 2 m each', '10 mm knot spacing (±5 mm)'], p29: ['DP', 'Double-knot tendon', '2 matching joint bearings'],
  p31: ['PP', 'File / sandpaper'], p33: ['Double-knot tendon', '2×8 pin', '2×6 pin'],
  p35: ['2×6 pin'], 'finishing-pp':['Matching finger skins', '2 matching PP bearings'], p37: ['2 tendons · 75 cm each'],
  p42: ['2 pins · 2×8', '2 matching joint bearings'], p49: ['2 tendons · 75 cm each'],
  p54: ['2 pins · 2×10', '2 matching joint bearings'], p56: ['2 tendons · 75 cm each'],
  p59: ['2 pins · 2×30'], p62: ['2 bearings · 4×8×3 mm'],
  p73: ['Palm skin', '2 pins · 3×50 mm', 'Carpal pulley', '2 bearings · 8×13×4'],
  p75: ['2 screws · M4×20', '2 M4 washers', '2 M4 square nuts', 'PTFE sleeves · ID 4 / OD 6 mm'],
  p89: ['Belt · GT2 142 mm', 'Assembled hand', 'Prepared wrist frame'],
  p93: ['2 fans', '2 M3 nuts', '3 M4 nuts', '2 fan screws · confirm length below', '180 mm 3-pin cable'],
  p99: ['M2 nut per spool', '3 screws · M2×4 per spool', 'Bottom spools', 'Ratchets'],
  p101: ['OH board', '12 V power supply', 'USB-C data cable'],
  p105: ['12 V supply', 'USB-C data cable', 'J-Link', 'Tag-Connect probe'], p150: ['12 V supply', 'USB-C data cable', 'J-Link', 'Tag-Connect probe'],
  p110: ['Connector board', '4-wire board cable', 'J-Link', 'Tag-Connect probe'], p154: ['Connector board', '4-wire board cable', 'J-Link', 'Tag-Connect probe'],
  p115: ['16 prepared spool motors', 'Wrist motor', 'Motor-link cables', '4 cable covers'], p122: ['Wrist motor & pulley carrier', '4 screws · M2×8', 'Wrist pulley', 'Pin · 4×10', 'Bearing · 4×8×3', '3 screws · M4×10', '3 M4 nuts · already in tower'],
  p126: ['16 top spools', '16 bearings · 4×8×3', '16 top-spool screws · confirm size below'], p127: ['4 M3 nuts', 'Metal spool holders', 'M3×14 screws'],
  p129: ['8 magnets', 'Superglue', 'Wiping cloth'], p132: ['Hull magnets', 'Superglue'],
  p136: ['2 M3 nuts', 'M3×14 screw', 'M2×8 screw', 'Cable cover'],
  p142: ['ISO 9409-1-50-4-M6 adapter', '2 matching threaded rods', '4 M6×8 mounting screws', 'M3×14 securing screws · confirm kit quantity'],
  p145: ['Silicone A & B', 'Thinner', 'Pigment', 'Molds', 'Scale', 'Cups', 'Separate mixing sticks', 'Gloves'],
}
export function kit(step:AssemblyStep,build:Build):string[]{
  if(step.id==='p93')return [...KITS.p93.slice(0,-1),build.motor==='dynamixel'?'180 mm 3-pin motor cable':'FeeTech board-to-motor adapter lead']
  if(step.id==='p62')return [`2 bearings · 4×8×${build.version==='touch'?2:3} mm`]
  return KITS[step.id]??[]
}
const CAPTIONS: Record<number, string> = {
  8:'Seat the knot and tuck in the 5 mm tail',10:'Straight paths versus trapped tendons',11:'A fully seated bearing',14:'Printed parts and PTFE channels',15:'AP tube locations',17:'Lined carpals and wrist',19:'Clean channel openings',21:'Pull the PTFE through the channel',23:'Identify the printed parts',27:'Double-knot tendon preparation',30:'DP tendon path and bearings',32:'PP surface finish: rough versus smooth',34:'DP-to-PP assembly sequence',36:'Pins, skin and bearings',39:'Tie the extra knot around the stopper',41:'Pull, trim and seat the AP knot',44:'Four-tendon AP routing',45:'Middle, ring and pinky parts',48:'Thumb DP and PP assembly',51:'Thumb AP stopper reinforcement',53:'Seating the thumb knot',55:'Thumb AP routing',58:'TP stopper reinforcement',59:'TP pin locations',60:'Thumb routing · right hand',61:'Thumb routing · left hand',63:'Seat the thumb joint',66:'Finger routing · right hand',67:'Finger routing · left hand',69:'Thumb attachment',72:'Palm and dorsum tendon groups',74:'Palm skin, pins, pulley and bearings',76:'Wrist preparation',79:'Wrist tendon group routing',81:'Check AP and thumb paths',82:'Find single and double crossings',84:'All tendon paths · right hand',85:'All tendon paths · left hand',89:'Belt between the screw sleeves',91:'Wrist pulley and pin',92:'Wrist drive assembly',95:'Keep fan wiring clear',96:'Tower cable routing',98:'Dynamixel connector PCB placement',100:'Fit the M2 nut before the ratchet',101:'OH board connector locations',103:'Powered OH board and USB-C cable',104:'J-Link connection',105:'Select the order in Bench Helper',106:'Bench Helper readiness',107:'Flash controls and output',108:'Hold the Tag-Connect on the pads',109:'Successful flash output',110:'Joint-sensing and tactile connector boards',111:'Connector-board flashing',114:'Motor power and data connectors',116:'Motor IDs · right hand',118:'Dynamixel motor columns',121:'Motor chain and cable covers',122:'Wrist-to-tower screws',124:'Bottom spool routing',125:'Return the knot tail into the channel',126:'Top spool bearing and screw',127:'Spool-holder nut positions',128:'Secure the metal spool holders',131:'Tower and wrist magnets',134:'Hull magnet positions',135:'Fan side plates',138:'Board and cable placement',140:'Completed hand',151:'OH board flash output',152:'OH board power and USB',156:'Connector-board probe and power',
}
export function figures(step: AssemblyStep, build: Build): Figure[] {
  const items=sourceFigures(step,build).filter(f=>!(step.id==='p35'&&f.instruction===3)&&!(step.id==='p16'&&f.src.endsWith('panel-017-3.png'))&&!(step.id==='p37'&&f.src.endsWith('panel-041-1.png'))&&!(['p37','p52'].includes(step.id)&&build.version!=='full'&&/panel-(041|053)-[24]\.png$/.test(f.src)))
  if(step.id==='p31')return items
  return replaceCadFigures(items.filter(f=>!(step.id==='p150'&&f.src.endsWith('panel-151-1.png'))),build).map(f=>f.src.endsWith('panel-111-1.png')?{...f,wide:true,caption:`Example screen · select ${build.side} hand for this build`}:f)
}
function sourceFigures(step: AssemblyStep, build: Build): Figure[] {
  if (['p1','p6','p23','p26','p80','p83','p105','p115','p42','p54','p59','p64'].includes(step.id)) return []
  if (step.id === 'p13') return ['Index AP','Middle AP','Ring AP','Pinky AP','Thumb AP','Carpals','Wrist frame'].map(label=>({src:(build.version==='touch'?(build.side==='left'?touchLeftInventory:touchRightInventory):(build.side==='left'?leftInventory:baseInventory)).parts.find(p=>p.label===(label==='Carpals'&&build.version==='touch'?'Touch carpals':label))!.thumbnail,caption:label==='Carpals'&&build.version==='touch'?'Touch carpals':label,instruction:2}))
  if (['p45','p46','p68','p73','p135','p139','p129','finishing-pp'].includes(step.id)) return []
  if(build.motor==='dynamixel'&&['p98','p99','p127'].includes(step.id)) return []
  if (step.id === 'p101') return [{src:'./assembly/media/board-connectors.png',caption:'Complete OH board connector diagram',instruction:1}]
  if (step.id === 'p18') return [{src:'./assembly/media/panel-019-4.png',caption:'Clean the carpal channel opening before inserting its PTFE liner',instruction:1}]
  if (step.id === 'p142') return [
    {src:'./assembly/media/mount-1.png',caption:'Earlier mounting kit · rod dimensions differ from the current model; confirm your supplied kit',instruction:2},
    {src:'./assembly/media/mount-3.png',caption:'Remove the hull covers; support the rear cover and connected board',instruction:3},
    {src:'./assembly/media/mount-2.png',caption:'Align the hand with the two mounting rods',instruction:4},
    {src:'./assembly/media/mount-4.png',caption:'Earlier mounting example · four screws shown; the required kit quantity is not yet confirmed',instruction:4},
    {src:'./assembly/media/mount-5.png',caption:'Connect power and USB after securing the hand and checking cable clearance',instruction:5},
  ]
  if (['p97','p98','p117'].includes(step.id) && build.motor === 'feetech') {
    return ['Connector orientation','Connector fully seated','Motor connection','The three cable types','Assembled motor block','HLS2915M connector detail'].map((caption,i) => ({ src:`./assembly/media/feetech-${i+1}.jpg`,caption,instruction:step.id==='p97'?[3,3,3,2,1,3][i]:step.id==='p98'?[1,1,1,2,1,1][i]:[1,1,1,1,3,1][i] }))
  }
  const extra: Record<string, number[]> = {p122:[91,92]}
  const assignments:Record<string,number[]> = {
    p10:[1,2],p11:[1],p13:[2,2],p15:[1,2],p16:[1,1,1,1,1],p18:[1,1,2,2],p20:[1,2,2],
    p29:[1,2,3,4],p31:[1,1,2],p33:[1,2,2,3,3,3],p35:[1,2,3,3,3],
    p37:[1,2,3,3,3,3,3],p40:[1,1,2,2,2],p42:[1,2],p46:[1],p49:[2,2],p52:[1,1,2,3,3],
    p54:[1,2,2],p56:[1,2],p59:[1,2,2],p62:[1,1,2],p64:[2,2,2],p68:[1,2],p70:[1],
    p73:[1,2,2,2],p75:[1,2,3],p77:[1,2],p80:[2,2,2,2,2,2,1,1],p83:[1,1,1],p89:[1,2,2,3,3,3],
    p93:[2,1,3,1],p98:[1,2],p99:[1],p101:[1,2,3],p105:[1,2,2,2,3,3,3,3,4],p110:[1,3,2,2,4],
    p112:[2,3],p115:[1,1],p117:[1,2,2],p119:[1,1,2,3],p122:[4,2,2,2,2,2],p123:[1,1,3,3],p126:[1,1],p127:[1,2],
    p129:[2],p132:[1],p135:[1],p136:[3,1,2,3,4],p139:[1],p150:[2,2],p154:[1,1],
  }
  return [...step.pages,...(extra[step.id] ?? [])].flatMap<Figure>(p => MEDIA[String(p)] ? (MEDIA[String(p)].panels ?? [{ ...MEDIA[String(p)], caption: CAPTIONS[p] ?? step.title }]) : []).filter(m => !m.side || m.side === build.side || step.id === 'p115').map((figure,i)=>({...figure,instruction:assignments[step.id]?.[i]??Math.min(i+1,instructions(step,build).length),caption:`${step.title}: ${instructions(step,build)[(assignments[step.id]?.[i]??1)-1]??step.title}`})).filter(f=>!(step.id==='p77'&&f.src.endsWith('panel-079-2.png'))).filter(f=>step.id!=='p110'||!f.src.endsWith(build.version==='touch'?'panel-110-1.png':'panel-110-2.png'))
}
export function instructions(step: AssemblyStep, build: Build): string[] {
  switch (step.id) {
    case 'p93': return [`Fit the two M3 nuts in the fan-mounting pockets shown. Route ${build.motor==='dynamixel'?'the 180 mm 3-pin motor cable':'the matching FeeTech board-to-motor adapter lead'} through the upper cable slot. Fit both fans and pass their leads through the lower slot.${build.motor==='feetech'?' If your supplied tower has one shared cable opening, pass both cable sets through it.':''}`, 'Secure the fans with two M3 screws after confirming their length below. Keep the wires clear of the fan blades and screw holes; check that the cables cannot be pinched.', step.instructions[2]]
    case 'p6': return ['Identify the long standing part and the short working end. Make a bight, then fold it into two loops.', 'Pass the loop on the standing-part side through the other loop. Feed the working end through the loop you just passed through.', 'Snug the half knot first, keeping the working end inside the remaining loop. Then tighten the working end, followed by the standing part.', 'Check the underside: the stopper should have three distinct lobes. Practice until you can repeat it consistently.']
    case 'p29': return ['Thread both free ends of one prepared double-knot tendon through the DP housing, from the middle toward the outside.', 'Pull the reinforced stoppers against their seats. The two reinforced knots sit inside the housing; the loop between them must also be tucked inside.', 'Tuck the remaining loop fully into the housing with an Allen key or screw bit.', 'Press in two matching joint bearings, one on each side.']
    case 'p33': return [step.instructions[0],step.instructions[1], 'Route the DP tendon from the lettered top through the PP top hole. Draw both strands straight and check for crossings before snapping the joint together.', 'Fully seat the bearing. The joint must rotate freely without sideways play. If it binds, reopen it and check for a trapped tendon or rough printed surface.']
    case 'p62': return [step.instructions[0], `Add two 4×8×${build.version==='touch'?2:3} mm bearings. All five fingers should now be assembled.`, ...step.instructions.slice(2)]
    case 'finishing-pp': return build.version==='touch'?['Fit the I-PP skin. The fingertip uses a Touch module instead of the Base DP skin; complete its sensor installation before closing the fingertip.', 'Seat the two 4×8×2 mm PP bearings. Check that the skin clears the moving joint.']:['Fit the I-DP and I-PP skins.', 'Seat the two 4×8×3 mm PP bearings. Check that the skins clear the moving joint.']
    case 'p42': return [step.instructions[0]+' Channel labels: 1 = PP extension; 2 = PP flexion; 3 = DP flexion; 4 = DP extension.',...step.instructions.slice(1)]
    case 'p59': return [step.instructions[0],step.instructions[1]+' Labels: 1 = AP toward thumb (away from pinky); 2 = PP extension; 3 = DP extension; 4 = DP flexion; 5 = PP flexion; 6 = AP toward pinky.']
    case 'p64': return [step.instructions[0],step.instructions[1]+' Labels: 1 = AP toward pinky; 2 = PP extension; 3 = DP extension; 4 = DP flexion; 5 = PP flexion; 6 = AP toward thumb.']
    case 'p54': return [step.instructions[0]+' Channel labels: 1 = PP extension; 2 = PP flexion; 3 = DP flexion; 4 = DP extension.',...step.instructions.slice(1), 'Fully seat the bearings, then check smooth movement through the joint’s full range. Correct trapped tendons or rough surfaces now.']
    case 'p97': return build.motor === 'feetech' ? ['Use short cables between neighboring motors; FeeTech does not use the Dynamixel connector PCBs.', 'Use the long cable across the bottom motors. The thin-to-thick cables connect the board to the first finger motor and the last finger motor to the wrist motor.', 'Switch the board OFF before adding or removing a motor. Align the small connector hole and plug, seat it fully, then power ON to configure.', 'Configure with --motor-type feetech. Never use Dynamixel configuration tools for FeeTech.'] : ['Use the connector PCBs to join neighboring Dynamixel motors, then link the column bottoms with the short 3-pin cables.', 'Use the Dynamixel output on the OH board. The FeeTech output is a different connector.', 'The connector PCBs should already be seated in the tower. Next, prepare the spools and assign IDs one motor at a time.']
    case 'p98': return build.motor === 'feetech' ? ['Skip the connector PCBs: connect neighboring FeeTech motors directly with the short cables.', 'Use the cable-type photos to identify the long and thin-to-thick cables. Keep the board off while connecting.'] : ['Fit a motor connector PCB in each square housing with a round center peg.', 'Repeat for all twelve connector PCB positions shown. Check that every board sits flat.']
    case 'p101': return ['Identify the 12 V input, USB-C data port, motor outputs and fan outputs in the labeled diagram.', 'Use the motor output matching your selected motor type. Keep power off while adding or removing connections.', ...(build.audience==='internal'?['For a new board, continue to either flashing method below. A blank OH board needs its bootloader installed through J-Link first.']:['Your supplied board should already be flashed. Connect power and USB-C when you reach motor configuration.'])]
    case 'p136': return step.instructions.map((text,i)=>i===0?`Keep board power off. Connect the two fan cables to the side connectors and the motor cable to the ${build.motor==='feetech'?'FeeTech':'Dynamixel'} output.`:i===3&&build.version!=='base'?text.replace('the motor cable through','the motor cable and the 4-wire connector-board cable through'):text)
    case 'p105': return ['Open ORCA Console → Flashing. Select the correct order and confirm its hand side, version and motor type.', 'Check Bench Helper. If it is not connected, open Bench setup and start the helper, then wait for the ready state.', 'Press Flash. Hold the Tag-Connect firmly on the OH board pads when the tool asks for the bootloader connection.', 'When prompted, lift the Tag-Connect OFF the pads. Keep power and USB connected while firmware and identity are written.', 'Wait for the flashed-and-linked success message. Use Show output if the process fails; check the connections before retrying.']
    case 'p150': return ['From your orca_firmware checkout, run ./setup.sh once to install the repo-local tooling. Install SEGGER J-Link software separately. On Windows use Git Bash; on Apple Silicon follow setup’s Rosetta instructions.', 'Connect 12 V and a USB-C data cable. Connect J-Link to the computer and have the Tag-Connect ready for a blank board.', `Run the flash command below for this ${build.side} ${build.version} hand. Review the identity it prints; set the correct serial in oh_board/hand.yaml if needed.`, 'If the bootloader is missing, hold the probe on the pads for that stage. Take the probe OFF when the script asks; it must be off before the USB upload and reboot.', 'Wait for firmware and identity verification to succeed. The USB device should appear as ORCA. A 0.000 V probe reading means the board is unpowered or the probe is not seated.']
    case 'p110': return build.version === 'base' ? ['A base hand does not need a touch or joint-sensing connector board. Continue to the motor chain.'] : ['Power the connector board through the OH board’s 4-wire cable; the OH board’s green LEDs must be on.', `Select firmware for the ${build.side} hand. Keep the Tag-Connect on the connector board’s six pads for the entire flash.`, build.version === 'touch' ? 'The tactile connector board has its flashing pads on the back.' : 'Use the joint-sensing connector board and the probe placement shown.', 'Wait for the flash-complete message before removing the probe. The terminal alternative is available below.']
    case 'p112': return ['From a terminal in your installed orca_core checkout, run the command below. It selects the model matching this build; the assembly selector does not change the configuration of a connected hand.', `Power the OH board with 12 V and connect to its ${build.motor === 'feetech' ? 'FeeTech' : 'Dynamixel'} motor output.`, 'Wait for “Scanning for motor …” before introducing the top-right palm-side motor, ID 17.', ...(build.motor === 'feetech' ? ['Power the board OFF while making each motor connection, then turn it back ON to configure. Never hot-plug a FeeTech motor.'] : [])]
    case 'p115': return build.motor==='feetech' ? [step.instructions[0], 'Power OFF, connect the next motor with its plug correctly oriented, then power ON. Wait for detection before adding another. Never hot-plug FeeTech motors.', ...step.instructions.slice(2)] : step.instructions
    case 'p117': return build.motor === 'feetech' ? ['For each motor, switch the board off, add the next motor with the correctly oriented cable, then power on.', 'Wait until the configuration tool finds the current motor before adding another. Follow the descending 17 → 1 ID order.', 'Build columns of four motors with direct cables; do not fit Dynamixel connector PCBs.'] : step.instructions
    case 'p139': return ['Work through every mechanical check below before tensioning. Reopen the linked assembly step if something needs correcting.', 'Correct any binding, misplaced skin, loose knot or crossed tendon now. Calibration cannot fix a mechanical assembly problem.']
    case 'p141': return ['Close this guide to return to Setup and use the existing Full setup workflow.', 'Start tensioning and keep clear while the motors wind the tendons. Wait until they are holding before adjusting the spools.', 'Turn each top spool clockwise with the ratchet until its tendon is firm. Leave a little give; do not overtighten.', 'Press Release when every spool is done. Full setup then calibrates the joints; keep fingers and objects clear during motion. Repeat the rounds offered by Setup until the tendons remain firm.']
    case 'p142': return ['Check that the supplied aluminum ISO 9409-1-50-4-M6 connector plate matches the arm flange. Confirm the mounting hardware listed below before starting; the hand is controlled independently through USB-C.', 'With the arm and hand unpowered, secure the plate to the flange using four M6×8 low-profile screws that match the supplied plate. Fit the two matching threaded rods. Use the arm manufacturer’s tightening specifications.', 'Remove the hull covers to access the mounting points. Support the rear cover with its control board; keep its connected cables slack.', 'Align the hand with both rods and slide it onto the adapter. Secure it with the supplied M3×14 screws at the mounting points confirmed for your kit. Do not use the older picture alone to choose the screw count.', 'Refit the covers without trapping wires. Route the power and USB-C cables along the arm, leaving enough slack for the intended arm motion. Check that the hand is secure and the cables are clear before powering up.']
    default: return step.instructions
  }
}
export const FINAL_CHECKS = [
  'Every bearing is seated; joints rotate without sideways play.',
  'Joint movement is smooth, without abrupt friction or binding.',
  'Each finger has the correct skin; no skin rubs a joint or leaves an unintended gap.',
  'Knots and loose tails are tucked into their housings.',
  'Carpal-to-wrist tendons are straight, alternating and uncrossed.',
  'PTFE ends protrude evenly by about 1 mm; none are pinched between the carpal rods.',
  'The palm skin is seated at every attachment point.',
  'Each spool has three tendon turns with one Ashley stopper, or the short-tendon fallback has two extra single knots on top.',
  'All hull magnets attract and remain securely seated when the panels are removed.',
  'The M3 spool-holder screws and bottom H-shaped cable holders are installed.',
]
export const RELATED: Record<string, {id:string;label:string}[]> = {
  p26:[{id:'p6',label:'Tie an Ashley-Stopper knot'}], p37:[{id:'p6',label:'Knot technique'}],
  p46:[{id:'p29',label:'DP assembly'},{id:'p31',label:'PP preparation'},{id:'p33',label:'Join DP and PP'},{id:'finishing-pp',label:'Skins and PP bearings'}],
  p45:[{id:'p26',label:'Repeat the finger assembly'}], p68:[{id:'p59',label:'Thumb tendon order'}],
  p15:[{id:'p20',label:'Help with a tight PTFE channel'}], p16:[{id:'p20',label:'Help with a tight PTFE channel'},{id:'p22',label:'Reusing a blocked tube'}],
  p77:[{id:'p70',label:'Identify the two tendon groups'}], p123:[{id:'p83',label:'Open tendon mapping'}],
  p126:[{id:'p83',label:'Open tendon mapping'}],
  'motor-check':[{id:'p115',label:'Locate motor IDs'},{id:'p83',label:'Trace tendon identities'},{id:'p126',label:'Check spool pairing'}],
  p139:[{id:'p80',label:'Check for crossed tendons'},{id:'p83',label:'Verify all 32 tendon identities'}],
}
export function commands(step: AssemblyStep, build: Build): string[] {
  if (step.id === 'p112') return [`uv run python scripts/configure_motor_chain.py orca_core/models/v2/orcahand${build.version==='base'?'':`-${build.version}`}-${build.side}/config.yaml --motor-type ${build.motor}`]
  if (step.id === 'p150') return ['cd orca_firmware\n./setup.sh', `cd oh_board\n./flash.sh --side ${build.side} --config ${build.version==='full'?'touch-js':build.version}`]
  if (step.id === 'p154') return [`cd orca_firmware/connector_board\n./flash.sh --${build.side === 'right' ? 'r' : 'l'}`]
  return []
}
export function note(step: AssemblyStep, build: Build) {
  if (step.id === 'p142') return 'Mounting kit details still need confirmation: the written mounting instructions specify 3 M3×14 securing screws, while the older illustration shows 4. The current adapter model also has 4 radial holes. The older picture specifies M5×100 rods, but the current rod geometry is 80 mm long; its thread specification is not confirmed. Match the physical mounting kit before assembly.'
  if (step.id === 'p93') return 'Confirm the fan screw length before fitting: the written instruction specifies M3×14, while the Base and Touch Dynamixel assemblies contain M3×12 at the two fan fixings. Match the supplied screw to the fan and nut pocket; do not substitute a longer screw without checking clearance.'
  if (['p29','p35','finishing-pp','p42','p46','p54'].includes(step.id)) return build.version==='touch'?'Use 4×8×3 mm bearings at DP and 4×8×2 mm bearings at PP and AP.':'Use 4×8×3 mm joint bearings.'
  if (['p145','p147','p148'].includes(step.id)) return 'Optional: cast skins only if you are making your own. These quantities and molds are for Base skins. The silicone product and demolding time are not specified here; confirm both before mixing. Touch and Full need their own matching skin and mold set.'
  if (step.id === 'p123') return 'The numbered map identifies each joint’s two tendons and motor. The bottom-versus-top assignment is not yet specified for every configuration. Confirm that assignment before cutting or anchoring a tendon; checking the joint pair alone does not establish the winding direction.'
  if (step.id === 'p126') return 'Confirm the supplied top-spool screw before fitting: the written size is M2×8, while the CAD assembly contains M2.5×8.'
  if (step.id === 'p97') return build.motor === 'feetech' ? 'Power off before every cable change. Reversed connectors permanently damage FeeTech motors.' : undefined
  if (step.id === 'p117') return build.motor === 'feetech' ? step.note : undefined
  if (step.id === 'p141') return 'Tensioning and calibration stay in Setup so the existing motor controls and safety checks remain available.'
  return step.note
}

export type FlashingMethod = 'console' | 'firmware'
export function buildSteps(build: Build, method?: FlashingMethod): AssemblyStep[] {
  return STEPS.filter(s => !(method==='console'&&['p150','p154'].includes(s.id)) && !(method==='firmware'&&['p105','p110'].includes(s.id)) && !(build.version === 'base' && ['p110','p154'].includes(s.id)) && !(build.audience==='external' && ['p105','p110','p150','p154'].includes(s.id))).map(s => {
    if (build.motor === 'feetech' && s.id === 'p98') return {...s,title:'Fit the direct motor cables',check:'The FeeTech cables are correctly oriented and seated.'}
    if (s.id === 'p101' && build.audience==='internal') return {...s,check:'I have identified the power, USB and correct motor connectors.'}
    if (s.id === 'p101' && build.audience==='external') return {...s,check:'I have identified the power, USB and correct motor connectors.'}
    if (s.id === 'p110') return {...s,title:`Prepare the ${build.version === 'full' ? 'Full' : 'Touch'} connector board`}
    return s
  })
}
