import type { Build, Figure } from './buildContent'
import type {JointPreparation} from './cadJointPreparation'
import type {WristPreparation} from './cadWristPreparation'
import type {AnchorPreparation} from './cadAnchorPreparation'
import type {ApAnchorPreparation} from './cadApAnchorPreparation'

export type Recipe = {
  step: string; file: string; caption: string; instruction: number
  scene?: 'motion' | 'detail'; position?: number; view?: [number, number, number]
  parts?: string[]; owner?: string; explode?: number; liners?: 'carpals' | 'wrist'
  labelParts?: string[]; motorSpecific?: boolean; routeFace?: 'entry' | 'exit'; tubePull?: 0 | 1 | 2
  routingReference?: 'wrist-groups' | 'carpal-rows' | 'pp-pair'
  jointPreparation?: JointPreparation
  wristPreparation?: WristPreparation
  anchorPreparation?: AnchorPreparation
  apAnchorPreparation?: ApAnchorPreparation
  thumbAnchor?: boolean
  tpAnchorPreparation?: 'thread' | 'reinforce'
  thumbFinishing?: 'pins' | 'bearings'
  wristCrossing?: boolean
  spoolPreparation?: 'overview' | 'thread'
  armMount?: 'adapter' | 'covers' | 'alignment'
  towerWiring?: boolean
}
const carpals = ['Carpals', 'Touch carpals', 'Carpal core']
export const CAD_ILLUSTRATIONS: Recipe[] = [
  {step:'p93',file:'panel-096-3',caption:'Tower cable routing · motor lead through the upper slot, both fan leads through the lower slot',instruction:1,towerWiring:true,motorSpecific:true},
  {step:'p142',file:'mount-1',caption:'Adapter plate and two mounting rods · rods lifted to show their mounting holes',instruction:2,armMount:'adapter',motorSpecific:true},
  {step:'p142',file:'mount-3',caption:'Tower covers · support the rear hull and board without pulling on their cables',instruction:3,armMount:'covers',motorSpecific:true},
  {step:'p142',file:'mount-2',caption:'Tower-to-adapter alignment · drive components hidden to reveal the two rods',instruction:4,armMount:'alignment',motorSpecific:true},
  {step:'p123',file:'panel-124-1',caption:'Wrist outlets above the bottom spools · keep each tendon identified until its spool is confirmed',instruction:1,spoolPreparation:'overview',motorSpecific:true},
  {step:'p123',file:'panel-124-2',caption:'Bottom spool · pull about 8 cm through the anchor channel before tying the stopper',instruction:1,spoolPreparation:'thread',motorSpecific:true},
  {step:'p77',file:'panel-079-1',caption:'Side view through the carpals and wrist · each tendon row crosses to the opposite wrist side',instruction:2,wristCrossing:true},
  {step:'p136',file:'panel-138-1',caption:'Rear hull · inner face of the cover for your selected build',instruction:3,parts:['Rear hull cover'],view:[.25,.15,-1]},
  {step:'p136',file:'panel-138-4',caption:'OH board · seated face down in the rear hull',instruction:3,parts:['Rear hull cover','OH control board'],labelParts:['OH control board'],view:[.25,.15,-1]},
  {step:'p70',file:'panel-072-1',caption:'Carpal underside · identify the 16 palmar and 16 dorsal tendons before threading the wrist',instruction:1,routingReference:'carpal-rows'},
  {step:'p62',file:'panel-063-1',caption:'TP · the six passing tendons run between the two 2 × 30 guide pins',instruction:1,thumbFinishing:'pins'},
  {step:'p62',file:'panel-063-2',caption:'Thumb joint · seat both 4 × 8 × 3 mm bearings fully',instruction:2,thumbFinishing:'bearings'},
  {step:'p122',file:'panel-092-1',caption:'Wrist drive · align the pulley, its pin and bearing with the motor carrier',instruction:2,scene:'motion',position:.4,motorSpecific:true},
  {step:'p122',file:'panel-092-2',caption:'Wrist drive · engage the motor carrier before joining the wrist to the tower',instruction:2,scene:'motion',position:.5,motorSpecific:true},
  {step:'p56',file:'panel-058-1',caption:'TP · thread both 75 cm anchors from outside to inside; pull 20 cm through',instruction:1,tpAnchorPreparation:'thread'},
  {step:'p56',file:'panel-058-2',caption:'TP · reinforce each Ashley stopper with three single knots around the stopper itself',instruction:2,tpAnchorPreparation:'reinforce'},
  {step:'p49',file:'panel-051-1',caption:'Thumb AP · thread from outside to inside; pull 20 cm through before tying',instruction:2,apAnchorPreparation:'thread',thumbAnchor:true},
  {step:'p49',file:'panel-051-2',caption:'Thumb AP · reinforce each Ashley stopper with three single knots around it',instruction:2,apAnchorPreparation:'reinforce',thumbAnchor:true},
  {step:'p52',file:'panel-053-1',caption:'Pull the long tendon firmly to settle the thumb stopper in its housing',instruction:1,apAnchorPreparation:'settle',thumbAnchor:true},
  {step:'p52',file:'panel-053-3',caption:'Pull the settled stopper out, then trim 5 mm after the knot',instruction:2,apAnchorPreparation:'trim',thumbAnchor:true},
  {step:'p52',file:'panel-053-5',caption:'Reseat and tuck the entire tail inside; repeat for the second thumb anchor',instruction:3,apAnchorPreparation:'tuck',thumbAnchor:true},
  {step:'p37',file:'panel-039-1',caption:'AP · pass the tendon from outside to inside and pull 20 cm through',instruction:1,apAnchorPreparation:'thread'},
  {step:'p37',file:'panel-039-2',caption:'Reinforce the Ashley stopper with one single knot around the stopper itself',instruction:2,apAnchorPreparation:'reinforce'},
  {step:'p37',file:'panel-041-1',caption:'Pull firmly to settle the reinforced stopper in its housing',instruction:3,apAnchorPreparation:'settle'},
  {step:'p37',file:'panel-041-3',caption:'Pull it back out, then trim 5 mm after the knot',instruction:3,apAnchorPreparation:'trim'},
  {step:'p37',file:'panel-041-5',caption:'Reseat the stopper and tuck the entire tail inside; repeat on the other side',instruction:3,apAnchorPreparation:'tuck'},
  {step:'prepare-pp',file:'panel-034-1',caption:'PP · feed both ends of the prepared double-knot tendon through its side housing',instruction:1,anchorPreparation:'pp-feed'},
  {step:'prepare-pp',file:'panel-034-2',caption:'PP · seat both reinforced stoppers and tuck the connecting loop fully inside',instruction:1,anchorPreparation:'pp-tuck'},
  {step:'p29',file:'panel-030-1',caption:'Feed both free ends from the central knot housing toward the joint',instruction:1,anchorPreparation:'dp-feed'},
  {step:'p29',file:'panel-030-2',caption:'Pull both ends to seat the two reinforced stoppers inside the housing',instruction:2,anchorPreparation:'dp-seat'},
  {step:'p29',file:'panel-030-3',caption:'Tuck the connecting loop fully inside; leave no loop outside the DP',instruction:3,anchorPreparation:'dp-tuck'},
  {step:'p75',file:'panel-076-3',caption:'Cover both exposed screw threads with PTFE; trim the sleeves to fit',instruction:4,wristPreparation:'screw-sleeves'},
  {step:'p89',file:'panel-089-1',caption:'Place the belt around the carpal pulley and between the two PTFE sleeves',instruction:1,wristPreparation:'belt-position'},
  {step:'p93',file:'panel-096-1',caption:'Fit the two M3 nuts in the highlighted fan-mounting pockets',instruction:1,wristPreparation:'fan-mounts',motorSpecific:true},
  {step:'p93',file:'panel-095-1',caption:'Fit both fans and secure the two fixing points; keep their wires clear',instruction:2,wristPreparation:'fans-fitted',motorSpecific:true},
  {step:'p31',file:'panel-032-1',caption:'PP underside · remove support remnants and burrs from the highlighted profile',instruction:1,jointPreparation:'pp-underside'},
  {step:'p31',file:'panel-032-3',caption:'Finished PP · keep the curved profile intact while removing rough print marks',instruction:2,jointPreparation:'pp-finish'},
  {step:'p35',file:'panel-036-1',caption:'Insert the upper 2 × 6 pin; keep the two DP tendons between the pins',instruction:1,jointPreparation:'upper-pin'},
  {step:'p35',file:'panel-036-2',caption:'Pins seated · inspect the two parallel DP tendon paths before pulling each end',instruction:1,jointPreparation:'pin-clearance'},
  {step:'p77',file:'route-p77-groups',caption:'Carpal underside · send each row to the opposite wrist side',instruction:2,routingReference:'wrist-groups'},
  {step:'p35',file:'route-p35-pair',caption:'Index PP · identify DP flex and DP ext at their exits',instruction:3,routingReference:'pp-pair'},
  {step:'p15',file:'panel-015-1',caption:'PTFE in the two wide AP channels · entry',instruction:1,routeFace:'entry'},
  {step:'p15',file:'panel-015-2',caption:'AP liners · leave about 1 mm at both ends',instruction:2,routeFace:'exit'},
  ...([0,1,2] as const).map(tubePull=>({step:'p20',file:`panel-021-${tubePull+1}`,caption:['Pass the free tendon through the tube','Feed the tendon through the AP channel','Pull the tendon to draw the tube through'][tubePull],instruction:tubePull===0?1:2,tubePull})),
  ...(['p42','p54','p59','p62','p64'] as const).flatMap(step=>(['entry','exit'] as const).map(routeFace=>({step,file:`route-${step}-${routeFace}`,caption:'Match the highlighted tendon',instruction:1,routeFace}))),
  {step:'p16',file:'panel-017-1',caption:'Carpals · close view of the 32 lined exits',instruction:1,parts:carpals,liners:'carpals',view:[0,-1,.35]},
  {step:'p16',file:'panel-017-2',caption:'Carpals · liners enter each finger seat',instruction:1,parts:carpals,liners:'carpals',view:[0,1,-.4]},
  {step:'p16',file:'panel-017-3',caption:'Wrist · liner entrances',instruction:1,parts:['Wrist frame'],liners:'wrist',view:[.6,.8,-1]},
  {step:'p16',file:'panel-017-4',caption:'Wrist · all 32 liner outlets',instruction:1,parts:['Wrist frame'],liners:'wrist',view:[0,-1,0]},
  {step:'p16',file:'panel-017-5',caption:'Wrist · lined channels from above',instruction:1,parts:['Wrist frame'],liners:'wrist',view:[0,1,.3]},
  {step:'p29',file:'panel-030-4',caption:'DP · seat a bearing on each side',instruction:4,parts:['Index DP'],owner:'Index DP',explode:12,labelParts:['Bearing · 4 × 8 × 3']},
  {step:'prepare-pp',file:'panel-034-3',caption:'PP · middle 2 × 8 pin and lower 2 × 6 pin',instruction:2,parts:['Index PP'],owner:'Index PP',explode:12,labelParts:['Pin · 2 × 8','Pin · 2 × 6']},
  {step:'p33',file:'panel-034-4',caption:'Keep the DP tendons aligned with the PP channels',instruction:1,scene:'motion',position:0},
  {step:'p33',file:'panel-034-5',caption:'Take up slack while closing the joint',instruction:1,scene:'motion',position:.55},
  {step:'p33',file:'panel-034-6',caption:'DP and PP · bearings fully seated',instruction:2,scene:'motion',position:1},
  {step:'p46',file:'panel-048-1',caption:'Thumb DP and PP · skins and bearings fitted',instruction:1,scene:'detail',position:0},
  {step:'p62',file:'panel-063-3',caption:'Thumb · fully seated joint and bearings',instruction:2,scene:'motion',position:1},
  {step:'p68',file:'panel-069-1',caption:'Thumb · align all eight ends before seating',instruction:1,scene:'motion',position:0},
  {step:'p68',file:'panel-069-2',caption:'Thumb · seat the bearings in the carpals',instruction:2,scene:'motion',position:1},
  {step:'p75',file:'panel-076-1',caption:'Fit the screws and washers from outside into the seated square nuts',instruction:3,parts:['Wrist frame','M4 × 20 socket screw','M4 washer'],explode:18,labelParts:['M4 × 20 socket screw','M4 washer'],view:[1,.65,-1]},
  {step:'p75',file:'panel-076-2',caption:'Inside view · insert both square nuts from inside the wrist into their pockets',instruction:2,wristPreparation:'square-nuts'},
  {step:'p93',file:'panel-096-2',caption:'Inside view · insert all three M4 nuts from inside the tower into the top pockets',instruction:3,wristPreparation:'tower-nuts',motorSpecific:true},
  {step:'p122',file:'panel-122-1',caption:'Seat the wrist and secure all three M4 × 10 screws',instruction:4,scene:'motion',position:.84,motorSpecific:true},
  {step:'p122',file:'panel-091-1',caption:'Wrist pulley · 4 × 10 pin and bearing',instruction:2,parts:['Wrist pulley','Pin · 4 × 10'],owner:'wrist-pulley',explode:15,labelParts:['Pin · 4 × 10','Bearing · 4 × 8 × 3'],view:[1,.4,-1],motorSpecific:true},
  {step:'p122',file:'panel-091-2',caption:'Wrist motor · fit the carrier and four M2 × 8 screws',instruction:1,parts:['Dynamixel XC430 wrist motor','Wrist motor adapter','M2 × 8 socket screw'],explode:18,labelParts:['Wrist motor adapter','M2 × 8 socket screw'],view:[1,.4,-1],motorSpecific:true},
  {step:'p122',file:'panel-092-3',caption:'Wrist and tower · secured assembly',instruction:4,scene:'motion',position:1,motorSpecific:true},
  {step:'p123',file:'panel-125-1',caption:'Bottom spool · three turns and the stopper at the anchor channel',instruction:2,scene:'motion',position:.7,motorSpecific:true},
  {step:'p123',file:'panel-125-2',caption:'Bottom spool · the 5 mm tail returns into the same channel',instruction:3,scene:'motion',position:1,motorSpecific:true},
  {step:'p126',file:'panel-126-1',caption:'Top spool · bearing and securing screw',instruction:1,scene:'motion',position:.84,motorSpecific:true},
  {step:'p126',file:'panel-126-2',caption:'Top spool · assembled antagonist pair',instruction:1,scene:'motion',position:1,motorSpecific:true},
  {step:'p132',file:'panel-134-1',caption:'Hull cover · check every magnet’s mating polarity',instruction:1,parts:['Hull cover','Hull magnet'],owner:'hull',explode:0,labelParts:['Hull magnet'],view:[.5,.3,1]},
]

export function replaceCadFigures(items:Figure[],build:Build):Figure[] {
  if(build.version==='full')return items
  const key=`${build.version}-${build.side}-dynamixel`
  return items.map(item=>{
    const recipe=CAD_ILLUSTRATIONS.find(r=>item.src.endsWith(`/${r.file}.png`))
    if(!recipe||(recipe.motorSpecific&&build.motor!=='dynamixel'))return item
    return {...item,src:`./assembly/renders/${key}/${recipe.file}.webp`,caption:recipe.caption,instruction:recipe.instruction,photo:{src:item.src,caption:item.caption}}
  })
}

