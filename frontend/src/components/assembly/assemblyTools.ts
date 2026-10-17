import type {Build} from './buildContent'
import type {AssemblyStep} from './guide'

const TOOLS = {
  measure: 'Ruler or tape measure · millimetres',
  cut: 'Sharp scissors or flush cutters · tendon and PTFE',
  driver: 'Hand screwdriver / hex keys with bits matching the supplied screws',
  tuck: 'Small blunt tool · tuck knots and tails without piercing the cord',
  finish: 'Small file or fine sandpaper',
  brush: 'Soft brush · remove loose print debris',
  seat: 'Small hammer and flat-ended bearing seating tool · only if needed',
  support: 'Firm support block · support the part beside its bearing pocket',
  cloth: 'Wiping cloth · remove excess glue',
  computer: 'Computer with ORCA UI and orca_core installed',
  flash: 'J-Link programmer and matching Tag-Connect probe',
  console: 'Computer with ORCA Console and Bench Helper',
  firmware: 'Computer with the orca_firmware flashing tools',
  paxini: 'Windows computer with Paxini software and Paxini adapter',
  labels: 'Removable labels and a pen',
  wire: 'Fine wire cutters',
  marker: 'Black permanent marker',
  scale: 'Digital scale · weigh silicone components separately',
  mixing: 'Separate cups and mixing sticks for A and B',
  gloves: 'Gloves suitable for the silicone materials',
} as const
type Tool = keyof typeof TOOLS
const bearing:Tool[] = ['support','seat']

// Every step has an explicit entry, including operations done entirely by hand.
export const STEP_TOOLS:Record<string,Tool[]> = {
  p1:[],p6:['cut'],p23:[],p13:['measure'],p15:['measure','cut'],
  p18:['brush'],p16:['measure','cut'],p20:['cut'],p22:['wire'],
  p26:['measure','cut'],p29:['tuck',...bearing],p31:['finish','brush'],
  'prepare-pp':['tuck'],p33:[...bearing],p35:[],
  'finishing-pp':[...bearing],p37:['measure','cut','tuck'],
  p42:[...bearing],p45:['measure','cut','tuck','finish','brush',...bearing],
  p46:['tuck','finish','brush',...bearing],p49:['measure','cut'],
  p52:['measure','cut','tuck'],p54:[...bearing],p56:['measure','cut','tuck'],
  p59:[],p62:[...bearing],p64:[...bearing],p68:[...bearing],p70:[],
  p73:[...bearing],p75:['driver','measure','cut'],p77:[],p80:[],p83:['labels'],p89:[],
  p93:['driver'],p98:[],p97:[],p101:[],p105:['console','flash'],p110:['console','flash'],
  p150:['firmware','flash'],p154:['firmware','flash'],p99:['driver'],
  p112:['computer'],p115:['computer','labels'],p117:['computer'],p122:['driver',...bearing],
  p123:['measure','cut','tuck','labels'],p126:['measure','cut','tuck','driver',...bearing],
  p127:['driver'],p129:['cloth'],p132:['cloth'],p135:[],p136:['driver'],
  p139:[],p141:['computer'],'motor-check':['computer'],p142:['driver'],
  p145:['scale','mixing','gloves'],p147:['scale'],p148:['scale','mixing','gloves'],
  'touch-parts':['measure','wire','driver','marker','paxini'],
  'touch-ids':['paxini','labels'],'touch-wrap-short':['measure','wire'],
  'touch-wrap-long':['measure','wire'],'touch-paint':['marker'],
  'touch-route':[],'touch-connect':[],'touch-mount':['driver'],
  'touch-board-mount':['driver'],'touch-board-connect':[],'touch-board-link':[],'touch-test':['computer'],
}

export function stepTools(step:AssemblyStep):string[] {
  return (STEP_TOOLS[step.id]??[]).map(id=>TOOLS[id])
}

export function buildTools(steps:AssemblyStep[],build:Build) {
  const core=steps.filter(s=>!s.chapter.startsWith('Appendix'))
  const ids=new Set(core.flatMap(s=>STEP_TOOLS[s.id]??[]))
  return {
    assembly:([...ids] as Tool[]).filter(id=>!['computer','flash','console','firmware','paxini'].includes(id)).map(id=>TOOLS[id]),
    setup:([...ids] as Tool[]).filter(id=>['computer','flash','console','firmware','paxini'].includes(id)).map(id=>TOOLS[id]),
    optional:[`Making ${build.version==='base'?'Base':build.version==='touch'?'Touch':'Full'} skins: digital scale, separate cups and sticks, suitable gloves.`,'Arm mounting: drivers and any tightening tool specified by your robot arm manufacturer.'],
  }
}

const TOOL_ONLY = /^(?:Ruler|Cutters|Wire cutters|Black permanent marker|Labels or marker|Paxini adapter|ORCA UI|Allen key|Hex keys|File|Soft brush|Small blunt tool|Scale|Cups|Separate mixing sticks|Gloves|Wiping cloth|Hand screwdriver|Windows laptop|Computer with|J-Link|Tag-Connect)/i
export const partsOnly=(items:string[])=>items.filter(item=>!TOOL_ONLY.test(item))
