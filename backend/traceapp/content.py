import io
import json
import re
from bs4 import BeautifulSoup
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from detector.core import normalize

PRESETS = {'timestamps':'time, [data-timestamp]', 'counters':'[data-counter]',
           'ads':'[data-ad], .advertisement, [aria-label="Advertisement"]',
           'banners':'[data-rotating-banner]', 'tokens':'[data-random-token]'}

def extract(html, geometry, config):
    soup = BeautifulSoup(html, 'html.parser')
    watches = config.get('watch', [])
    ignores = config.get('ignore', [])
    masks = []
    geo = {e['key']: e for e in geometry}
    for selector in watches + ignores:
        try:
            if not soup.select(selector):
                raise ValueError('Selected region no longer matches: ' + selector)
        except Exception as exc:
            raise ValueError('Invalid or missing region: ' + selector) from exc
    for selector in ignores + [s for k,s in PRESETS.items() if config.get(k, False)]:
        for element in list(soup.select(selector)):
            if element.parent is None:
                continue
            key = element.get('data-trace-key')
            if key in geo:
                masks.append(geo[key]['box'])
            element.decompose()
    selected = [e for s in watches for e in soup.select(s)] if watches else [soup]
    if watches and not selected:
        raise ValueError('Ignored regions cover the watched region')
    text = normalize('\n'.join(e.get_text('\n', strip=True) for e in selected))
    if len(text) > 24000:
        raise ValueError('Monitored text exceeds 24,000 characters; select a smaller region')
    if not text:
        raise ValueError('No visible monitored text; select another region')
    return text, masks

def image_diff(before, after, masks):
    a, b = Image.open(io.BytesIO(before)).convert('RGB'), Image.open(io.BytesIO(after)).convert('RGB')
    size = (max(a.width,b.width), max(a.height,b.height))
    canvases = []
    for source in (a,b):
        canvas = Image.new('RGB',size,'white'); canvas.paste(source,(0,0))
        draw = ImageDraw.Draw(canvas)
        for x,y,w,h in masks:
            draw.rectangle((x,y,x+w,y+h), fill='white')
        canvases.append(canvas)
    difference = ImageChops.difference(*canvases).convert('L').point(lambda v: 255 if v > 28 else 0)
    difference = difference.filter(ImageFilter.MaxFilter(5))
    result = Image.blend(canvases[1], Image.new('RGB',size,'white'),0.28)
    overlay = Image.new('RGB',size,'#ce493b')
    result = Image.composite(Image.blend(result,overlay,0.65),result,difference)
    output = io.BytesIO(); result.save(output,format='PNG')
    return output.getvalue()
