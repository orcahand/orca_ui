#!/usr/bin/env python3
"""Extract separate slide panels, omitting the decorative part-location badge."""
from pathlib import Path
import argparse,json,re
import pymupdf
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('pdf',type=Path)
source=pymupdf.open(parser.parse_args().pdf)
manifest=ROOT/'frontend/src/components/assembly/media-catalog.json'
media=json.loads(manifest.read_text())
for key,entry in media.items():
 n=int(key)
 if n in (84,85): continue # The three numbered routing maps already have separate crops.
 doc=pymupdf.open();doc.insert_pdf(source,from_page=n-1,to_page=n-1);p=doc[0]
 if n==101:
  p.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=pymupdf.Rect(110,92,550,367)).save(ROOT/'frontend/public/assembly/media/board-connectors.png')
  entry['panels']=[{'src':'./assembly/media/board-connectors.png','caption':'Complete OH board connector diagram','side':None}]
  continue
 # The badge is a small hand image plus an overlay near the upper-right corner.
 removed=[]
 for info in p.get_images(full=True):
  rects=p.get_image_rects(info[0])
  if any(r.x0>480 and r.y0<200 and r.width<175 and r.height<150 and (r.y0<110 or r.x0>625) for r in rects): removed.append(info[7])
 for xref in p.get_contents():
  stream=doc.xref_stream(xref)
  for name in removed:stream=re.sub(rb'/'+name.encode()+rb'\s+Do\b',b'',stream)
  doc.update_stream(xref,stream)
 p=doc.reload_page(p)
 original_log=p.get_bboxlog()
 # Remove yellow badge outlines. Functional raster arrows and numbers stay intact.
 for drawing in p.get_drawings():
  color=drawing.get('color')
  if color and color[0]>.8 and color[1]>.8 and color[2]<.2:p.add_redact_annot(drawing['rect']+(-2,-2,2,2),fill=None)
 p.apply_redactions(images=0,graphics=2,text=1)
 p=doc.reload_page(p)
 # Routing legends are real UI text next to the corresponding numbered instruction.
 for block in p.get_text('blocks'):
  rect=pymupdf.Rect(block[:4])
  p.add_redact_annot(rect,fill=None)
 p.apply_redactions(images=0,graphics=0)
 bounds=pymupdf.Rect(0,89,720,345)
 rects=[]
 previous=None
 for kind,coords in original_log:
  if kind=='fill-path':previous=pymupdf.Rect(coords)
  if kind!='fill-image':continue
  original=pymupdf.Rect(coords)
  rect=original & bounds
  # Slides crop large photos with a clipping rectangle immediately before the image.
  if previous and previous.get_area()>1000 and (original & previous).get_area()>.995*previous.get_area():rect=previous & bounds
  if rect.get_area()<1800:continue
  if not any((rect&r).get_area()>.98*rect.get_area() for r in rects):rects.append(rect)
 rects.sort(key=lambda r:(round(r.y0/30),r.x0))
 if n in (39,51,58):rects=[r for r in rects if r.y0<150][:2]
 if not rects:continue
 panels=[]
 for j,r in enumerate(rects):
  filename=f'panel-{n:03}-{j+1}.png'
  p.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=r,alpha=False).save(ROOT/'frontend/public/assembly/media'/filename)
  panels.append({'src':f'./assembly/media/{filename}','caption':f'Assembly detail {j+1}','side':entry['side']})
 entry['panels']=panels
 print(n,len(panels))
manifest.write_text(json.dumps(media,indent=2)+'\n')
