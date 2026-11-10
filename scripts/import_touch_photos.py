"""Extract readable Touch assembly details from the original PDF image content.

Usage: python scripts/import_touch_photos.py '/path/Touch Assembly Instructions.pdf'
Crop coordinates preserve the guide's annotations and orientation. The PDF is
an authoring input only; it is not copied into the published guide.
"""
import argparse,json
from pathlib import Path
import pymupdf
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    folder=ROOT/'frontend/public/assembly/touch'
    sources=json.loads((folder/'sources.json').read_text())
    doc=pymupdf.open(args.pdf)
    for name,source in sources.items():
        rect=pymupdf.Rect(source['crop'])
        scale=min(8,2200/max(rect.width,rect.height))
        pix=doc[source['page']-1].get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=rect,alpha=False)
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        image.save(folder/f'{name}.webp',quality=95,method=6)
        print(name,pix.width,pix.height,flush=True)

if __name__=='__main__':main()
