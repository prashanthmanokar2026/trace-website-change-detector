import asyncio
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import httpx
from playwright.async_api import async_playwright,expect
from traceapp.worker import tick
from tests.fixtures import FixtureRenderer
from tests.test_application import due
from traceapp.db import connect

async def test_owner_end_to_end_and_mobile(database):
    root=Path(__file__).resolve().parents[1]
    if not (root/'frontend/dist/index.html').exists():
        raise AssertionError('Run npm ci && npm run build in frontend before UI tests')
    salt=b'ui-test-salt-1234';password='ui-test-password-only'
    env={**os.environ,'PYTHONPATH':str(root/'backend'),'TRACE_DATA':str(database),'TRACE_BASE_URL':'http://127.0.0.1:8011',
         'TRACE_OWNER_HASH':salt.hex()+':'+hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()}
    server=subprocess.Popen([sys.executable,'-m','uvicorn','traceapp.api:app','--host','127.0.0.1','--port','8011','--no-access-log'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                try:
                    if (await client.get('http://127.0.0.1:8011/api/health')).status_code==200:break
                except httpx.HTTPError: pass
                await asyncio.sleep(.1)
            else: raise AssertionError('UI test API did not start')
        async with async_playwright() as p:
            browser=await p.chromium.launch()
            page=await browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            await page.goto('http://127.0.0.1:8011')
            await page.get_by_role('button',name='Owner sign in').click()
            await page.get_by_label('Owner password').fill(password)
            await page.get_by_role('button',name='Sign in',exact=True).click()
            await page.get_by_role('button',name='Add monitor').click()
            await page.get_by_label('Monitor name',exact=True).fill('Scholarship test')
            await page.get_by_label('Public webpage URL').fill('https://fixture.trace.test/scholarship')
            await page.get_by_role('button',name='Start monitoring').click()
            await expect(page.get_by_role('heading',name='Scholarship test',exact=True)).to_be_visible()
            with connect() as c:mid=c.execute('SELECT id FROM monitors').fetchone()[0]
            renderer=FixtureRenderer();await tick(renderer)
            await expect(page.get_by_role('heading',name='Version history')).to_be_visible(timeout=10000)
            await page.get_by_role('tab',name='Regions & settings').click()
            await page.screenshot(path='/tmp/trace-ui-settings.png',full_page=True)
            await page.get_by_label('Page element',exact=True).select_option('#announcement',timeout=3000)
            await page.get_by_role('button',name='Add to watched regions').click()
            await page.get_by_role('button',name='Preview compared text').click()
            await expect(page.get_by_role('heading',name='Text Trace will compare')).to_be_visible()
            assert '25,000' in await page.locator('.preview pre').inner_text()
            await page.get_by_role('button',name='Save settings').click()
            await asyncio.sleep(.2);due(mid);await tick(renderer)
            renderer.stage=1;due(mid);await tick(renderer)
            await page.get_by_role('tab',name='Version history').click()
            await expect(page.locator('.diff-line.added')).to_have_count(2,timeout=12000)
            await page.get_by_role('button',name='Side by side').click()
            await expect(page.locator('.screenshots img')).to_have_count(2)
            await page.get_by_role('button',name='Visual changes').click()
            await expect(page.locator('.visual-diff img')).to_be_visible()
            await page.set_viewport_size({'width':390,'height':844})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            await page.locator('.brand').focus()
            await page.keyboard.press('Tab')
            assert await page.evaluate('document.activeElement !== document.body')
            await page.get_by_role('button',name='Pause',exact=True).click()
            await expect(page.get_by_role('button',name='Resume',exact=True)).to_be_visible()
            await page.get_by_role('tab',name='Regions & settings').click()
            await page.get_by_role('button',name='Delete monitor',exact=True).click()
            await page.get_by_role('button',name='Keep monitor',exact=True).click()
            assert not await page.get_by_role('button',name='Delete permanently').count()
            assert not errors
            await browser.close()
    finally:
        server.terminate()
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: server.kill();server.wait()
