"""Prompt locally; never print the password or include it in process arguments."""
import getpass
import hashlib
import os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
a=getpass.getpass('Choose an owner password (at least 12 characters): ')
b=getpass.getpass('Confirm password: ')
if len(a)<12 or a!=b: raise SystemExit('Passwords must match and contain at least 12 characters')
salt=os.urandom(16)
value=salt.hex()+':'+hashlib.scrypt(a.encode(),salt=salt,n=16384,r=8,p=1).hex()
p=root/'.env'
lines=p.read_text().splitlines() if p.exists() else []
lines=[x for x in lines if not x.startswith('TRACE_OWNER_HASH=')]
p.write_text('\n'.join(lines+['TRACE_OWNER_HASH='+value])+'\n'); p.chmod(0o600)
print('Owner password configured. Restart the API to load it.')
