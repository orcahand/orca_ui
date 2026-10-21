import baseRight from '../../../public/assembly/parts/base-right-dynamixel/inventory.json'
import baseLeft from '../../../public/assembly/parts/base-left-dynamixel/inventory.json'
import touchRight from '../../../public/assembly/parts/touch-right-dynamixel/inventory.json'
import touchLeft from '../../../public/assembly/parts/touch-left-dynamixel/inventory.json'
import {supplies} from './assemblyParts'
import type {Build} from './buildContent'

type Image={src:string;label:string}
const normalize=(s:string)=>s.toLowerCase().replace(/(?<=\d)\s*[×x]\s*(?=\d)/g,'×').replace(/\s*mm\b/g,'').replace(/ø/g,'').replace(/\s+/g,' ').trim()
// Match the kit's named components to the same inventory thumbnails as the explorer.
export function stepPartImages(text:string,build:Build,step:string):Image[] {
  const inventory=build.version==='touch'?(build.side==='left'?touchLeft:touchRight):(build.side==='left'?baseLeft:baseRight)
  const stock=supplies(build),t=normalize(text),found:Image[]=[]
  const thumb=step.startsWith('thumb-')||['p46','p49','p54','p56','p59','p62','p68'].includes(step)||/thumb/.test(t)
  const allFingers=/5 ap|five|four|4 assembled|middle, ring|index, middle/.test(t)||['p13','p15','p45'].includes(step)
  const fingerMatches=(label:string)=>allFingers?(!step.startsWith('p45')||!label.startsWith('index')&&!label.startsWith('thumb')):label.startsWith(thumb?'thumb':'index')
  const addPart=(test:(label:string)=>boolean)=>inventory.parts.filter(p=>test(normalize(p.label))).forEach(p=>found.push({src:p.thumbnail,label:p.label}))
  const addSupply=(id:string)=>{const s=stock.find(s=>s.id===id);if(s?.image)found.push({src:s.image,label:s.label})}
  const dimensions=t.match(/\bm?\d+(?:\.\d+)?(?:×\d+(?:\.\d+)?)+/g)??[]
  if(/\b(bearings?|pins?|screws?|nuts?|washers?|magnets?)\b/.test(t)&&!/^prepared |^assembled |with | and |housing/.test(t)) {
    const type=t.match(/\b(bearing|pin|screw|nut|washer|magnet)/)![1]
    addPart(label=>label.includes(type)&&(dimensions.length?dimensions.some(d=>label.includes(d)):type==='nut'||type==='washer'?(!/\bm\d/.test(t)||label.includes(t.match(/\bm\d+/)![0])):true))
    if(!found.length)stock.filter(s=>normalize(s.label).includes(type)&&dimensions.some(d=>normalize(s.label).includes(d))).forEach(s=>addSupply(s.id))
  }
  if(!found.length){
    if(/\bptfe\b/.test(t)&&!/^(?:(?:prepared|printed|thumb) )*(?:carpals|wrist|dp|pp|ap|tp)\b/.test(t))addSupply(/sleeve/.test(t)?'sleeves':'ptfe')
    else if(/\b(tendon|tendons|cord)\b/.test(t)&&!/(\b(dp|pp|ap|tp)\b.*with|prepared (bare )?(thumb )?(dp|pp|ap)|assembled|hand|wrist|fingers|on installed)/.test(t))addSupply(/75\s*cm/.test(t)?'cord-75cm':'cord-2m')
    else {
      const segments=['dp','pp','ap','tp'].filter(s=>new RegExp(`\\b${s}\\b`).test(t))
      if(segments.length)addPart(label=>segments.some(s=>new RegExp(`\\b${s}\\b`).test(label))&&(/matching.*skin/.test(t)?label.includes('skin'):!label.includes('skin'))&&fingerMatches(label))
      if(/carpal|palm skin/.test(t))addPart(label=>/pulley/.test(t)?label==='carpal pulley':/palm skin/.test(t)?label==='palm skin':/core/.test(t)?label==='carpal core':label===(build.version==='touch'?'touch carpals':'carpals'))
      if(/wrist/.test(t)){if(/motor/.test(t)&&build.motor==='feetech')found.push({src:'./assembly/media/feetech-1.jpg',label:'FeeTech motor assembly'});else addPart(label=>label===(/motor/.test(t)?'dynamixel xc430 wrist motor':/pulley/.test(t)?'wrist pulley':'wrist frame'))}
      if(/\btower\b/.test(t))addPart(label=>label==='motor tower')
      if(/spool/.test(t)&&(!/motor/.test(t)||/bottom spools/.test(t)))addPart(label=>/holder/.test(t)?label==='metal spool holder':/top/.test(t)?label==='top spool / tensioner':label==='bottom spool')
      if(/ratchet/.test(t))addPart(label=>label==='ratchet')
      if(/\bfans?\b/.test(t))addPart(label=>/plate/.test(t)?label==='side plate':label==='cooling fan')
      if(/\bbelt\b/.test(t))addPart(label=>label.includes('gt2 belt'))
      if(/oh (board|control board)/.test(t))addPart(label=>label==='oh control board')
      if(/connector (board|pcbs?)/.test(t))addPart(label=>/motor/.test(t)?label==='motor connector pcb':label.includes('connector board'))
      if(/\bmotors?\b/.test(t)&&!/(cable|wrist|pcb|installed)/.test(t)&&build.motor==='dynamixel')addPart(label=>label==='dynamixel xc330 motor')
      if(/12 v|power supply/.test(t))addSupply('power')
      if(/usb/.test(t))addSupply('usb')
      if(/cable cover/.test(t)){if(/4 |chain/.test(t)){addSupply('chain-a');addSupply('chain-b')}else addSupply('board-cover')}
      else if(/cable|harness/.test(t)){if(/4-wire|four-wire/.test(t))addSupply('board-lead');else if(build.version==='touch'&&/130|280|sensor|wrapped|routed connector/.test(t)){if(!/280/.test(t)||/130/.test(t))addSupply('touch-short');if(!/130/.test(t)||/280/.test(t))addSupply('touch-long');}else if(!/usb/.test(t))addSupply(build.motor==='feetech'?'feetech-harness':/180/.test(t)?'motor-long':'motor-links')}
      if(/copper/.test(t))addSupply('touch-wire')
      if(/carpal cover/.test(t))addSupply(`carpal-cover-${build.side}`)
      if(/sensor/.test(t)&&build.version==='touch'&&!/cable/.test(t))addPart(label=>label.includes('touch module'))
      if(/iso 9409/.test(t))addPart(label=>label.includes('arm mounting adapter'))
      if(/molds?/.test(t))found.push({src:`./assembly/molds/${build.version==='touch'?'touch':'base'}-plate-2.png`,label:'Skin molds'})
      if(!found.length&&/finger|thumb|assembly|hand|middle, ring/.test(t))addPart(label=>/^(index|middle|ring|pinky|thumb) (dp|pp|ap|tp)$/.test(label)&&(/hand|mechanical assembly/.test(t)||fingerMatches(label)))
      if(!found.length&&/motors?/.test(t)&&build.motor==='feetech')found.push({src:'./assembly/media/feetech-1.jpg',label:'FeeTech motor assembly'})
    }
  }
  return [...new Map(found.map(image=>[image.src,image])).values()]
}
