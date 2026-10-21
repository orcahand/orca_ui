"""Extract the unmodified, full-resolution OH-board photo for the port selector.

Usage: python scripts/import_control_board_photo.py '/path/Assembly Instructions.pdf'
The UI applies the original page rotation and adds its own accessible port labels.
"""
import argparse,hashlib,json
from pathlib import Path
import pymupdf
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    doc=pymupdf.open(args.pdf)
    page=doc[100]
    images=[i for i in page.get_image_info(xrefs=True) if i['width']==864 and i['height']==1152]
    assert len(images)==1,'Expected the original portrait OH-board photograph on page 101.'
    info=images[0];image=doc.extract_image(info['xref'])
    assert image['ext']=='jpeg'
    folder=ROOT/'frontend/public/assembly/details';folder.mkdir(exist_ok=True)
    (folder/'oh-board-reference.jpeg').write_bytes(image['image'])
    (folder/'oh-board-reference.json').write_text(json.dumps({'pdfSha256':hashlib.sha256(args.pdf.read_bytes()).hexdigest(),'page':101,'width':image['width'],'height':image['height'],'rotationDegrees':-90,'imageSha256':hashlib.sha256(image['image']).hexdigest()},indent=2)+'\n')
    print('Extracted original OH-board photo, without resampling:',len(image['image']),'bytes')

if __name__=='__main__':main()
