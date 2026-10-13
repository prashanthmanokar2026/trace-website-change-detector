import asyncio
from email.message import EmailMessage
import os
import re
import smtplib
import ssl
import time
import httpx
from .db import connect


def configured(channel):
    return bool(os.getenv('TRACE_SMTP_HOST') and os.getenv('TRACE_EMAIL_TO') and os.getenv('TRACE_EMAIL_FROM')) if channel=='email' else bool(os.getenv('TRACE_DISCORD_WEBHOOK'))

def email_send(body):
    message=EmailMessage(); message['Subject']='Trace · Website change detected'
    message['From']=os.environ['TRACE_EMAIL_FROM']; message['To']=os.environ['TRACE_EMAIL_TO']; message.set_content(body)
    with smtplib.SMTP(os.environ['TRACE_SMTP_HOST'],int(os.getenv('TRACE_SMTP_PORT','587')),timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        if os.getenv('TRACE_SMTP_USER'):
            smtp.login(os.environ['TRACE_SMTP_USER'],os.environ['TRACE_SMTP_PASSWORD'])
        smtp.send_message(message)

async def send(channel,body):
    if not configured(channel): raise ValueError('Channel credentials not configured')
    if channel=='email':
        await asyncio.to_thread(email_send,body)
    else:
        url=os.environ['TRACE_DISCORD_WEBHOOK']
        if not re.fullmatch(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+',url):
            raise ValueError('Unsupported Discord webhook destination')
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as client:
            response=await client.post(url,json={'content':body,'allowed_mentions':{'parse':[]}})
            response.raise_for_status()

async def deliver_one(sender=send,now=None):
    now=now or time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # An interrupted sending record is uncertain, so do not blindly resend it.
        db.execute("UPDATE outbox SET state='uncertain',error='Worker interrupted during delivery; check recipient before retrying' WHERE state='sending' AND due<?",(now-120,))
        row=db.execute("SELECT * FROM outbox WHERE state='pending' AND due<=? AND channel IN (SELECT key FROM settings WHERE value='on') ORDER BY id LIMIT 1",(now,)).fetchone()
        if not row: return False
        settings=dict(db.execute('SELECT key,value FROM settings').fetchall())
        if settings.get(row['channel'])!='on': return False
        db.execute("UPDATE outbox SET state='sending',attempts=attempts+1,due=? WHERE id=?",(now,row['id']))
    try:
        await sender(row['channel'],row['body'])
    except (httpx.TimeoutException,smtplib.SMTPServerDisconnected,TimeoutError):
        state,error='uncertain','Delivery acknowledgement missing; check recipient before retrying'
    except Exception:
        state='failed' if row['attempts']>=2 else 'pending'
        error='Delivery failed; check server configuration or provider status'
    else:
        state,error='sent',None
    with connect() as db:
        db.execute('UPDATE outbox SET state=?,error=?,due=? WHERE id=?',(state,error,now+60*2**row['attempts'],row['id']))
    return True
