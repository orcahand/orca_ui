import touchRight from '../../../public/assembly/parts/touch-right-dynamixel/inventory.json'
import touchLeft from '../../../public/assembly/parts/touch-left-dynamixel/inventory.json'
import type { Build } from './buildContent'
export const AREAS = ['Thumb','Fingers','Carpals','Wrist','Tower'] as const
export type Area = typeof AREAS[number]
export type Part = {id:string;label:string;category:string;count:number;nodes:string[];areas:Record<string,string[]>;thumbnail:string}
export type Inventory = {key:string;parts:Part[];instanceCount:number}
export function groupStandardParts(parts:Part[]):Part[] {
  const grouped=new Map<string,Part>()
  for(const part of parts){
    const key=`${part.category}:${part.label}`
    const existing=grouped.get(key)
    if(!existing){grouped.set(key,{...part,nodes:[...part.nodes],areas:Object.fromEntries(Object.entries(part.areas).map(([area,nodes])=>[area,[...nodes]]))});continue}
    existing.count+=part.count
    existing.nodes.push(...part.nodes)
    for(const [area,nodes] of Object.entries(part.areas))existing.areas[area]=[...(existing.areas[area]??[]),...nodes]
  }
  return [...grouped.values()]
}
// These are CAD solids within the spool assembly, not separately supplied parts.
export const isInternalSpoolPart=(part:Part)=>['Spool ORCA insert','Top spool / tensioner'].includes(part.label)
export function explorerParts(parts:Part[]):Part[] {
  return groupStandardParts(parts.map(part=>({...part,areas:Object.fromEntries(
    [...new Set(Object.keys(part.areas).map(area=>area==='Thumb'?'Fingers':area))]
      .map(area=>[area,area==='Fingers'?[...(part.areas.Fingers??[]),...(part.areas.Thumb??[])]:part.areas[area]])
  )})))
}
export type Supply = {id:string;label:string;quantity:string;areas:Area[];kind:'tube'|'cord'|'cable'|'equipment'|'hardware';note:string; partLabel?:string; optional?:boolean; image?:string; files?:{label:string;src:string}[]}
export function supplementalParts(part:Part,stock:Supply[],area?:string){return stock.filter(s=>s.partLabel===part.label&&(!area||s.areas.includes(area as Area)))}
export function partQuantity(part:Part,stock:Supply[],area?:string){return (area?part.areas[area]?.length??0:part.count)+supplementalParts(part,stock,area).filter(s=>!s.optional).reduce((n,s)=>n+Number(s.quantity),0)}
export function partQuantityLabel(part:Part,stock:Supply[],area?:string){
  const optional=supplementalParts(part,stock,area).filter(s=>s.optional)
  const suffix=optional.length?optional.some(s=>!Number.isFinite(Number(s.quantity)))?' + optional kit (confirm count)':` + ${optional.reduce((n,s)=>n+Number(s.quantity),0)} optional`:''
  return `${partQuantity(part,stock,area)}${suffix}`
}
export const supplyQuantity=(s:Supply)=>`${s.quantity}${s.optional?' · optional':''}`
export function supplies(build:Build):Supply[] {
  const touchInventory=build.side==='left'?touchLeft:touchRight
  const touchScrews:Supply[]=build.version==='touch'?[
    {length:3,area:'Fingers' as const,total:8}, {length:4,area:'Fingers' as const,total:8},
    {length:4,area:'Thumb' as const,total:2}, {length:6,area:'Thumb' as const,total:2},
    {length:6,area:'Carpals' as const,total:2},
  ].flatMap(({length,area,total})=>{
    const label=`M1.4 × ${length} cheese-head screw`
    const represented=touchInventory.parts.filter(p=>p.label===label).reduce((n,p)=>n+(p.areas[area]?.length??0),0)
    return total>represented?[{id:`touch-screw-${length}-${area}`,label,partLabel:label,quantity:String(total-represented),areas:[area],kind:'hardware' as const,note:`${total} required in ${area.toLowerCase()} by the Touch instructions; ${represented} already represented in this CAD. Board screws are self-tapping. The initial kit list and CAD differ; see Touch kit review notes.`}]:[]
  }):[]
  const list:Supply[] = [
    ...touchScrews,
    {id:`carpal-cover-${build.side}`,label:'Carpal cover',quantity:'1',areas:['Carpals'],kind:'hardware',note:'Separate printed carpal cover; omitted from the complete CAD assembly export.',image:`./assembly/supplies/carpal-cover-${build.side}.svg`,files:[{label:'STL',src:`./assembly/supplies/carpal-cover-${build.side}.stl`}]},
    {id:'cord-2m',label:'Tendon · 2m',quantity:'10',areas:['Fingers'],kind:'cord',note:'Ten 2 m lengths; the same tendons continue through carpals, wrist and tower.',image:'./assembly/supplies/cord.svg'},
    {id:'cord-75cm',label:'Tendon · 75cm',quantity:'12',areas:['Fingers'],kind:'cord',note:'Twelve 75 cm lengths; the same tendons continue through carpals, wrist and tower.',image:'./assembly/supplies/cord.svg'},
    {id:'ptfe',label:'AP PTFE liner · OD 1.5 / ID 0.9mm · 5–6mm',quantity:'8',areas:['Fingers'],kind:'tube',note:'Two liners per finger AP.',image:'./assembly/supplies/ptfe.svg'},
    {id:'ptfe-thumb',label:'Thumb PTFE liner · OD 1.5 / ID 0.9mm · 18mm',quantity:'2',areas:['Fingers'],kind:'tube',note:'Two thumb AP liners.',image:'./assembly/supplies/ptfe.svg'},
    {id:'ptfe-carpals',label:'Carpal PTFE liner · OD 1.5 / ID 0.9mm · 60mm max',quantity:'32',areas:['Carpals'],kind:'tube',note:'60mm is the longest carpal liner.',image:'./assembly/supplies/ptfe.svg'},
    {id:'ptfe-wrist',label:'Wrist PTFE liner · OD 1.5 / ID 0.9mm',quantity:'32',areas:['Wrist'],kind:'tube',note:'One liner per wrist channel.',image:'./assembly/supplies/ptfe.svg'},
    {id:'sleeves',label:'PTFE screw sleeve · OD 4 / ID 2.7 mm',quantity:'2 cut pieces',areas:['Wrist'],kind:'tube',note:'Sleeves over the two wrist screw threads. Trim to fit at the wrist preparation step.'},
    ...(build.motor==='dynamixel'?[
      {id:'motor-long',label:'3-pin board-to-motor cable · 180 mm',quantity:'1',areas:['Tower'] as Area[],kind:'cable' as const,note:'From the OH board through the upper tower slot.'},
      {id:'motor-links',label:'3-pin column-link cables',quantity:'3',areas:['Tower'] as Area[],kind:'cable' as const,note:'Two bottom links (14 → 13 and 6 → 5) and one top link (10 → 9). The bottom links use 30–50 mm cables; match the top link to the routed assembly.'},
      {id:'wrist-lead',label:'3-pin wrist motor cable',quantity:'1',areas:['Tower'] as Area[],kind:'cable' as const,note:'From the last spool motor to the wrist motor. Check the required length against your routed assembly.'},
    ]:[{id:'feetech-harness',label:'FeeTech motor cable harness',quantity:'1 matching set',areas:['Tower'] as Area[],kind:'cable' as const,note:'Short neighbor links, long bottom links and the two thin-to-thick adapter leads shown in the motor wiring steps.'}]),
    {id:'chain-a',label:'Motor-chain cable cover A',quantity:'2',areas:['Tower'],kind:'hardware',note:'Fit the A covers over the matching motor-chain cable paths.'},
    {id:'chain-b',label:'Motor-chain cable cover B',quantity:'2',areas:['Tower'],kind:'hardware',note:'Fit the B covers over the matching motor-chain cable paths.'},
    {id:'board-cover',label:'OH board cable cover',quantity:'1',areas:['Tower'],kind:'hardware',note:'Fits over the routed board cables inside the rear hull.'},
    {id:'board-nuts',label:'M3 hex nut',partLabel:'M3 hex nut',quantity:'2',areas:['Tower'],kind:'hardware',note:'Includes 2 nuts for the rear-hull board mount.',image:'./assembly/parts/base-right-dynamixel/08f5283ed3.png'},
    {id:'board-screw',label:'M3 × 14 socket screw',partLabel:'M3 × 14 socket screw',quantity:'1',areas:['Tower'],kind:'hardware',note:'Includes 1 screw for the rear-hull board mount.',image:'./assembly/parts/base-right-dynamixel/f1efd004fd.png'},
    {id:'board-cover-screw',label:'M2 × 8 socket screw',partLabel:'M2 × 8 socket screw',quantity:'1',areas:['Tower'],kind:'hardware',note:'Includes 1 screw for the OH board cable cover.',image:'./assembly/parts/base-right-dynamixel/d1b7310480.png'},
    {id:'arm-flange-screws',label:'M6 × 8 low-profile mounting screw',partLabel:'M6 × 8 low-profile mounting screw',quantity:'4',optional:true,areas:['Tower'],kind:'hardware',note:'Only for the optional arm adapter. Match the screw head to the supplied plate and arm flange.',image:'./assembly/supplies/mount-screw.svg'},
    {id:'arm-hand-screws',label:'M3 × 14 socket screw',partLabel:'M3 × 14 socket screw',quantity:'unconfirmed',optional:true,areas:['Tower'],kind:'hardware',note:'Optional arm mounting needs additional M3×14 screws. The written instructions say 3 and the older illustration shows 4; confirm the supplied kit before purchasing or fitting them.',image:'./assembly/parts/base-right-dynamixel/f1efd004fd.png'},
    {id:'fan-leads',label:'Fan leads',quantity:'2 · with fans',areas:['Tower'],kind:'cable',note:'Included with the two fans; route through the lower tower slot.'},
    ...(build.version!=='base'?[
      {id:'board-lead',label:'4-wire connector-board cable',quantity:'1',areas:['Carpals','Tower'] as Area[],kind:'cable' as const,note:'Connects the OH board and the selected version’s connector board.'},
      ...(build.version==='touch'?[
        {id:'touch-short',label:'Touch sensor cable · 130 mm',quantity:'3',areas:['Thumb','Fingers','Carpals'] as Area[],kind:'cable' as const,note:'Three short cables. Finger allocation needs confirmation; the cable-wrapping step shows the short-cable dimensions.'},
        {id:'touch-long',label:'Touch sensor cable · 280 mm',quantity:'2',areas:['Thumb','Fingers','Carpals'] as Area[],kind:'cable' as const,note:'Two long cables. Confirm the finger allocation and wrap position before fixing the copper wrap.'},
        {id:'touch-wire',label:'Copper wrapping wire · Ø0.2 mm',quantity:'2.5 m + spare',areas:['Thumb','Fingers'] as Area[],kind:'cable' as const,note:'Approximately 50 cm per cable, five cables. Secure each end with a clove hitch.'},
      ]:[{id:'sensor-harness',label:'Full finger harness',quantity:'1 matching set',areas:['Thumb','Fingers','Carpals'] as Area[],kind:'cable' as const,note:'Use the harness supplied for the selected hand side and version; check connector lengths against the kit.'}]),
    ]:[]),
    {id:'power',label:'12 V power supply',quantity:'1',areas:['Tower'],kind:'equipment',note:'Power connection to the OH board.'},
    {id:'power-cable',label:'Power cable · 12V',quantity:'1',areas:['Tower'],kind:'cable',note:'Power supply to OH board.'},
    {id:'usb',label:'USB-C data cable',quantity:'1',areas:['Tower'],kind:'cable',note:'A data-capable cable for programming and controlling the hand.'},
    {id:'tools',label:'Assembly tools',quantity:'1 set',areas:[],kind:'equipment',note:'Metric hex bits 1.5 / 2.5 / 3mm, ruler, cutters, file or sandpaper, wiping cloth, and superglue for the magnets. Approximately 0.45 mm iron wire only if reused PTFE is blocked.'},
  ]
  const mapped=list.map(s=>({...s,areas:[...new Set(s.areas.map(area=>area==='Thumb'?'Fingers' as const:area))],image:s.image??(s.kind==='hardware'&&s.partLabel?.includes('cheese-head screw')?'./assembly/supplies/cheese-head-screw.svg':undefined)??`./assembly/supplies/${['chain-a','chain-b','board-cover'].includes(s.id)?s.id+'.png':(['cord','ptfe','sleeves','usb','power','tools'].includes(s.id)?s.id:'cable')+'.svg'}`,files:s.files??(['chain-a','chain-b','board-cover'].includes(s.id)?[{label:'STL',src:`./assembly/supplies/${s.id}.stl`}]:undefined)}))
  const grouped=new Map<string,Supply>()
  for(const supply of mapped){
    const key=supply.partLabel&&!supply.optional?`${supply.partLabel}:${supply.areas.join(',')}`:supply.id
    const existing=grouped.get(key)
    if(existing){existing.quantity=String(Number(existing.quantity)+Number(supply.quantity));existing.note+=` ${supply.note}`}
    else grouped.set(key,supply)
  }
  return [...grouped.values()]
}
export function areaSupplyQuantity(s:Supply,area?:Area) {
  if(s.id==='cord-2m'&&area==='Thumb')return '2'
  if(s.id==='cord-75cm'&&area==='Thumb')return '4'
  return s.quantity
}

export function partLabel(label:string) {
  return label.replace(/\s*×\s*/g,'×').replace(/\s+mm\b/g,'mm')
    .replace(/\b(M?\d+(?:\.\d+)?(?:×\d+(?:\.\d+)?)+)(?=\s|$)/g, '$1mm')
}

export function supplyLabel(s:Supply) {
  if(s.id==='sleeves')return 'PTFE sleeve · OD 4 / ID 2.7mm'
  if(s.id==='touch-wire')return 'Copper wire · Ø0.2mm · 2.5m'
  return partLabel(s.label)
}

export function quantityBadge(quantity:string) {
  const count=quantity.match(/^\d+(?:\.\d+)?/)
  return count?`${count[0]}×`:quantity==='unconfirmed'?'?×':'1×'
}

export const BOM_CATEGORIES=['3D printed parts','Mechanical components','Electronic components','Skins','Tendons & PTFE','Tools & supplies'] as const
export function bomCategory(part:Part|null,supply:Supply|null):typeof BOM_CATEGORIES[number] {
  if(part){
    if(part.category==='Skins')return 'Skins'
    if(/motor$|fan$|board|PCB|module/i.test(part.label)&&!part.label.includes('adapter'))return 'Electronic components'
    if(part.category==='Standard components'||/belt|Metal spool holder|Arm mounting adapter/i.test(part.label))return 'Mechanical components'
    return '3D printed parts'
  }
  if(supply){
    if(supply.kind==='tube'||supply.id.startsWith('cord-'))return 'Tendons & PTFE'
    if(supply.kind==='cable'||supply.id==='power'||supply.id==='touch-wire')return 'Electronic components'
    if(supply.files?.some(f=>f.label==='STL'))return '3D printed parts'
    if(supply.kind==='hardware')return supply.id==='oh-board'?'Electronic components':'Mechanical components'
  }
  return 'Tools & supplies'
}
