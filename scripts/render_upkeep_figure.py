"""Render one Base upkeep figure using the assembly guide's existing Three.js CAD scenes.

Start Vite, then run:
uv run --no-project --with playwright python scripts/render_upkeep_figure.py --url http://127.0.0.1:5183
"""
import argparse
import base64
import json
from html import escape
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:5183')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = root / 'frontend/public/assembly/upkeep'
output.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    try:
        page = browser.new_page()
        page.route('**/__upkeep-figure', lambda route: route.fulfill(content_type='text/html', body='<!doctype html><title>Base upkeep figure</title>'))
        page.goto(args.url.rstrip('/') + '/__upkeep-figure')
        result = page.evaluate("""async () => {
            const {renderUpkeepFigure} = await import('/src/components/assembly/renderUpkeepFigure.ts');
            return renderUpkeepFigure();
        }""")
        image = output / 'base-index-ap-replacement.png'
        image.write_bytes(base64.b64decode(result.pop('data')))
        for panel in result.pop('images'):
            (output / panel['name']).write_bytes(base64.b64decode(panel['data']))
        frames = result.pop('printFrames')
        steps = result.pop('steps')
        knot_cues = page.evaluate("async () => (await import('/src/components/assembly/knotSteps.ts')).KNOT_CUES")
        captions = [
            ['Wiggle the finger; watch the matching motor.', 'Trace the broken AP tendon to motor 4.'],
            ['Remove the holder screw.', 'Slide the holder clear of the spools.'],
            ['Remove the top-spool screws.', 'Lift the top spools; keep their bearings fitted.'],
            ['Counter-rotate to unwind the motor 4 pair.', 'Free both ends from the spool channels.'],
            ['Pop out the finger; lift off the tip-and-middle unit.', 'Draw the AP pair back through the wrist and carpals.'],
            ['Pull out both pieces of the broken cord.', 'Insert the replacement, tie the stopper and seat it.'],
            ['Follow the measured carpal channels.', 'Continue through the wrist and into the tower.'],
            ['Pop the finger back into the hand.', 'Rethread the freed ends; rewind the spools.'],
            ['Refit top spools and start the screws.', 'Tension, power off, tighten and refit the holder.'],
        ]
        intro = 'A finger has six tendon ends; the thumb has eight. Keep the other ends attached to their spools. Pop out only the parts needed for access. Keep their pins and bearings fitted.'
        sheets = []
        for index, step in enumerate(steps):
            panels = ''.join(f'<figure><img src="data:image/png;base64,{frame["data"]}"><figcaption>{escape(captions[index][j])}</figcaption></figure>' for j, frame in enumerate(frames[index*2:index*2+2]))
            sheets.append(f'''<section class="sheet"><header><span>ORCA / MAINTENANCE</span><span>BASE RIGHT · DYNAMIXEL</span></header>
              <h1><b>{index+1:02d}</b> {escape(step['title'])}</h1>
              {f'<p class="intro">{intro}</p>' if index == 0 else ''}
              <div class="panels">{panels}</div>
              <div class="instructions"><p>{escape(step['instruction'])}</p><p class="detail">{escape(step['detail'])}</p>{'<p class="detail">Ashley stopper: illustrated knot sequence on pages 10–11.</p>' if index == 5 else ''}</div>
              <footer><span>Replacing the index AP tendon</span><span>{index+1} / 11</span></footer></section>''')
        for appendix, start in enumerate([0,6]):
            cards = []
            for i in range(start,min(start+6,11)):
                image_url = page.evaluate("async (path) => (await import('/src/components/assembly/media.ts')).mediaUrl(path)", f'./assembly/media/ashley-{i+1}.jpg')
                response = page.request.get(image_url if image_url.startswith('https://') else args.url.rstrip('/') + '/' + image_url.removeprefix('./'))
                assert response.ok, f'Could not load knot reference: {response.status}'
                photo = base64.b64encode(response.body()).decode()
                cards.append(f'<figure><img src="data:image/jpeg;base64,{photo}"><figcaption><b>{i+1:02d}.</b> {escape(knot_cues[i])}</figcaption></figure>')
            if appendix == 1:
                cards.append('<figure class="knot-finish"><h2>Finish the AP anchor</h2><p>Tie one single knot around the Ashley stopper, directly on top of it. Pull snug, then seat the anchor in the AP.</p><p>Spool anchors use the assembly guide’s Ashley stopper and three winding turns.</p></figure>')
            sheets.append(f'''<section class="sheet"><header><span>ORCA / MAINTENANCE</span><span>ASSEMBLY GUIDE · KNOT REFERENCE</span></header><h1>Ashley stopper · {appendix+1} / 2</h1><div class="knots">{''.join(cards)}</div><footer><span>Replacing the index AP tendon · knot reference for steps 6 and 8</span><span>{10+appendix} / 11</span></footer></section>''')
        html = '''<!doctype html><html><head><meta charset="utf-8"><title>ORCA — Index AP tendon maintenance</title><style>
          @page { size: A4 landscape; margin: 8mm; }
          * { box-sizing: border-box; } body { margin: 0; color: #20332f; font-family: Arial, sans-serif; }
          .sheet { height: 194mm; display: flex; flex-direction: column; break-after: page; padding: 3mm 5mm; }
          .sheet:last-child { break-after: auto; } header, footer { display: flex; justify-content: space-between; font-size: 8pt; letter-spacing: .8px; color: #526a62; }
          header { padding-bottom: 3mm; border-bottom: 1px solid #cbd4cd; } h1 { font-weight: 500; font-size: 23pt; margin: 5mm 0 3mm; } h1 b { color: #14786e; margin-right: 3mm; }
          .intro { font-size: 10pt; max-width: 245mm; line-height: 1.4; margin: 0 0 2mm; }
          .panels { display: grid; grid-template-columns: 1fr 1fr; gap: 7mm; flex: 1; min-height: 0; }
          figure { margin: 0; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
          .panels img { height: 0; flex: 1; min-height: 0; object-fit: contain; background: #f7f7f2; width: 100%; }
          figcaption { font-size: 10pt; line-height: 1.35; padding: 3mm 0 1mm; }
          .instructions { margin-top: 3mm; border-top: 1px solid #cbd4cd; padding-top: 2mm; }
          .instructions p { margin: 1mm 0; font-size: 11pt; line-height: 1.4; }
          .instructions .detail { font-size: 9pt; color: #526a62; } footer { margin-top: 4mm; font-size: 7pt; }
          .knots { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(3,1fr); grid-template-rows: 1fr 1fr; gap: 5mm 9mm; }
          .knots img { width: 100%; height: 0; flex: 1; min-height: 0; object-fit: contain; }
          .knots figcaption { font-size: 9pt; } .knots b { color: #14786e; }
          .knot-finish { justify-content: center; padding: 4mm; background: #f7f7f2; } .knot-finish h2 { font-size: 14pt; font-weight: 500; } .knot-finish p { font-size: 10pt; line-height: 1.5; }
        </style></head><body>''' + ''.join(sheets) + '</body></html>'
        page.set_content(html)
        page.emulate_media(media='print')
        page.evaluate("Promise.all(Array.from(document.images, image => image.decode()))")
        assert page.locator('.sheet').evaluate_all('(sheets) => sheets.every(s => s.scrollHeight <= s.clientHeight + 1)'), 'Print page overflow'
        pdf = output / 'index-ap-maintenance.pdf'
        page.pdf(path=str(pdf), print_background=True, prefer_css_page_size=True)
        print(pdf)
        inventory = root / 'frontend/public/assembly/parts'  / result['model'] / 'inventory.json'
        result['source'] = json.loads(inventory.read_text())['source']
        (output / 'base-index-ap-replacement.json').write_text(json.dumps(result, indent=2) + '\n')
        print(image)
        print(f"{result['width']} × {result['height']} · {result['model']}")
    finally:
        browser.close()
