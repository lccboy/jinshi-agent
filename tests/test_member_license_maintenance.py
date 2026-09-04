import datetime as dt
import json
from pathlib import Path
import subprocess
import shutil
import pytest
from io import BytesIO

from services import local_license


def cached(tmp_path, now):
    value = {'member_id':'U1','code':'AK-TEST','device_fingerprint':'DEV-1',
             'status':'active','checked_at':(now-dt.timedelta(hours=7)).isoformat(),
             'expire_timestamp':(now+dt.timedelta(days=10)).timestamp()}
    (tmp_path/'license.json').write_text(json.dumps(value))
    return value


def test_maintenance_refreshes_before_grace_expires_and_rate_limits_failures(tmp_path):
    now=dt.datetime(2026,9,4,10)
    old=cached(tmp_path,now)
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        raise OSError('network unavailable')
    local_license.refresh_cached_license_if_due(tmp_path,'http://cloud/api',now=now,refresher=fail)
    local_license.refresh_cached_license_if_due(tmp_path,'http://cloud/api',now=now+dt.timedelta(seconds=20),refresher=fail)
    assert len(calls)==1
    assert local_license.load_license_cache(tmp_path)==old
    state=json.loads((tmp_path/'license_refresh.json').read_text())
    assert state['status']=='network_error'
    assert 'AK-TEST' not in json.dumps(state)


def test_fresh_license_does_not_make_network_call(tmp_path):
    now=dt.datetime(2026,9,4,10)
    value=cached(tmp_path,now)
    value['checked_at']=now.isoformat()
    (tmp_path/'license.json').write_text(json.dumps(value))
    def fail(*a,**kw): raise AssertionError('unnecessary network request')
    local_license.refresh_cached_license_if_due(tmp_path,'http://cloud/api',now=now,refresher=fail)


def test_maintenance_recovers_expired_grace_only_after_real_cloud_success(tmp_path):
    now=dt.datetime(2026,9,4,10)
    value=cached(tmp_path,now)
    value['checked_at']=(now-dt.timedelta(hours=25)).isoformat()
    (tmp_path/'license.json').write_text(json.dumps(value))
    assert not local_license.license_allows_member(value,'U1','DEV-1',now=now)
    def refresh(action,payload,root,api,now):
        response={'success':True,'user':{'id':'U1','status':'active','expire_timestamp':value['expire_timestamp']}}
        return local_license.refresh_cloud_license(action,payload,root,api,now=now,opener=lambda *a,**kw:BytesIO(json.dumps(response).encode()))
    local_license.refresh_cached_license_if_due(tmp_path,'http://cloud/api',now=now,refresher=refresh)
    assert local_license.license_allows_member(local_license.load_license_cache(tmp_path),'U1','DEV-1',now=now)


def test_frontend_retries_only_expired_local_session_and_license_uses_same_helper():
    js=(Path(__file__).parents[1]/'apps/web/assets/app.js').read_text(encoding='utf-8')
    post=js[js.index('function postJSON'):js.index('function openMemberLocalPage')]
    assert "d.error === 'local token required'" in post
    assert '!retried' in post and 'memberIsLocalWorkbench()' in post
    assert "fetch('/index.html'" in post
    license_post=js[js.index('function licenseJSON'):js.index('function renderMemberLicense')]
    assert 'postJSON(MEMBER_LICENSE_API + path, payload)' in license_post


def test_browser_post_recovery_retries_once_and_does_not_relax_token_gate():
    node=shutil.which('node')
    if not node: pytest.skip('Node runtime unavailable')
    js=(Path(__file__).parents[1]/'apps/web/assets/app.js').read_text(encoding='utf-8')
    function=js[js.index('function postJSON'):js.index('function openMemberLocalPage')]
    harness=r'''
let calls=[]; let local=true;
function memberIsLocalWorkbench(){return local;}
async function fetch(url,options){calls.push(url);return url==='/index.html' ? {ok:true} :
 {ok:false,status:403,json:async()=>({error:'local token required'})};}
(async()=>{
 try {await postJSON('license-api/validate',{});}catch(e){}
 if(JSON.stringify(calls)!==JSON.stringify(['license-api/validate','/index.html','license-api/validate']))throw Error('retry bound');
 local=false;calls=[];try{await postJSON('license-api/validate',{});}catch(e){}
 if(calls.length!==1)throw Error('public page must not refresh local cookie');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result=subprocess.run([node,'-e',function+harness],capture_output=True,timeout=10)
    assert result.returncode==0, result.stderr
