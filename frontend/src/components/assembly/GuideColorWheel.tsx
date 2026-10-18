import {useLayoutEffect,useRef} from 'react'
function hsv(hex:string){
 const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255),max=Math.max(...rgb),min=Math.min(...rgb),d=max-min
 const h=d===0?0:max===rgb[0]?((rgb[1]-rgb[2])/d+6)%6:max===rgb[1]?(rgb[2]-rgb[0])/d+2:(rgb[0]-rgb[1])/d+4
 return [h*60,max===0?0:d/max,max]
}
function rgb(h:number,s:number,v:number){const c=v*s,x=c*(1-Math.abs(h/60%2-1)),m=v-c;return (h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x]).map(n=>Math.round((n+m)*255))}
const hex=(h:number,s:number,v:number)=>'#'+rgb((h+360)%360,s,v).map(n=>n.toString(16).padStart(2,'0')).join('')
export function GuideColorWheel({value,onChange,disabled}:{value:string;onChange:(value:string)=>void;disabled:boolean}){
 const ref=useRef<HTMLCanvasElement>(null),[h,s,v]=hsv(/^#[0-9a-f]{6}$/i.test(value)?value:'#ffffff'),size=180
 useLayoutEffect(()=>{
  const ctx=ref.current?.getContext('2d');if(!ctx)return
  const pixels=ctx.createImageData(size,size)
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
   const dx=x-size/2,dy=y-size/2,r=Math.hypot(dx,dy)/(size/2-3);if(r>1)continue
   const color=rgb((Math.atan2(dy,dx)*180/Math.PI+360)%360,r,1),i=(y*size+x)*4
   pixels.data.set([...color,disabled?85:255],i)
  }
  ctx.putImageData(pixels,0,0)
  const x=size/2+Math.cos(h*Math.PI/180)*s*(size/2-3),y=size/2+Math.sin(h*Math.PI/180)*s*(size/2-3)
  ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.lineWidth=3;ctx.strokeStyle='#fff';ctx.stroke();ctx.lineWidth=1;ctx.strokeStyle='#25353b';ctx.stroke()
 },[h,s,disabled])
 function pick(e:React.PointerEvent<HTMLCanvasElement>){if(disabled)return;const box=e.currentTarget.getBoundingClientRect(),x=(e.clientX-box.left)/box.width-.5,y=(e.clientY-box.top)/box.height-.5;onChange(hex(Math.atan2(y,x)*180/Math.PI,Math.min(1,Math.hypot(x,y)*2),v||1))}
 return <div className="assembly-color-wheel"><canvas ref={ref} width={size} height={size} role="slider" tabIndex={disabled?-1:0} aria-disabled={disabled} aria-label="Background color wheel" aria-valuemin={0} aria-valuemax={360} aria-valuenow={Math.round(h)} aria-valuetext={`${value}; left and right change hue, up and down change saturation`} onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);pick(e)}} onPointerMove={e=>{if(e.buttons===1)pick(e)}} onKeyDown={e=>{if(disabled||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();onChange(hex(h+(e.key==='ArrowRight'?3:e.key==='ArrowLeft'?-3:0),Math.max(0,Math.min(1,s+(e.key==='ArrowUp'?.03:e.key==='ArrowDown'?-.03:0))),v||1))}}/><label>Brightness<input type="range" aria-label="Background brightness" min="0" max="100" value={Math.round(v*100)} disabled={disabled} onChange={e=>onChange(hex(h,s,+e.target.value/100))}/></label></div>
}
