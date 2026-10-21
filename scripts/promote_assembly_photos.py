"""Promote higher-resolution PDF panel crops without changing their framing.

First run refine_assembly_panels.py with --dpi 600 and --output-root STAGING.
Then run this script with that staging folder. Originals remain available for
comparison; only verified matching crops enter the guide's resolution map.
"""
import argparse,json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('staging',type=Path)
    args=parser.parse_args()
    source=args.staging/'frontend/public/assembly/media'
    target=ROOT/'frontend/public/assembly/media/hires';target.mkdir(exist_ok=True)
    mapping={};size=0
    for path in sorted(source.glob('*.png')):
        original=target.parent/path.name
        if not original.exists():continue
        with Image.open(original) as old,Image.open(path) as new:
            aspect_error=abs(old.width/old.height-new.width/new.height)/(old.width/old.height)
            if aspect_error>=.012:raise ValueError(f'Crop changed: {path.name}')
            if new.width<=old.width:continue
            new.save(target/f'{path.stem}.webp',quality=95,method=6)
        mapping[f'./assembly/media/{path.name}']=f'./assembly/media/hires/{path.stem}.webp'
        size+=(target/f'{path.stem}.webp').stat().st_size
    (ROOT/'frontend/src/components/assembly/photoResolutionMap.json').write_text(json.dumps(mapping,indent=2)+'\n')
    print(f'Promoted {len(mapping)} verified crops, {size/1024**2:.1f} MiB total.',flush=True)

if __name__=='__main__':main()
