import asyncio
import time
import os
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx
from playwright.async_api import async_playwright
from .config import PROXY
from .policy import validate_url

class CaptureError(Exception):
    def __init__(self, message, blocked=False, retry_after=0):
        super().__init__(message)
        self.blocked = blocked
        self.retry_after = retry_after

@dataclass
class Capture:
    html: str
    geometry: list
    image: bytes
    captured: float

# The cloned HTML is parsed as data only. Scripts/styles/hidden content are removed.
SCRIPT = r'''() => {
  const all = [...document.body.querySelectorAll('*')];
  if (all.length > 12000) throw Error('Page has too many elements');
  const selector = el => {
    if (el.id && document.querySelectorAll('#'+CSS.escape(el.id)).length===1) return '#'+CSS.escape(el.id);
    let parts=[];
    for(let node=el;node && node!==document.body;node=node.parentElement){
      const tag=node.tagName.toLowerCase();
      const siblings=[...node.parentElement.children].filter(n=>n.tagName===node.tagName);
      parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');
    }
    return 'body > '+parts.join(' > ');
  };
  const geometry=[];
  all.forEach((el,i)=>{
    el.setAttribute('data-trace-key',String(i));
    const r=el.getBoundingClientRect(), s=getComputedStyle(el);
    if(!r.width || !r.height || s.visibility==='hidden' || s.display==='none' || s.opacity==='0') el.setAttribute('data-trace-hidden','1');
    if(!el.hasAttribute('data-trace-hidden') && r.width>4 && r.height>4 && r.top<4000 && geometry.length<1800 && !['SCRIPT','STYLE','NOSCRIPT'].includes(el.tagName))
      geometry.push({key:String(i),selector:selector(el),tag:el.tagName.toLowerCase(),label:(el.innerText||el.getAttribute('alt')||el.tagName).slice(0,90),box:[r.x+scrollX,r.y+scrollY,r.width,r.height]});
  });
  const clone=document.documentElement.cloneNode(true);
  clone.querySelectorAll('script,style,noscript,template,head,iframe,[data-trace-hidden]').forEach(el=>el.remove());
  clone.querySelectorAll('*').forEach(el=>[...el.attributes].forEach(a=>{
    if(a.name.startsWith('on') || ['src','srcset','href','action','formaction'].includes(a.name))el.removeAttribute(a.name);
  }));
  return {html:clone.outerHTML,geometry};
}'''

class Renderer:
    def __init__(self):
        self.robots = {}

    async def robots_allowed(self, url):
        u = urlsplit(url); origin = f'{u.scheme}://{u.netloc}'
        saved = self.robots.get(origin)
        if saved and saved[0] > time.time():
            return saved[1].can_fetch('TraceMonitor',url)
        async with httpx.AsyncClient(proxy=PROXY, timeout=10, trust_env=False) as client:
            response = await client.get(origin+'/robots.txt', follow_redirects=False)
            if response.status_code == 404:
                lines=[]
            elif response.status_code != 200:
                raise CaptureError('robots.txt could not be verified', blocked=True)
            else:
                if len(response.content)>256000:
                    raise CaptureError('robots.txt exceeds size limit',blocked=True)
                lines=response.text.splitlines()
        parser=RobotFileParser(); parser.parse(lines)
        self.robots[origin]=(time.time()+3600,parser)
        return parser.can_fetch('TraceMonitor',url)

    async def capture(self,url):
        validate_url(url)
        async with asyncio.timeout(50):
            if not await self.robots_allowed(url):
                raise CaptureError('Monitoring disallowed by robots.txt',blocked=True)
            async with async_playwright() as p:
                browser = await p.chromium.launch(chromium_sandbox=True,env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','SYSTEMROOT','PLAYWRIGHT_BROWSERS_PATH')},proxy={'server':PROXY,'bypass':'<-loopback>'},
                    args=['--disable-quic','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
                try:
                    context = await browser.new_context(viewport={'width':1280,'height':900},
                        device_scale_factor=1,locale='en-US',timezone_id='UTC',service_workers='block',
                        accept_downloads=False,user_agent='TraceMonitor/1.0 (public-page change detection)')
                    await context.route_web_socket('**/*',lambda ws:ws.close())
                    count=0
                    async def guard(route):
                        nonlocal count
                        count+=1
                        try:
                            validate_url(route.request.url)
                            if count>100 or route.request.method not in ('GET','HEAD') or route.request.resource_type in ('media','font'):
                                raise ValueError('request budget')
                            await route.continue_()
                        except ValueError:
                            await route.abort()
                    await context.route('**/*',guard)
                    page=await context.new_page()
                    context.on('page',lambda popup: asyncio.create_task(popup.close()) if popup!=page else None)
                    response=await page.goto(url,wait_until='domcontentloaded',timeout=25000)
                    if not response:
                        raise CaptureError('No page response')
                    if response.status>=400:
                        retry=0
                        value=response.headers.get('retry-after','')
                        try: retry=float(value)
                        except ValueError:
                            try: retry=parsedate_to_datetime(value).timestamp()-time.time()
                            except (ValueError,TypeError): pass
                        raise CaptureError(f'Website returned HTTP {response.status}',
                            blocked=response.status in (401,403),retry_after=max(0,min(retry,86400)))
                    await page.wait_for_timeout(800)
                    body=(await page.locator('body').inner_text(timeout=5000)).lower()
                    if any(x in body[:8000] for x in ('verify you are human','checking your browser','complete the captcha','access denied','just a moment...')):
                        raise CaptureError('Access challenge detected; no baseline updated',blocked=True)
                    return await capture_page(page)
                finally:
                    await browser.close()

async def capture_page(page):
    await page.evaluate('window.stop()')
    await page.context.set_offline(True)
    await page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}')
    await page.clock.pause_at(int(time.time()*1000))
    result=await page.evaluate(SCRIPT)
    if len(result['html'])>1500000:
        raise CaptureError('Page DOM exceeds size limit')
    height=min(4000,max(900,await page.evaluate('document.documentElement.scrollHeight')))
    image=await page.screenshot(type='png',clip={'x':0,'y':0,'width':1280,'height':height},animations='disabled',timeout=10000)
    return Capture(result['html'],result['geometry'],image,time.time())
