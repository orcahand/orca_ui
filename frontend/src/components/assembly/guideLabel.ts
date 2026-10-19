// Keep CAD lookup names intact; format their dimensions only when displaying them.
export function guideLabel(text:string):string {
 const [name,...details]=text.split(' · ')
 return details.length?`${name} (${details.join('; ').replace(/ \(([^()]*)\)/g,'; $1')})`:text
}
const punctuationNeutral=(text:string)=>text.replace(/[·();,]/g,' ').replace(/\.\s+/g,' ').replace(/[.]$/,'').replace(/\s+/g,' ').trim().toLowerCase()
export const sameGuideSource=(a:string,b:string)=>a===b||punctuationNeutral(a)===punctuationNeutral(b)
