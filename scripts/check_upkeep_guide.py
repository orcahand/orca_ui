"""Review the maintenance window using a production build and mocked APIs/WebSockets.

Serve a frontend production build, then run:
uv run --no-project --with playwright python scripts/check_upkeep_guide.py --url http://127.0.0.1:5192
No hardware backend is used. Requires Google Chrome.
"""
import argparse
import json
import re
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', default='http://127.0.0.1:5192')
ORIGIN = parser.parse_args().url.rstrip('/')
KEY = 'orca-ui.upkeep.v3'
SEED = {'current': 'p6', 'done': [], 'checks': [], 'tendons': [], 'views': {},
        'build': {'side': 'right', 'version': 'base', 'motor': 'dynamixel', 'audience': 'external'}}
INTRO = 'A finger has six tendon ends; the thumb has eight. Keep the other ends attached to their spools. Pop out only the parts needed for access. Keep their pins and bearings fitted.'

with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)

    def setup(seed=None, fail_storage=False):
        context = browser.new_context(viewport={'width': 1360, 'height': 1000})
        page = context.new_page()
        page.set_default_timeout(10000)
        mutations, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def api(route):
            request = route.request
            path = request.url.removeprefix(ORIGIN)
            if request.method not in ('GET', 'HEAD'):
                mutations.append((request.method, path))
            if path == '/api/estop':
                route.fulfill(json={'report': {'stopped': True}})
            elif path == '/api/assembly/progress':
                route.fulfill(json=SEED if request.method == 'GET' else {'ok': True})
            else:
                route.fulfill(status=503, json={})
        page.route(ORIGIN + '/api/**', api)
        page.route_web_socket(ORIGIN.replace('http', 'ws', 1) + '/ws', lambda ws: None)
        if seed is not None:
            page.add_init_script(f"localStorage.setItem('{KEY}', {json.dumps(seed)});")
        if fail_storage:
            page.add_init_script("Storage.prototype.setItem = function() { throw new DOMException('Test failure', 'QuotaExceededError'); };")
        page.goto(ORIGIN)
        page.get_by_role('button', name='Setup', exact=True).click()
        page.get_by_role('button', name='Maintenance', exact=True).click()
        guide = page.get_by_role('region', name='Maintenance', exact=True)
        expect(guide.get_by_role('heading', name='Step-by-step walkthrough of replacing the index AP tendon')).to_be_visible()
        return context, page, guide, mutations, errors

    context, page, guide, mutations, errors = setup()
    expect(page.get_by_role('dialog', name='Maintenance', exact=True)).to_be_visible()
    expect(page.get_by_role('dialog', name='Maintenance', exact=True).get_by_role('button', name='■ E-STOP')).to_be_visible()
    expect(guide.locator('.upkeep-intro')).to_have_text(INTRO)
    expect(guide.locator('.upkeep-grid')).to_have_count(0)
    expect(guide.get_by_role('navigation', name='Repair steps').get_by_role('button')).to_have_count(9)
    # Published previews and the PDF must work from a fresh checkout with no local copies.
    page.route(ORIGIN + '/assembly/upkeep/*.png', lambda route: route.abort())
    page.route(ORIGIN + '/assembly/upkeep/*.pdf', lambda route: route.abort())
    for index in range(9):
        guide.locator('.upkeep-chapters button').nth(index).click()
        poster = guide.locator('.upkeep-stage > img')
        expect(poster).to_have_attribute('src', re.compile(r'https://firebasestorage.googleapis.com/.*'))
        page.wait_for_function('(img) => img.complete && img.naturalWidth > 0', arg=poster.element_handle())
    guide.locator('.upkeep-chapters button').first.click()
    with page.expect_download() as download_info:
        guide.get_by_role('link', name='Download PDF ↓').click()
    download = download_info.value
    assert download.suggested_filename == 'index-ap-maintenance.pdf'
    assert download.failure() is None
    guide.get_by_role('button', name='Watch the repair', exact=True).click()
    slider = guide.get_by_role('slider', name='Animation progress')
    expect(slider).to_be_enabled(timeout=60000)
    # Keep the scene in view; scroll-based pause must not hide a playback defect.
    guide.locator('.upkeep-stage').scroll_into_view_if_needed()
    if guide.get_by_role('button', name='Pause', exact=True).count():
        guide.get_by_role('button', name='Pause', exact=True).click()
    slider.fill('3.95')
    expect(guide.locator('.upkeep-current-cue')).to_contain_text('Free both motor 4 ends')
    expect(guide.locator('.upkeep-callouts')).to_have_text('Motor 4')
    slider.fill('5.5')
    expect(guide.locator('.upkeep-knot-lesson img')).to_have_attribute('data-media', './assembly/media/ashley-4.jpg')
    expect(guide.locator('.upkeep-knot-lesson img')).to_have_attribute('src', re.compile(r'https://firebasestorage.googleapis.com/.*'))
    expect(guide.locator('.upkeep-current-cue')).to_contain_text('Keep the new loop open')
    expect(guide.locator('.upkeep-stage')).not_to_contain_text('Keep the new loop open')
    slider.fill('5.89')
    expect(guide.locator('.upkeep-current-cue')).to_contain_text('Tie one single knot')
    expect(guide.locator('.upkeep-stage')).not_to_contain_text('Tie the ordinary')
    for i in range(9):
        guide.locator('.upkeep-chapters button').nth(i).click()
        expect(guide.locator('.upkeep-player-caption > span')).to_have_text(f'STEP {i+1} / 9')
        expect(guide.locator('.upkeep-chapters button').nth(i)).to_have_attribute('aria-current', 'step')
        if i == 8: expect(guide.get_by_role('button', name='Play', exact=True)).to_be_visible()
    guide.locator('.upkeep-chapters button').nth(4).click()
    expect(slider).to_have_value('5')
    saved = json.loads(page.evaluate(f"localStorage.getItem('{KEY}')"))
    assert saved['current'] == 'open'
    guide.get_by_role('button', name='Close maintenance').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    page.get_by_role('button', name='Maintenance', exact=True).click()
    expect(guide.locator('.upkeep-player-caption > span')).to_have_text('STEP 5 / 9')
    guide.get_by_role('button', name='Watch the repair', exact=True).click()
    expect(slider).to_be_enabled(timeout=60000)
    expect(guide.locator('.upkeep-player-caption > span')).to_have_text('STEP 5 / 9')
    guide.get_by_role('combobox', name='Playback speed').select_option('2')
    guide.get_by_role('button', name='Play from start').click()
    guide.locator('.upkeep-stage').scroll_into_view_if_needed()
    for i in range(9):
        expect(guide.locator('.upkeep-player-caption > span')).to_have_text(f'STEP {i+1} / 9', timeout=30000)
    expect(guide.get_by_role('button', name='Replay', exact=True)).to_be_visible(timeout=15000)
    expect(slider).to_have_value('9')
    guide.get_by_role('button', name='Replay', exact=True).click()
    expect(guide.locator('.upkeep-player-caption > span')).to_have_text('STEP 1 / 9')
    # The assembly guide opens on top of maintenance and closes back to it.
    reference = guide.get_by_role('button', name='Assembly guide: knots and routing →')
    reference.click()
    assembly = page.get_by_role('dialog', name='Assembly instructions', exact=True)
    expect(assembly.get_by_role('heading', name='Ashley stopper knot', exact=True)).to_be_visible()
    expect(guide.get_by_role('button', name='Play', exact=True)).to_be_attached()
    assembly.get_by_role('button', name='■ E-STOP').click()
    page.keyboard.press('Escape')
    expect(reference).to_be_focused()
    slider.fill('5.5')
    for width in (320, 390, 768):
        page.set_viewport_size({'width': width, 'height': 900})
        assert guide.evaluate('(el) => el.scrollWidth <= el.clientWidth'), f'Overflow at {width}'
        page.wait_for_function('(el) => el.scrollWidth <= el.clientWidth', arg=guide.locator('.upkeep-stage').element_handle())
    guide.locator('.upkeep-stage').screenshot(path='/tmp/maintenance-review-mobile-knot.png')
    page.set_viewport_size({'width': 1360, 'height': 1000})
    slider.fill('4.95')
    guide.screenshot(path='/tmp/maintenance-review-desktop.png')
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    guide.screenshot(path='/tmp/maintenance-review-dark.png')
    guide.locator('canvas').evaluate("el => el.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()")
    expect(guide.get_by_role('alert')).to_contain_text('The animation could not load')
    guide.get_by_role('button', name='Retry animation').click()
    expect(slider).to_be_enabled(timeout=30000)
    assert not errors, errors
    assert all(path in ('/api/estop', '/api/assembly/progress') for _, path in mutations), mutations
    assert sum(path == '/api/estop' for _, path in mutations) == 1
    context.close()
    print('PASS: maintenance window, PDF, step selection, full playback/replay, labels only, assembly reference, mobile/dark layout, WebGL recovery, no hardware calls.', flush=True)

    for seed, fail_storage in [('{broken', False), (None, True)]:
        context, page, guide, mutations, errors = setup(seed, fail_storage)
        guide.locator('.upkeep-chapters button').nth(3).click()
        expect(guide.locator('.upkeep-player-caption > span')).to_have_text('STEP 4 / 9')
        assert not errors and not mutations, (errors, mutations)
        context.close()
    print('PASS: malformed saved state and unavailable storage.', flush=True)

    context, page, guide, mutations, errors = setup()
    page.route('**/*assembly*.glb*', lambda route: route.abort())
    guide.get_by_role('button', name='Watch the repair').click()
    expect(guide.get_by_role('alert')).to_contain_text('The animation could not load', timeout=30000)
    expect(guide.get_by_role('link', name='Download PDF ↓')).to_be_visible()
    assert not errors and not mutations, (errors, mutations)
    context.close()
    print('PASS: model failure preserves PDF and instructions.', flush=True)

    context, page, guide, mutations, errors = setup()
    page.emulate_media(reduced_motion='reduce')
    guide.get_by_role('button', name='Watch the repair').click()
    expect(guide.get_by_role('slider')).to_be_enabled(timeout=60000)
    expect(guide.get_by_role('button', name='Play', exact=True)).to_be_visible()
    expect(guide.get_by_role('slider')).to_have_value('0')
    assert not errors and not mutations, (errors, mutations)
    context.close()
    print('PASS: reduced motion starts paused.', flush=True)
    browser.close()
