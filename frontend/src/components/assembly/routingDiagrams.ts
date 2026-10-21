import cadViews from './cad-route-views.json'
import tpTraces from './tpTraces.json'
// Coordinates are traced on the numbered assembly diagrams, in native image pixels.
export type RoutingImage={src:string;width:number;height:number;view?:[number,number,number,number];markerRadius?:number;reference?:RoutingImage}
export type Route={name:string;color:string;path:string;entry:[number,number];exit:[number,number]|null}
export type RoutingDiagram={title:string;image:RoutingImage;entryImage:RoutingImage;exitImage:RoutingImage;routes:Route[];entryTitle:string;exitTitle:string;orientation:string}
const image=(file:string,width:number,height:number,view?:RoutingImage['view']):RoutingImage=>({src:`./assembly/media/panel-${file}.png`,width,height,view})
const colors=['#d99d54','#81bb50','#d3bd50','#ae86eb','#f26962','#29bfcb']
export function routingDiagram(step:string,side:'left'|'right',version:'base'|'touch'|'full'='base'):RoutingDiagram|null {
 const original=referenceDiagram(step,side)
 if(!original||version==='full')return original
 const root=`${version}-${side}-dynamixel`,views=cadViews as Record<string,{width:number;height:number;points:number[][]}>
 const entry=views[`${root}/route-${step}-entry`],exit=views[`${root}/route-${step}-exit`]
 if(!entry||!exit)return original
 const picture=(face:'entry'|'exit',data:typeof entry):RoutingImage=>({src:`./assembly/renders/${root}/route-${step}-${face}.webp`,width:data.width,height:data.height,markerRadius:24,reference:face==='entry'?original.entryImage:original.exitImage})
 return {...original,image:picture('entry',entry),entryImage:picture('entry',entry),exitImage:picture('exit',exit),orientation:['p59','p62'].includes(step)?'Keep these six tendons in order between the guide pins. The two TP anchor ends are separate.':'Select a tendon to locate its entry and exit.',routes:original.routes.map((r,i)=>({...r,entry:entry.points[i] as [number,number],exit:exit.points[i] as [number,number]}))}
}
function referenceDiagram(step:string,side:'left'|'right'):RoutingDiagram|null {
 if(['p42','p54'].includes(step)){
  const thumb=step==='p54'
  const names=['PP ext','PP flex','DP flex','DP ext'],tints=['#55c4cf','#f29b58','#dac64e','#ae86eb']
  const starts=thumb?[[550,211],[540,373],[529,333],[529,339]]:[[850,278],[786,440],[790,408],[790,420]]
  const ends=thumb?[[175,201],[198,297],[160,260],[150,245]]:[[495,207],[492,278],[478,249],[463,231]]
  const entries=thumb?ends:[[194,194],[194,276],[170,247],[161,222]]
  const exits=thumb?[[154,342],[158,351],[150,351],[146,358]]:[[280,377],[283,389],[276,391],[272,400]]
  return {title:thumb?'Thumb AP · match all four channels':'Finger AP · match all four channels',image:thumb?image('055-1',1036,433):image('044-1',1385,515),entryImage:thumb?image('055-1',1036,433,[35,105,260,280]):image('044-1',1385,515,[65,110,230,275]),exitImage:thumb?image('055-3',315,430,[115,300,105,110]):image('044-2',398,515,[222,328,132,162]),entryTitle:'Looking into the AP · entry',exitTitle:'Looking underneath · exit',orientation:'Orient the part like these views. Select one tendon and match its highlighted entry and exit before seating the joint.',routes:names.map((name,i)=>({name,color:tints[i],path:`M${starts[i]} C${thumb?350:620},${i===0?420:535} ${thumb?75:415},${i===0?270:470} ${ends[i]}`,entry:entries[i] as [number,number],exit:exits[i] as [number,number]}))}
 }
 if(['p59','p62'].includes(step)){
  const left=side==='left',entries=left?[704,675,651,623,594,563]:[173,200,226,254,284,315],exits=left?[187,214,240,265,288,309]:[365,341,315,293,271,248]
  return {title:'Six tendons through the TP',image:image(left?'061-1':'060-1',left?859:877,540),entryImage:image(left?'061-1':'060-1',left?859:877,540,left?[408,282,385,220]:[85,282,400,220]),exitImage:image(left?'061-2':'060-2',left?566:547,left?540:526,left?[112,320,290,205]:[182,310,255,206]),entryTitle:'Looking into the TP · entry',exitTitle:'Looking underneath · exit',orientation:`${side==='left'?'Left':'Right'} thumb. Keep the six existing tendons in this order. The two TP anchor ends are additional; the completed thumb has eight ends.`,routes:['AP toward thumb','PP ext','DP ext','DP flex','PP flex','AP toward pinky'].map((name,i)=>({name,color:colors[i],path:tpTraces[left?'061':'060'][i],entry:[entries[i],380],exit:[exits[i],left?398:388]}))}
 }
 if(step==='p64'){
  const left=side==='left',points=left?[[400,171],[346,155],[354,168],[350,188],[356,202],[292,175]]:[[192,166],[244,150],[233,164],[235,182],[235,194],[298,169]]
  return {title:'Six channels per finger',image:image(left?'067-1':'066-1',left?591:592,left?318:307),entryImage:image(left?'067-1':'066-1',left?591:592,left?318:307,undefined),exitImage:image(left?'067-2':'066-2',808,307,undefined),entryTitle:'Carpals · looking into the finger seat',exitTitle:'AP exits · keep the strands parallel',orientation:`${left?'Left':'Right'} hand, dorsum at the top and palm at the bottom. Repeat this six-channel order for index, middle, ring and pinky.`,routes:['AP toward pinky','PP ext','DP ext','DP flex','PP flex','AP toward thumb'].map((name,i)=>({name,color:colors[i],path:`M${points[i][0]},${points[i][1]} h.01`,entry:points[i] as [number,number],exit:i===0||i===5?null:[350,[0,173,184,179,190,0][i]]}))}
 }
 return null
}
