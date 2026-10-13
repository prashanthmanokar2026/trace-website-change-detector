"""Explicit fixture transport. Never imported by production application startup."""
import asyncio
from playwright.async_api import async_playwright
from traceapp.capture import capture_page, CaptureError


def page_html(kind='scholarship',stage=0,noise=0):
    titles={'scholarship':'Meridian Scholarship','release':'Studio release notes','event':'Design systems workshop'}
    title=titles.get(kind,'Meridian Scholarship')
    content={
      'scholarship': ('Applications open for the 2026 research fellowship.', 'Applications are now open to first-year students.'),
      'release': ('Version 2.4 · Faster exports and improved keyboard navigation.', 'Version 2.5 · Offline drafts and accessible table exports.'),
      'event': ('Saturday, 24 October · 10:00 AM · Room 204', 'Saturday, 24 October · 2:00 PM · Auditorium A')
    }[kind][min(stage,1)]
    price=('₹25,000 grant' if stage==0 else '₹35,000 grant') if kind=='scholarship' else ('Free registration' if kind=='event' else 'Available to all workspaces')
    return f'''<!doctype html><html><head><meta charset="UTF-8"><style>
      body{{margin:0;background:#f8f7f2;color:#263c34;font:18px/1.6 Arial,sans-serif}}
      header{{border-bottom:1px solid #d8dfd2;padding:28px 80px;display:flex;justify-content:space-between;font-size:14px}}
      main{{margin:65px 80px;max-width:950px}} .eyebrow{{font-size:12px;letter-spacing:2px;color:#637965}}
      h1{{font:52px/1.1 Georgia,serif;max-width:700px}} h2{{font-size:23px}} article{{border-top:1px solid #c9d8c7;padding:25px 0}}
      #award{{font-size:28px;color:#29664c}} aside{{padding:15px 25px;background:#e8eee1;margin-top:35px;font-size:14px}}
      footer{{margin:60px 80px;font-size:13px;color:#697763}}
    </style></head><body><header><b>MERIDIAN / COMMUNITY</b><span>Opportunities & updates</span></header>
      <main id="main"><p class="eyebrow">CONTROLLED DEMONSTRATION PAGE</p><h1>{title}</h1>
      <article id="announcement"><h2>Latest announcement</h2><p id="description">{content}</p><p id="award">{price}</p>
      <p id="deadline">Apply before 30 October 2026.</p></article>
      <aside data-ad="true">Community partner message {noise}</aside>
      <p><time>Updated at 10:{noise%60:02d}</time> · <span data-counter="true">{100+noise} views</span></p>
      <span data-random-token="true">request-{noise}</span></main><footer>This page is a reproducible test fixture. It is not an actual scholarship or event.</footer></body></html>'''

class FixtureRenderer:
    def __init__(self,kind='scholarship',stage=0,noise=0):
        self.kind,self.stage,self.noise=kind,stage,noise
        self.calls=0
        self.requests=0
        self.failure=None
    async def capture(self,url):
        self.calls+=1
        if self.failure: raise self.failure
        async with async_playwright() as p:
            browser=await p.chromium.launch()
            try:
                context=await browser.new_context(viewport={'width':1280,'height':900},device_scale_factor=1,locale='en-US',timezone_id='UTC',service_workers='block')
                async def respond(route):
                    if route.request.url.rstrip('/')==url.rstrip('/'):
                        self.requests+=1
                        await route.fulfill(status=200,content_type='text/html',body=page_html(self.kind,self.stage,self.noise))
                    else:
                        await route.abort()
                await context.route('**/*',respond)
                page=await context.new_page(); await page.goto(url)
                return await capture_page(page)
            finally:
                await browser.close()
