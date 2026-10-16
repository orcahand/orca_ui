#!/usr/bin/env python3
"""Extract annotated assembly photos without shipping the source PDF.

uv run --no-project --with pymupdf --with pillow python scripts/import_assembly_guide.py '/path/Assembly Instructions.pdf'

The crop map matches the supplied 157-page V2.1 base guide. Preview cropped
images after changing the document; this deliberately is not a PDF viewer.
"""
import argparse
from pathlib import Path
import pymupdf, re, json
from PIL import Image, ImageChops
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('pdf',type=Path)
parser.add_argument('--dpi',type=int,default=300,help='Rasterization resolution (default: 300 DPI). Source photo detail remains the limit.')
args=parser.parse_args()
if args.dpi<=0:parser.error('--dpi must be positive')
scale=args.dpi/72
root=Path(__file__).resolve().parents[1]
doc=pymupdf.open(args.pdf)
out=root/'frontend/public/assembly/media'; out.mkdir(parents=True,exist_ok=True)
# Tight crops for mixed text/photo layouts; composite diagrams retain their annotations.
crops={15:(405,89,720,340),11:(383,89,702,340),30:(25,90,710,335),39:(20,98,695,337),44:(25,96,695,337),51:(20,98,695,337),58:(20,98,695,337),60:(6,91,680,345),61:(6,91,680,345),66:(0,91,710,344),67:(0,91,710,344),79:(30,87,720,345),84:(0,0,720,367),85:(0,0,720,367),94:(395,90,710,345),95:(397,90,710,345),98:(401,90,710,345),101:(90,93,559,366),103:(328,100,701,345),104:(336,100,702,345),105:(347,102,678,310),106:(24,104,700,338),110:(23,215,620,360),111:(333,103,704,343),122:(377,90,710,346),124:(392,88,692,345),125:(378,90,698,342),126:(358,85,704,346),128:(292,100,702,344),151:(322,102,705,345),152:(317,100,704,342)}
crops.update({45:(400,90,700,340),59:(420,89,700,340),116:(280,89,700,345),127:(95,175,700,345),135:(510,90,715,345),89:(25,220,170,345)})
skip={1,2,3,4,5,6,24,25,26,28,46,64,83,86,87,88,93,97,123,129,139,141,142,143,144,145,146,147,148,149,150,153,154,155,157}
media={}
for n,p in enumerate(doc,1):
 ims=[im for im in p.get_image_info() if pymupdf.Rect(im['bbox']).intersects(pymupdf.Rect(0,90,720,365)) and pymupdf.Rect(im['bbox']).get_area()>1800]
 if not ims or n in skip: continue
 crop=pymupdf.Rect(crops.get(n,(0,89,720,345)))
 # Remove body paragraphs already rendered as real UI text, retaining short diagram labels.
 for b in p.get_text('blocks'):
  rect=pymupdf.Rect(b[:4]); txt=b[4]
  if n not in {39,44,51,55,58,60,61,66,67,81,101,110,124,126,128,138} or rect.y0<88 or rect.y0>=365 or (' = ' in txt and rect.y0>=340) or len(txt)>140:
   p.add_redact_annot(rect,fill=(1,1,1))
 p.apply_redactions(images=0,graphics=0)
 pix=p.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=crop,alpha=False)
 im=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
 mask=ImageChops.difference(im,Image.new('RGB',im.size,'white')).convert('L').point(lambda v:255 if v>35 else 0)
 box=mask.getbbox()
 if not box: continue
 box=(max(0,box[0]-18),max(0,box[1]-18),min(im.width,box[2]+18),min(im.height,box[3]+18))
 im=im.crop(box)
 filename=f'detail-{n:03}.png'; im.save(out/filename)
 side='right' if n in (60,66,84,116) else 'left' if n in (61,67,85) else None
 media[str(n)]={'src':f'./assembly/media/{filename}','side':side}
(root/'frontend/src/components/assembly/media-catalog.json').write_text(json.dumps(media,indent=2)+'\n')
print('Extracted',len(media),'annotated media panels')
# Keep the three numbered mapping views intact, including fingertip IDs at the top.
doc = pymupdf.open(args.pdf)
for n, side in [(84, 'right'), (85, 'left')]:
    panels = []
    for label, clip in [('Wrist channel numbering', (27,92,262,362)), ('Joint and palm-side mapping', (272,3,498,368)), ('Back-side spool mapping', (508,51,700,367))]:
        j=len(panels)+1
        filename=f'mapping-{side}-{j}.png'
        doc[n-1].get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=pymupdf.Rect(clip),alpha=False).save(out/filename)
        panels.append({'src':f'./assembly/media/{filename}','caption':f'{label} · {side} hand','side':side})
    media[str(n)]['panels']=panels
(root/'frontend/src/components/assembly/media-catalog.json').write_text(json.dumps(media,indent=2)+'\n')
