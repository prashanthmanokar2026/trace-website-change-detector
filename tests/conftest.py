import hashlib
import pytest
from traceapp import db,config

@pytest.fixture
def database(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    db.init()
    return tmp_path

@pytest.fixture
def client(database,monkeypatch):
    from fastapi.testclient import TestClient
    from traceapp.api import app,limits
    salt=b'test-salt-value-1'
    password='test-owner-password'
    monkeypatch.setattr(config,'OWNER_HASH',salt.hex()+':'+hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex())
    limits.clear()
    with TestClient(app,base_url=config.BASE_URL,headers={'Origin':config.BASE_URL}) as c:
        yield c

@pytest.fixture
def signed(client):
    response=client.post('/api/login',json={'password':'test-owner-password'})
    assert response.status_code==200
    client.headers['x-csrf-token']=response.json()['csrf']
    return client
