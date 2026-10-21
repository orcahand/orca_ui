import {resolvedFigure} from './photoResolution'
import baseInventory from '../../../public/assembly/parts/base-right-dynamixel/inventory.json'
import leftInventory from '../../../public/assembly/parts/base-left-dynamixel/inventory.json'
import touchRightInventory from '../../../public/assembly/parts/touch-right-dynamixel/inventory.json'
import touchLeftInventory from '../../../public/assembly/parts/touch-left-dynamixel/inventory.json'
import { replaceCadFigures } from './cadIllustrations'
import { MEDIA, STEPS, type AssemblyStep } from './guide'
import { TOUCH_FIGURES, TOUCH_KITS, TOUCH_STEPS } from './touchGuide'

export type Build = { side: 'right' | 'left'; motor: 'dynamixel' | 'feetech'; version: 'base' | 'touch' | 'full'; audience: 'internal' | 'external' }
export type Figure = { src: string; caption: string; instruction?:number; showCaption?:boolean; contrast?:boolean; side?: string | null; wide?:boolean; photo?: {src:string;caption:string} }
export const GLOSSARY = [
  ['DP · distal phalanx', 'The outer finger segment, nearest the fingertip.'],
  ['PP · proximal phalanx', 'The segment behind DP, toward the hand.'],
  ['AP · abduction phalanx', 'The finger-base phalanx that allows sideways movement.'],
  ['TP · thumb phalanx', 'The extra thumb-base phalanx between AP and the hand body.'],
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
  p15: ['8 AP PTFE liners · 5–6mm', '2 thumb AP PTFE liners · 18mm', '5 AP parts'], p16: ['Carpals and wrist frame', '32 PTFE liners for carpals · 60mm max', '32 PTFE liners for wrist'],
  p20: ['Tendon with stopper knot', 'PTFE tube'], p22: ['Iron wire · approx. 0.45 mm'],
  p26: ['Tendon cord · 10 lengths, 2 m each'], p29: ['DP', 'Double-knot tendon', '2 matching joint bearings'],
  p31: ['PP', 'File / sandpaper'], p33: ['Double-knot tendon', '2×8 pin', '2×6 pin'],
  p35: ['2×6 pin'], 'finishing-pp':['Matching finger skins', '2 matching PP bearings'], p37: ['2 tendons · 75 cm each'],
  p42: ['2 pins · 2×8', '2 matching joint bearings'], p49: ['2 tendons · 75 cm each'],
  p54: ['2 pins · 2×10', '2 matching joint bearings'], p56: ['2 tendons · 75 cm each'],
  p59: ['2 pins · 2×30'], p62: ['2 bearings · 4×8×3 mm'],
  p73: ['Palm skin', '2 pins · 3×50 mm', 'Carpal pulley', '2 bearings · 8×13×4'],
  p75: ['2 screws · M4×20', '2 M4 washers', '2 M4 square nuts', 'PTFE sleeves · ID 2.7 / OD 4 mm'],
  p89: ['Belt · GT2 142 mm', 'Assembled hand', 'Prepared wrist frame'],
  p93: ['2 fans', '2 M3 nuts', '3 M4 nuts', '2 fan screws · M3×12 in current CAD (earlier guide: M3×14; verify supplied kit)', '180 mm 3-pin cable'],
  p99: ['M2 nut per spool', '3 screws · M2×4 per spool', 'Bottom spools', 'Ratchets'],
  p101: ['OH board', '12 V power supply', 'USB-C data cable'],
  p105: ['OH board', '12 V supply', 'USB-C data cable', 'J-Link', 'Tag-Connect probe'], p150: ['OH board', '12 V supply', 'USB-C data cable', 'J-Link', 'Tag-Connect probe'],
  p110: ['OH board, 12 V supply and USB-C data cable', 'Connector board', '4-wire board cable', 'J-Link', 'Tag-Connect probe'], p154: ['OH board, 12 V supply and USB-C data cable', 'Connector board', '4-wire board cable', 'J-Link', 'Tag-Connect probe'],
  p115: ['16 prepared spool motors', 'Wrist motor', 'Motor-link cables', '4 cable covers'], p122: ['Wrist motor & pulley carrier', '4 screws · M2×8', 'Wrist pulley', 'Pin · 4×10', 'Bearing · 4×8×3', '3 screws · M4×10', '3 M4 nuts · already in tower'],
  p126: ['16 top spools', '16 bearings · 4×8×3', '16 top-spool screws · M2.5×8 in current CAD (earlier guide: M2×8; verify supplied thread)'], p127: ['4 M3 nuts', 'Metal spool holders', 'M3×14 screws'],
  p129: ['8 magnets', 'Superglue', 'Wiping cloth'], p132: ['Hull magnets', 'Superglue'],
  p136: ['2 M3 nuts', 'M3×14 screw', 'M2×8 screw', 'Cable cover'],
  p142: ['ISO 9409-1-50-4-M6 adapter', '2 matching threaded rods', '4 M6×8 mounting screws', 'M3×14 securing screws · confirm kit quantity'],
  p145: ['Silicone A & B', 'Thinner', 'Pigment', 'Molds', 'Scale', 'Cups', 'Separate mixing sticks', 'Gloves'],
}
export function kit(step:AssemblyStep,build:Build):string[]{
  if(['p23'].includes(step.id))return []
  if(TOUCH_KITS[step.id])return TOUCH_KITS[step.id]
  const pp=build.version==='touch'?'4×8×2 mm':'4×8×3 mm'
  const extra:Record<string,string[]>={
    'prepare-pp':['PP','Prepared double-knot tendon','1 middle pin · Ø2×8 mm','1 lower pin · Ø2×6 mm'],p33:[build.version==='touch'?'Prepared bare PP with tendon, pins and bearings':'Prepared PP with tendon, pins, skin and bearings','Prepared DP','1 upper pin · Ø2×6 mm'],
    p6:['Practice tendon cord'],p23:['Selected hand model and parts'],
    p18:['Printed carpals','Soft brush for loose print debris'],
    p20:['Tendon with stopper knot','PTFE · OD 1.5 / ID 0.9 mm','Printed part with tight channel'],
    p22:['Reused PTFE tube','Iron wire · approximately Ø0.45 mm'],
    p29:['DP','Prepared double-knot tendon','2 bearings · 4×8×3 mm'],
    p35:['Assembled index finger · six free tendon ends'],p31:['DP','PP','AP'],
    'pp-ready':['PP with tendon and guide pins',...(build.version==='touch'?[]:['Matching PP skin']),`2 PP bearings · ${pp}`],
    'finishing-pp':[build.version==='touch'?'Assembled finger with PP skin':'Assembled finger with PP skin and matching DP skin'],
    p37:['AP with two PTFE liners','2 tendons · 75 cm each','Ruler, cutters and small blunt tool for tucking tails'],
    p42:['Prepared DP/PP and AP','2 pins · Ø2×8 mm',`2 AP bearings · ${pp}`],
    p45:[build.version==='touch'?'Middle, ring and pinky printed parts · leave all skins off':'Middle, ring and pinky printed parts and matching skins','3 prepared DP/PP tendon sets','6 AP tendons · 75 cm each','6 DP bearings · 4×8×3 mm',`6 PP + 6 AP bearings · ${pp}`,'6 pins · Ø2×6 mm','9 pins · Ø2×8 mm'],
    'thumb-tendons':['1 prepared DP double-knot tendon · 2 m','1 unknotted PP tendon · 2 m from the ten-length set'],
    'thumb-parts':['Thumb DP','Thumb PP','Thumb AP','Thumb TP'],
    'thumb-dp':['Thumb DP','Prepared double-knot tendon','2 DP bearings · 4×8×3 mm'],
    'thumb-pp':['Thumb PP',build.version==='base'?'Prepared double-knot tendon':'Unknotted tendon · 2 m','1 middle pin · Ø2×8 mm','1 lower pin · Ø2×6 mm'],
    'thumb-pp-ready':['Prepared thumb PP',...(build.version==='touch'?[]:['Matching thumb PP skin']),`2 PP bearings · ${pp}`],
    'thumb-tp-pins':['Thumb TP with prepared anchors','2 pins · Ø2×30 mm'],
    'thumb-skins':[build.version==='touch'?'Assembled thumb with PP skin':'Assembled thumb with PP skin and matching DP skin'],
    'thumb-test':['Assembled thumb · eight free tendon ends'],
    p46:['Prepared thumb DP',build.version==='touch'?'Prepared bare thumb PP with tendon, bearings and two guide pins':'Prepared thumb PP with tendon, skin, bearings and two guide pins','1 upper pin · Ø2×6 mm'],
    p49:['Thumb AP with two PTFE liners','2 tendons · 75 cm each','Ruler and cutters'],
    p54:['Prepared thumb DP/PP and AP','2 pins · Ø2×10 mm','2 thumb AP bearings · 4×8×3 mm'],
    p56:['Thumb TP','2 tendons · 75 cm each','Ruler and cutters'],
    p59:['Assembled thumb DP/PP/AP','Prepared TP with two guide pins and two anchor ends'],
    p62:['Thumb assembly','2 thumb TP bearings · 4×8×3 mm'],
    p64:['4 assembled fingers','Carpals with 32 PTFE liners'],p68:['Assembled thumb with 8 tendon ends','Carpals'],
    p70:['Hand with all 32 tendon ends'],
    p77:['Prepared hand','Wrist with 32 PTFE liners'],p80:['Hand and wrist with routed tendons'],p83:['Hand and wrist with 32 free tendon ends'],
    p98:build.motor==='feetech'?['Tower','FeeTech direct motor cables']:['Tower','12 Dynamixel motor connector PCBs'],
    p112:['OH board','12 V supply','USB-C data cable',build.motor==='feetech'?'FeeTech motors and matching adapter cable':'Dynamixel motors and matching 3-pin cable','Computer with orca_core installed'],
    p123:['16 bottom spools on installed motors','32 identified tendon ends','Ruler and cutters'],
    p135:['2 fan side plates','Assembled tower'],p139:['Completed mechanical assembly'],p141:['Assembled hand','ORCA UI Setup workflow'],
    'motor-check':['Tensioned and calibrated hand','12 V supply and USB-C data cable','ORCA UI connection'],
    p147:['Matching Base skin molds','Scale','Silicone A and B · equal masses'],
    p148:['Assembled Base molds','Silicone A and B · 1:1','Thinner · 5–10% of A','Pigment · white 2% or black 2–3% of A','Scale, separate cups and sticks, gloves'],
  }
  if(extra[step.id])return extra[step.id]
  if(step.id==='p93')return [...KITS.p93.slice(0,-1),build.motor==='dynamixel'?'180 mm 3-pin motor cable':'FeeTech board-to-motor adapter lead']
  return KITS[step.id]??[]
}

const CAPTIONS: Record<number, string> = {
  8:'Seat the knot and tuck in the 5 mm tail',10:'Straight paths versus trapped tendons',11:'A fully seated bearing',14:'Printed parts and PTFE channels',15:'AP tube locations',17:'Lined carpals and wrist',19:'Clean channel openings',21:'Pull the PTFE through the channel',23:'Identify the printed parts',27:'Double-knot tendon preparation',30:'DP tendon path and bearings',32:'PP surface finish: rough versus smooth',34:'DP-to-PP assembly sequence',36:'Pins, skin and bearings',39:'Tie the extra knot around the stopper',41:'Pull, trim and seat the AP knot',44:'Four-tendon AP routing',45:'Middle, ring and pinky parts',48:'Thumb DP and PP assembly',51:'Thumb AP stopper reinforcement',53:'Seating the thumb knot',55:'Thumb AP routing',58:'TP stopper reinforcement',59:'TP pin locations',60:'Thumb routing · right hand',61:'Thumb routing · left hand',63:'Seat the thumb joint',66:'Finger routing · right hand',67:'Finger routing · left hand',69:'Thumb attachment',72:'Palm and dorsum tendon groups',74:'Palm skin, pins, pulley and bearings',76:'Wrist preparation',79:'Wrist tendon group routing',81:'Check AP and thumb paths',82:'Find single and double crossings',84:'All tendon paths · right hand',85:'All tendon paths · left hand',89:'Belt between the screw sleeves',91:'Wrist pulley and pin',92:'Wrist drive assembly',95:'Keep fan wiring clear',96:'Tower cable routing',98:'Dynamixel connector PCB placement',100:'Fit the M2 nut before the ratchet',101:'OH board connector locations',103:'Powered OH board and USB-C cable',104:'J-Link connection',105:'Select the order in Bench Helper',106:'Bench Helper readiness',107:'Flash controls and output',108:'Hold the Tag-Connect on the pads',109:'Successful flash output',110:'Joint-sensing and tactile connector boards',111:'Connector-board flashing',114:'Motor power and data connectors',116:'Motor IDs · right hand',118:'Dynamixel motor columns',121:'Motor chain and cable covers',122:'Wrist-to-tower screws',124:'Bottom spool routing',125:'Return the knot tail into the channel',126:'Top spool bearing and screw',127:'Spool-holder nut positions',128:'Secure the metal spool holders',131:'Tower and wrist magnets',134:'Hull magnet positions',135:'Fan side plates',138:'Board and cable placement',140:'Completed hand',151:'OH board flash output',152:'OH board power and USB',156:'Connector-board probe and power',
}
export function figures(step: AssemblyStep, build: Build): Figure[] {
  if(TOUCH_FIGURES[step.id])return TOUCH_FIGURES[step.id].map(f=>({...f,contrast:false}))
  const items=sourceFigures(step,build).filter(f=>!(build.version==='base'&&['p49','p56'].includes(step.id)&&/panel-(051|058)-2\.png$/.test(f.src))&&!(step.id==='p33'&&f.src.endsWith('panel-034-6.png'))&&!(step.id==='p35'&&f.instruction===3)&&!(step.id==='p16'&&f.src.endsWith('panel-017-3.png'))&&!(step.id==='p37'&&f.src.endsWith('panel-041-1.png'))&&!(['p37','p49'].includes(step.id)&&build.version!=='full'&&/panel-(041|053)-[24]\.png$/.test(f.src)))
  if(step.id==='touch-skins')return (build.side==='left'?touchLeftInventory:touchRightInventory).parts.filter(p=>p.label.endsWith('PP skin')).map(p=>({src:p.thumbnail,caption:p.label,instruction:2,showCaption:true}))
  if(step.id==='thumb-dp')return ['feed','seat','tuck'].map((phase,i)=>({src:`./assembly/renders/${build.version==='touch'?'touch':'base'}-${build.side}-dynamixel/thumb-dp-${phase}.webp`,caption:['Feed both ends through the thumb DP housing','Seat the reinforced stoppers','Tuck the connecting loop inside'][i],instruction:i===0?1:2,contrast:true,showCaption:true}))
  if(step.id.startsWith('thumb-')||['p35','pp-ready'].includes(step.id))return []
  if(step.id==='p31')return items.map(f=>resolvedFigure({...f,contrast:false}))
  const whiteMaterial=['p29','prepare-pp','p33','p35','p37','p46','p49','p52','p54','p56','p62','p75','p77','p89','p123','p126'].includes(step.id)
  return replaceCadFigures(items.filter(f=>!(step.id==='p150'&&f.src.endsWith('panel-151-1.png'))),build).map(f=>({...f,contrast:f.photo?whiteMaterial:step.id==='p147'&&build.version==='base',...(f.src.endsWith('panel-111-1.png')?{wide:true,showCaption:true,caption:`Example screen · select ${build.side} hand for this build`}:{})})).map(f=>({...f,instruction:step.id==='p33'&&f.src.includes('panel-036-')?3:f.instruction})).map(resolvedFigure)
}
function sourceFigures(step: AssemblyStep, build: Build): Figure[] {
  if(step.id.startsWith('thumb-')||['p35','pp-ready'].includes(step.id))return []
  if(['prepare-pp','p33'].includes(step.id))return (MEDIA['34'].panels??[]).filter(f=>step.id==='prepare-pp'?/panel-034-[123]\.png$/.test(f.src):/panel-034-[456]\.png$/.test(f.src)).map(f=>({...f,instruction:step.id==='prepare-pp'?(f.src.endsWith('-3.png')?2:1):(f.src.endsWith('-6.png')?2:1)})).concat(step.id==='p33'?(MEDIA['36'].panels??[]).filter(f=>/panel-036-[12]\.png$/.test(f.src)).map(f=>({...f,instruction:3})):[])
  if(step.id==='p123'&&build.motor==='dynamixel')return []
  if(step.id==='p126')return build.motor==='feetech'?[{src:'./assembly/media/panel-126-1.png',caption:'Top spool, bearing and screw · seat the bearing on the bench before installation',instruction:3}]:[]
  if(['p145','p148'].includes(step.id)&&build.version!=='full'){
    const version=build.version
    const plates: [number,string][] = step.id==='p145'
      ? [[2,'Carpal mold halves · choose the L or R set matching your hand'],[4,'PP mold halves · print layout, not a build quantity'],...(version==='base'?[[7,'DP mold halves · Base skins'] as [number,string]]:[])]
      : [[3,'Carpal mold backs and cores · matching L or R set'],[5,'PP mold clips'],[version==='base'?9:7,'Pentafunnel · print layout, not a build quantity']]
    return plates.map(([plate,caption])=>({src:`./assembly/molds/${version}-plate-${plate}.png`,caption,instruction:1,showCaption:true}))
  }
  if(step.id==='p147'&&build.version!=='full')return (build.version==='touch'?(build.side==='left'?touchLeftInventory:touchRightInventory):(build.side==='left'?leftInventory:baseInventory)).parts.filter(p=>p.category==='Skins').map(p=>({src:p.thumbnail,caption:`${p.label} ×${p.count}`,instruction:1,showCaption:true}))
  if(step.id==='p105')return [
    ['105-1',1,'Select the matching order'],['106-1',2,'Bench Helper not connected'],['106-2',2,'Bench Helper ready'],
    ['107-1',3,'Start the flash'],['108-1',3,'OH board power, USB and programming connections'],['108-2',3,'OH board programming probe'],
    ['108-4',4,'Remove the probe when prompted'],['109-1',5,'Flashed and linked'],
  ].map(([id,instruction,caption])=>({src:`./assembly/media/panel-${id}.png`,instruction:Number(instruction),caption:String(caption),wide:true}))
  if(build.version==='touch'&&step.id==='p110')return [{src:'./assembly/media/panel-110-2.png',caption:'Touch connector board · programming pads are on the reverse side',instruction:2}]
  if(build.version==='touch'&&step.id==='p154')return []

  if (['p1','p6','p23','p26','p77','p80','p83','p115','p42','p54','p59','p64'].includes(step.id)) return []
  if (step.id === 'p13') return ['Index AP','Middle AP','Ring AP','Pinky AP','Thumb AP','Carpals','Wrist frame'].map(label=>({src:(build.version==='touch'?(build.side==='left'?touchLeftInventory:touchRightInventory):(build.side==='left'?leftInventory:baseInventory)).parts.find(p=>p.label===(label==='Carpals'&&build.version==='touch'?'Touch carpals':label))!.thumbnail,showCaption:true,caption:label==='Carpals'&&build.version==='touch'?'Touch carpals':label,instruction:2}))
  if (['p45','p46','p68','p73','p135','p139','p129','finishing-pp'].includes(step.id)) return []
  if(build.motor==='dynamixel'&&['p98','p99','p127'].includes(step.id)) return []
  if (step.id === 'p101') return []
  if (step.id === 'p18') return [{src:'./assembly/media/panel-019-4.png',caption:'Earlier screw-based cleanup example · the correct screw size remains unconfirmed; follow the inspection instructions',instruction:1}]
  if (step.id === 'p142') return [
    {src:'./assembly/media/mount-1.png',caption:'Earlier mounting kit · rod dimensions differ from the current model; confirm your supplied kit',instruction:2},
    {src:'./assembly/media/mount-3.png',caption:'Remove the hull covers; support the rear cover and connected board',instruction:3},
    {src:'./assembly/media/mount-2.png',caption:'Align the hand with the two mounting rods',instruction:4},
    {src:'./assembly/media/mount-4.png',showCaption:true,caption:'Earlier mounting example · four screws shown; the required kit quantity is not yet confirmed',instruction:4},
    {src:'./assembly/media/mount-5.png',caption:'Connect power and USB after securing the hand and checking cable clearance',instruction:5},
  ]
  if (['p97','p98','p117'].includes(step.id) && build.motor === 'feetech') {
    return ['Connector orientation','Connector fully seated','Motor connection','The three cable types','Assembled motor block','HLS2915M connector detail'].map((caption,i) => ({ src:`./assembly/media/feetech-${i+1}.jpg`,caption,showCaption:true,instruction:step.id==='p97'?[3,3,3,2,1,3][i]:step.id==='p98'?[1,1,1,2,1,1][i]:[1,1,1,1,3,1][i] }))
  }
  const extra: Record<string, number[]> = {p122:[91,92]}
  const assignments:Record<string,number[]> = {
    p10:[1,2],p11:[1],p13:[2,2],p15:[1,2],p16:[1,1,1,1,1],p18:[1,1,2,2],p20:[1,2,2],
    p29:[1,2,3,4],p31:[1,1,2],p33:[1,2,2,3,3,3],p35:[1,2,3,3,3],
    p37:[1,2,3,3,3,3,3],p40:[1,1,2,2,2],p42:[1,2],p46:[1],p49:[2,2,3,3,3,3,3],
    p54:[1,2,2],p56:[1,2],p59:[2,3,3],p62:[1,1,2],p64:[2,2,2],p68:[1,2],p70:[1],
    p73:[1,2,2,2],p75:[3,2,4],p77:[1,2],p80:[2,2,2,2,2,2,1,1],p83:[1,1,1],p89:[1,2,2,3,3,3],
    p93:[2,1,3,1],p98:[1,2],p99:[1],p101:[1,2,3],p105:[1,2,2,2,3,3,3,3,4],p110:[1,3,2,2,4],
    p112:[2,3],p115:[1,1],p117:[1,2,2],p119:[1,1,2,3],p122:[4,2,2,2,2,2],p123:[1,1,3,3],p126:[1,1],p127:[1,2],
    p129:[2],p132:[1],p135:[1],p136:[3,1,2,3,4],p139:[1],p150:[2,2],p154:[1,1],
  }
  return [...step.pages,...(extra[step.id] ?? [])].flatMap<Figure>(page => {
    const entry=MEDIA[String(page)]
    if(!entry)return []
    const panels=entry.panels??[{...entry,caption:CAPTIONS[page]??step.title}]
    return panels.map(panel=>({...panel,caption:CAPTIONS[page]??step.title}))
  }).filter(figure=>!figure.side||figure.side===build.side||step.id==='p115')
    .map((figure,i)=>({...figure,instruction:assignments[step.id]?.[i]??Math.min(i+1,instructions(step,build).length)}))
    .filter(figure=>!(step.id==='p77'&&figure.src.endsWith('panel-079-2.png')))
    .filter(figure=>step.id!=='p110'||!figure.src.endsWith(build.version==='touch'?'panel-110-1.png':'panel-110-2.png'))

}
export function instructions(step: AssemblyStep, build: Build): string[] {
  if(build.version==='base'){
    if(step.id==='p26')return [step.instructions[0], 'Near the middle of each of the ten lengths, tie two Ashley-Stopper knots 10 mm apart (±5 mm).', step.instructions[2]]
    if(step.id==='thumb-pp')return [...STEPS.find(s=>s.id==='prepare-pp')!.instructions]
    if(step.id==='p46')return [...step.instructions.slice(0,2), DP_PIN_INSTRUCTION]
  }
  switch (step.id) {
    case 'pp-ready': case 'thumb-pp-ready': return build.version==='touch'?['Leave all skins off so the sensor cable channel stays accessible. Fit PP skins in the Touch skins section, after connecting the sensor cables.', 'Press both matching PP bearings into their pockets with your fingers.']:step.instructions
    case 'p35': return build.version==='touch'?[...step.instructions.slice(0,2),'Check that bearings remain seated and guide pins are flush. Leave all skins off until the sensor cables are connected. Correct any binding before continuing.']:step.instructions
    case 'thumb-test': return build.version==='touch'?[...step.instructions.slice(0,2),'Check bearing seats and guide pins. Leave all skins off for the sensor cable steps next. Correct any trapped or crossed tendon before continuing.']:step.instructions

    case 'thumb-skins': return [build.version==='touch'?'Fit the PP skin only after the Touch sensor cable is connected and the sensor is mounted.':'Slide the DP skin over the thumb tip and down. Settle the PP skin already fitted during preparation into its final position.', 'Check that the skin edges clear all thumb joints and keep all eight tendon ends free.']
    case 'p18': return ['Inspect the printed carpal exits and gently clear loose debris with a soft brush.', 'The screw-based cleanup method still needs a confirmed screw size. If an opening remains obstructed, confirm the correct cleanup tool before enlarging it; do not force an arbitrary screw into the tendon channel.']

    case 'p73': return [step.instructions[0], 'Insert two 3×50 mm pins, mount the toothed carpal pulley and add two 8×13×4 bearings. The pulley teeth engage the wrist belt.']
    case 'p89': return [...step.instructions.slice(0,2), 'Check that the two tendon groups remain in order below the wrist.']
    case 'p126': return ['On the workbench, support each loose top spool close to its bearing pocket and seat its 4×8×3 mm bearing fully. Do this before mounting the spool; do not drive a bearing into a spool supported by the tower.', 'Use the opposing tendon from the same joint for the top spool—the bottom tendon stays in its installed spool. Thread and anchor it as before: three turns, one Ashley stopper and a 5 mm tail tucked back into the channel. Use the two-extra-knot fallback only if the tendon is too short for three turns.', 'Fit the prepared top spool with its bearing already seated and secure it with the matching supplied screw listed in Parts. Check the screw thread before tightening.', 'With power off, gently turn one motor back and forth by hand. Its two tendons should move only the matching joint, in opposite directions.']
    case 'p147': return build.version==='touch'?['Review the rendered Touch skin set for the selected hand. Touch uses sensor modules at the fingertips; do not cast Base DP skins for this build.', 'The supplied guide gives batch masses only for the Base molds. Obtain the material specification and quantities for the Touch mold set before mixing.']:step.instructions
    case 'p145': if(build.version==='touch')return ['Gather the matching Touch PP and carpal molds shown, silicone A and B, compatible thinner and pigment, scale, cups, separate mixing sticks and gloves.', 'Confirm the silicone product, mixing ratios, batch quantities and demolding schedule for these molds before casting. The supplied Base recipe is not a verified Touch recipe.'];return ['Gather silicone A and B, compatible thinner and pigment, matching molds, a scale, cups, separate mixing sticks and gloves. Confirm the silicone product and its demolding schedule before mixing.', 'The Base recipe uses A:B = 1:1 by mass; thinner 5–10% of A; white pigment 2% of A or black pigment 2–3% of A. These quantities do not establish a recipe for Touch skins.']
    case 'p148': if(build.version==='touch')return ['Identify the matching Touch mold halves, cores, clips and funnel shown. Confirm your mold assembly and pouring instructions before starting.', 'Use the silicone manufacturer’s verified mixing and cure instructions for this Touch mold set. The supplied document does not establish Touch batch masses or a demolding schedule.'];return [...step.instructions.slice(0,2), 'The earlier Base recipe gives a 20-minute pot life. Check the working time on your actual product before mixing. Stir gently and keep the A and B utensils separate to avoid contamination.']

    case 'p93': return [`Fit the two M3 nuts in the fan-mounting pockets shown. Route ${build.motor==='dynamixel'?'the 180 mm 3-pin motor cable':'the matching FeeTech board-to-motor adapter lead'} through the upper cable slot. Fit both fans and pass their leads through the lower slot.${build.motor==='feetech'?' If your supplied tower has one shared cable opening, pass both cable sets through it.':''}`, 'Secure the fans with the screws listed in Parts, after matching the supplied length to the fan and nut pockets. Keep the wires clear of the fan blades and screw holes; check that the cables cannot be pinched.', step.instructions[2]]
    case 'p6': return ['Identify the long standing part and the short working end. Make a bight, then fold it into two loops.', 'Pass the loop on the standing-part side through the other loop. Feed the working end through the loop you just passed through.', 'Snug the half knot first, keeping the working end inside the remaining loop. Then tighten the working end, followed by the standing part.', 'Check the underside: the stopper should have three distinct lobes. Practice until you can repeat it consistently.']
    case 'p29': return ['Thread both free ends of one prepared double-knot tendon through the DP housing, from the middle toward the outside.', 'Pull the reinforced stoppers against their seats. The two reinforced knots sit inside the housing; the loop between them must also be tucked inside.', 'Tuck the remaining loop fully into the housing with an Allen key or screw bit.', 'Press in two matching joint bearings, one on each side.']
    case 'p33': return ['Route the DP tendon from the lettered top through the PP top hole. Draw both strands straight and check for crossings, then snap the joint together.', 'Fully seat the bearing. The joint must rotate freely without sideways play. If it binds, reopen it and check for a trapped tendon or rough printed surface.', build.version==='base'?DP_PIN_INSTRUCTION:'Add the upper Ø2×6 mm pin. Keep the two DP tendons between the upper and lower pins, and press the pin fully into its seat. Gently pull each DP end to check that it runs freely.']
    case 'p68': return [step.instructions[0],step.instructions[1]+(build.version==='touch'?' Guide the free sensor cable tail through its carpal cable passage as you seat the thumb. Keep it separate from the tendon channels and accessible for the connector board.':''),'With all eight ends slack, check that the seated thumb rotates freely without axial play.']
    case 'p62': return [step.instructions[0], 'Add two 4×8×3 mm thumb TP bearings.', ...step.instructions.slice(2)]
    case 'finishing-pp': return [build.version==='touch'?'Fit the PP skin only after the Touch sensor cable is connected and the sensor is mounted.':'Slide the DP skin over the fingertip and down. Settle the PP skin already fitted during preparation into its final position.', 'Check that skin edges are seated and do not rub or pinch either joint. Keep all six tendon ends free.']
    case 'p45': return build.version==='touch'?[step.instructions[0], 'Leave all skins off. Repeat the tendon seating, routing and friction checks on the bare fingers. Connect the Touch cables and sensors in the section after the thumb, then fit the PP skins.',step.instructions[2]]:step.instructions
    case 'p42': return [step.instructions[0]+' Channel labels: 1 = PP extension; 2 = PP flexion; 3 = DP flexion; 4 = DP extension.',...step.instructions.slice(1)]
    case 'p59': return [step.instructions[0]+' Labels: 1 = AP toward thumb (away from pinky); 2 = PP extension; 3 = DP extension; 4 = DP flexion; 5 = PP flexion; 6 = AP toward pinky.',step.instructions[1]]
    case 'p64': return [step.instructions[0],step.instructions[1]+' Labels: 1 = AP toward pinky; 2 = PP extension; 3 = DP extension; 4 = DP flexion; 5 = PP flexion; 6 = AP toward thumb.'+(build.version==='touch'?' Guide each free sensor cable tail through its carpal cable passage as you seat the finger. Keep it separate from the tendon channels and accessible for the connector board.':''), 'With the tendons slack, check each seated finger joint for free rotation and axial play.']
    case 'p54': return ['Confirm the corrected thumb AP channel order before routing DP and PP tendons. The current diagram is awaiting confirmation of the reversed route reported in the feedback.',...step.instructions.slice(1), 'Fully seat the bearings, then check smooth movement through the joint’s full range. Correct trapped tendons or rough surfaces now.']
    case 'p97': return build.motor === 'feetech' ? ['Use short cables between neighboring motors; FeeTech does not use the Dynamixel connector PCBs.', 'Use the long cable across the bottom motors. The thin-to-thick cables connect the board to the first finger motor and the last finger motor to the wrist motor.', 'Switch the board OFF before adding or removing a motor. Align the small connector hole and plug, seat it fully, then power ON to configure.', 'Configure with --motor-type feetech. Never use Dynamixel configuration tools for FeeTech.'] : ['Use the connector PCBs to join neighboring Dynamixel motors, then link the column bottoms with the short 3-pin cables.', 'Use the Dynamixel output on the OH board. The FeeTech output is a different connector.', 'The connector PCBs should already be seated in the tower. Next, prepare the spools and assign IDs one motor at a time.']
    case 'p98': return build.motor === 'feetech' ? ['Skip the connector PCBs: connect neighboring FeeTech motors directly with the short cables.', 'Use the cable-type photos to identify the long and thin-to-thick cables. Keep the board off while connecting.'] : ['Fit a motor connector PCB in each square housing with a round center peg.', 'Repeat for all twelve connector PCB positions shown. Check that every board sits flat.']
    case 'p101': return ['Identify the 12 V input, USB-C data port, motor outputs and fan outputs in the labeled diagram.', 'Use the motor output matching your selected motor type. Keep power off while adding or removing connections.', 'Connect power and USB-C when you reach motor configuration.']
    case 'p136': return step.instructions.map((text,i)=>i===0?`Keep board power off. Connect the two fan cables to the side connectors and the motor cable to the ${build.motor==='feetech'?'FeeTech':'Dynamixel'} output.`:i===3&&build.version!=='base'?text.replace('the motor cable through','the motor cable and the 4-wire connector-board cable through'):text)
    case 'p105': return ['Open ORCA Console → Flashing. Select the correct order and confirm its hand side, version and motor type.', 'Check Bench Helper. If it is not connected, open Bench setup and start the helper, then wait for the ready state.', 'Press Flash. Hold the Tag-Connect firmly on the OH board pads when the tool asks for the bootloader connection.', 'When prompted, lift the Tag-Connect OFF the pads. Keep power and USB connected while firmware and identity are written.', 'Wait for the flashed-and-linked success message. Use Show output if the process fails; check the connections before retrying.']
    case 'p150': return ['From your orca_firmware checkout, run ./setup.sh once to install the repo-local tooling. Install SEGGER J-Link software separately. On Windows use Git Bash; on Apple Silicon follow setup’s Rosetta instructions.', 'Connect 12 V and a USB-C data cable. Connect J-Link to the computer and have the Tag-Connect ready for a blank board.', `Run the flash command below for this ${build.side} ${build.version} hand. Review the identity it prints; set the correct serial in oh_board/hand.yaml if needed.`, 'If the bootloader is missing, hold the probe on the pads for that stage. Take the probe OFF when the script asks; it must be off before the USB upload and reboot.', 'Wait for firmware and identity verification to succeed. The USB device should appear as ORCA. A 0.000 V probe reading means the board is unpowered or the probe is not seated.']
    case 'p110': return ['In ORCA Console → Flashing, select the order for this hand and confirm Bench Helper is connected. Use the connector-board check/flash action for the selected hand side.', 'Power the connector board through the OH board’s 4-wire cable; the OH board’s green LEDs must be on. Keep the board loose on the bench for access to its programming pads.', build.version==='touch'?'Place the Tag-Connect on the six programming pads on the BACK of the Touch connector board, opposite its component side. Keep the probe seated for the entire connector-board flash.':'Place the Tag-Connect on the six programming pads of the Full connector board and hold it for the entire flash.', 'Wait for the connector-board flash to report success before removing the probe. Switch power off before mounting or connecting cables.']
    case 'p154': return [build.version==='touch'?'Keep the Touch board loose on the bench. Power it through the OH board’s 4-wire cable; hold the Tag-Connect on the six pads on the BACK of the connector board. Keep it seated for the entire flash.':step.instructions[0],step.instructions[1],step.instructions[2]]
    case 'p112': return ['From a terminal in your installed orca_core checkout, run the command below. It selects the model matching this build; the assembly selector does not change the configuration of a connected hand.', `Power the OH board with 12 V and connect to its ${build.motor === 'feetech' ? 'FeeTech' : 'Dynamixel'} motor output.`, 'Wait for “Scanning for motor …” before introducing the top-right palm-side motor, ID 17.', ...(build.motor === 'feetech' ? ['Power the board OFF while making each motor connection, then turn it back ON to configure. Never hot-plug a FeeTech motor.'] : [])]
    case 'p115': return build.motor==='feetech' ? [step.instructions[0], 'Power OFF, connect the next motor with its plug correctly oriented, then power ON. Wait for detection before adding another. Never hot-plug FeeTech motors.', ...step.instructions.slice(2)] : step.instructions
    case 'p117': return build.motor === 'feetech' ? ['For each motor, switch the board off, add the next motor with the correctly oriented cable, then power on.', 'Wait until the configuration tool finds the current motor before adding another. Follow the descending 17 → 1 ID order.', 'Build columns of four motors with direct cables; do not fit Dynamixel connector PCBs.'] : step.instructions
    case 'p139': return ['Work through every mechanical check below before tensioning. Reopen the linked assembly step if something needs correcting.', 'Correct any binding, misplaced skin, loose knot or crossed tendon now. Calibration cannot fix a mechanical assembly problem.']
    case 'p141': return ['Return to Setup and open Full setup. Follow the tensioning prompts beside the live controls, then complete calibration there.', 'Keep the hand supported and its joints clear throughout the operation. Return to the joint check in this guide after Setup finishes.']
    case 'p142': return ['Check that the supplied aluminum ISO 9409-1-50-4-M6 connector plate matches the arm flange. Confirm the mounting hardware listed below before starting; the hand is controlled independently through USB-C.', 'With the arm and hand unpowered, secure the plate to the flange using four M6×8 low-profile screws that match the supplied plate. Fit the two matching threaded rods. Use the arm manufacturer’s tightening specifications.', 'Remove the hull covers to access the mounting points. Support the rear cover with its control board; keep its connected cables slack.', 'Align the hand with both rods and slide it onto the adapter. Secure it with the supplied M3×14 screws at the mounting points confirmed for your kit. Do not use the older picture alone to choose the screw count.', 'Refit the covers without trapping wires. Route the power and USB-C cables along the arm, leaving enough slack for the intended arm motion. Check that the hand is secure and the cables are clear before powering up.']
    default: return step.instructions
  }
}
export const FINAL_CHECKS = [
  'Every bearing is seated; joints rotate without sideways play.',
  'Joint movement is smooth, without abrupt friction or binding.',
  'Each fitted skin is seated correctly; no skin rubs a joint or leaves an unintended gap.',
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
  p46:[{id:'thumb-dp',label:'Thumb DP preparation'},{id:'thumb-pp',label:'Thumb PP preparation'}],
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
function stepNote(step: AssemblyStep, build: Build) {
  if (step.id === 'p142') return 'Mounting kit details still need confirmation: the written mounting instructions specify 3 M3×14 securing screws, while the older illustration shows 4. The current adapter model also has 4 radial holes. The older picture specifies M5×100 rods, but the current rod geometry is 80 mm long; its thread specification is not confirmed. Match the physical mounting kit before assembly.'
  if (step.id === 'p93') return 'Check cable clearance at the fan blades and screw holes before tightening.'
  if(step.id==='p54')return 'The thumb AP route is under review: the feedback reports a reversed route but does not specify which channels change. Confirm the corrected hole assignment before using the diagram to assemble this joint.'
  if (['p145','p147','p148'].includes(step.id)) return build.version==='touch'?'Optional: cast skins only if you are making your own. These are Touch mold and skin references. The supplied instructions do not establish the Touch material specification, batch masses or demolding time; confirm them before mixing.':build.version==='full'?'Full-specific skin molds and casting quantities are not verified here. Confirm the matching mold set and material procedure before casting.':'Optional: cast skins only if you are making your own. The recipe and quantities are for Base skins. Confirm the actual silicone product and its demolding schedule before mixing.'
  if (step.id === 'p123') return 'The numbered map identifies each joint’s two tendons and motor. The bottom-versus-top assignment is not yet specified for every configuration. Confirm that assignment before cutting or anchoring a tendon; checking the joint pair alone does not establish the winding direction.'
  if (step.id === 'p126') return 'Seat each bearing on the bench with the loose spool supported. Do not hammer or press on the assembled tower.'
  if (step.id === 'p97') return build.motor === 'feetech' ? 'Power off before every cable change. Reversed connectors permanently damage FeeTech motors.' : undefined
  if (step.id === 'p117') return build.motor === 'feetech' ? step.note : undefined
  if (step.id === 'p141') return 'Tensioning and calibration stay in Setup so the existing motor controls and safety checks remain available.'
  return step.note
}

export const note = stepNote

export type FlashingMethod = 'console' | 'firmware'
const DP_PIN_INSTRUCTION='Add the upper Ø2×6 mm pin. Keep the two DP tendons between the upper and lower pins, ensure that the DP flexor tendon is more in the middle of the part and press the pin fully into its seat. Gently pull each DP end to check that it runs freely.'
export const BASE_STEP_REDIRECTS:Record<string,string>={'thumb-tendons':'thumb-parts',p141:'p139','motor-check':'p139'}
export function buildSteps(build: Build): AssemblyStep[] {
  const selected = STEPS.filter(s => !s.chapter.startsWith('Flashing') && !(build.version==='base'&&BASE_STEP_REDIRECTS[s.id]) && !(build.version==='touch'&&['finishing-pp','thumb-skins'].includes(s.id)) && !s.id.startsWith('touch-')).map(s => {
    if(build.version==='base'){
      if(s.id==='p31')return {...s,title:'Prepare the printed parts for the index'}
      if(s.id==='p26')return {...s,check:'All ten lengths have reinforced double stoppers 10 mm apart (±5 mm).'}
      if(s.id==='thumb-pp')return {...s,check:'The PP tendon is seated and tucked, and the middle and lower pins are fitted.'}
      if(s.id==='p139')return {...s,chapter:'Check the hand',title:'Check the hand'}
    }
    if (build.motor === 'feetech' && s.id === 'p98') return {...s,title:'Fit the direct motor cables',check:'The FeeTech cables are correctly oriented and seated.'}
    if (s.id === 'p101') return {...s,check:'I have identified the power, USB and correct motor connectors.'}
    if (build.version==='touch'&&['pp-ready','thumb-pp-ready'].includes(s.id))return {...s,title:'Fit the PP bearings',check:'Both PP bearings are seated; all skins remain off for cable installation.'}
    if (s.id === 'p110') return {...s,title:`Prepare the ${build.version === 'full' ? 'Full' : 'Touch'} connector board`}
    return s
  })
  if(build.version!=='touch')return selected
  const fingers=TOUCH_STEPS.filter(s=>['Touch sensors','Touch skins'].includes(s.chapter))
  const electronics=TOUCH_STEPS.filter(s=>!['Touch sensors','Touch skins'].includes(s.chapter))
  return selected.flatMap(s=>s.id==='thumb-test'?[s,...fingers]:s.id==='p139'?[...electronics,s]:[s])
}
