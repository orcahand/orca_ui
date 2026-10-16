#!/usr/bin/env python3
"""Create local, bounded walkthrough clips from the ORCA assembly video.

Usage: python scripts/import_assembly_clips.py /path/to/TgIz7HiyaoU.mp4
Requires ffmpeg. The full recording stays outside the application bundle.
"""
import argparse
import concurrent.futures
import json
import subprocess
from pathlib import Path

# Reviewed against the recording. Titles describe the action in each excerpt.
# Board programming in the recording predates the OH board: do not import it.
CUTS = [
    ('p73', 1845, 1916, 'Fit the carpal pins, pulley and skin'),
    ('p6', 86, 118, 'Tie an Ashley stopper'),
    ('p46', 768, 888, 'Prepare the thumb DP and PP pins'),
    ('p46', 888, 1006, 'Seat the thumb tendons, joint and skins'),
    ('p49', 1108, 1195, 'Anchor the thumb AP tendons'),
    ('p52', 1195, 1220, 'Trim and seat the thumb AP stoppers'),
    ('p54', 1006, 1108, 'Route and join the thumb AP'),
    ('p56', 1220, 1280, 'Prepare the TP tendon anchors'),
    ('p59', 1305, 1405, 'Route the six tendons through TP'),
    ('p62', 1405, 1465, 'Seat the thumb joint and bearings'),
    ('p112', 3479, 3500, 'Motor setup reference'),
    ('p135', 5035, 5135, 'Fit the side and hull covers'),
    ('p136', 4985, 5025, 'Seat the rear hull cover'),
    ('p26', 78, 153, 'Tie the double-knot tendon'),
    ('p29', 153, 239, 'Thread and seat the DP tendon and bearings'),
    ('p33', 239, 321, 'Fit the PP tendon and pins'),
    ('p33', 347, 416, 'Route DP through PP and seat the joint'),
    ('p35', 416, 426, 'Check free movement'),
    ('finishing-pp', 329, 346, 'Fit the DP skin'),
    ('finishing-pp', 426, 445, 'Fit the PP skin'),
    ('p37', 638, 685, 'Cut and anchor the AP tendons'),
    ('p42', 475, 558, 'Route the four AP tendons'),
    ('p42', 558, 638, 'Seat the AP, pins and bearings'),
    ('p40', 685, 718, 'Trim and tuck the AP stopper'),
    ('p18', 1483, 1502, 'Finish the carpal openings'),
    ('p64', 1510, 1635, 'Route a finger into the carpals'),
    ('p64', 1635, 1715, 'Seat the finger joint'),
    ('p68', 1761, 1845, 'Attach the thumb to the carpals'),
    ('p75', 2330, 2460, 'Prepare the wrist screws and sleeves'),
    ('p77', 2486, 2590, 'Start threading the wrist'),
    ('p77', 2590, 2660, 'Finish the wrist routing'),
    ('p89', 2678, 2755, 'Fit the belt and seat the hand in the wrist'),
    ('p122', 2755, 2828, 'Fit the wrist motor carrier'),
    ('p122', 2828, 2916, 'Fit the pulley, bearing and wrist drive'),
    ('p122', 3976, 4020, 'Join the wrist and tower'),
    ('p93', 2917, 3045, 'Route the tower wires and fit the fans'),
    ('p93', 3045, 3170, 'Secure the fans and tower nuts'),
    ('p98', 3403, 3430, 'Seat the Dynamixel connector PCB'),
    ('p99', 3238, 3373, 'Assemble a motor spool and ratchet'),
    ('p115', 3500, 3590, 'Install motors in the tower'),
    ('p115', 3690, 3775, 'Link the motor columns'),
    ('p123', 4146, 4235, 'Thread and knot a bottom spool'),
    ('p123', 4235, 4307, 'Wind the remaining bottom spools'),
    ('p126', 4307, 4448, 'Thread the top spool and fit its bearing and screw'),
    ('p126', 4448, 4605, 'Repeat and check joint pairing'),
    ('p127', 4617, 4750, 'Fit the spool holders'),
    ('p129', 1940, 2040, 'Fit the tower magnets'),
    ('p132', 2100, 2195, 'Fit the hull magnets'),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    out=root/'frontend/public/assembly/clips';out.mkdir(parents=True,exist_ok=True)
    def cut(row):
        step,start,end,title=row
        name=f'{step}-{start}'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(args.video),'-t',str(end-start),'-vf','scale=960:-2','-c:v','libx264','-preset','veryfast','-crf','26','-threads','2','-c:a','aac','-b:a','80k','-movflags','+faststart',str(out/f'{name}.mp4')],check=True)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss','2','-i',str(out/f'{name}.mp4'),'-frames:v','1','-q:v','3',str(out/f'{name}.jpg')],check=True)
        return step,dict(src=f'./assembly/clips/{name}.mp4',poster=f'./assembly/clips/{name}.jpg',title=title,duration=end-start)
    catalog={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for step,clip in pool.map(cut,CUTS):
            catalog.setdefault(step,[]).append(clip)
            print(clip['title'],flush=True)
    (root/'frontend/src/components/assembly/local-clips.json').write_text(json.dumps(catalog,indent=2)+'\n')
if __name__=='__main__': main()
