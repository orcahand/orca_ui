import resolutions from './photoResolutionMap.json'
import type {Figure} from './buildContent'
export const photoResolution=(src:string)=>(resolutions as Record<string,string>)[src]??src
export const resolvedFigure=(figure:Figure):Figure=>({...figure,src:photoResolution(figure.src),...(figure.photo?{photo:{...figure.photo,src:photoResolution(figure.photo.src)}}:{})})
