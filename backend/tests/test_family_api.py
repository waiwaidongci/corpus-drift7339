import os
os.environ['DATABASE_URL']='sqlite:////tmp/family_http.db'
os.environ['JWT_SECRET']='test-secret';os.environ['SEED_DEMO']='false';os.environ['ARTIFACT_DIR']='/tmp/artifacts'
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.main import app
from src.config.database import Base,engine,SessionLocal
from src.models import *
from src.utils.security import hash_password
from src import worker
class FakeTask:
 def __init__(self):self.calls=[]
 def delay(self,id_):self.calls.append(id_)
fm,fw=FakeTask(),FakeTask()
worker.family_member_task=fm;worker.family_watch_task=fw
Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
client=TestClient(app)
# 登录
r=client.post('/auth/login',json={'email':'analyst@yanyu.demo','password':'Yanyu2026!'})
assert r.status_code==401
# 建用户与快照
import numpy as np
rng=np.random.default_rng(3)
with SessionLocal() as db:
 u=User(email='analyst@yanyu.demo',name='研',role='analyst',password_hash=hash_password('Yanyu2026!'));admin=User(email='admin@yanyu.demo',name='管',role='admin',password_hash=hash_password('Yanyu2026!'))
 db.add_all([u,admin]);db.flush()
 for kind,name in [('reference','R'),('candidate','C')]:
  s=CorpusSnapshot(name=name,kind=kind,filename=name+'.csv');db.add(s);db.flush()
  for i in range(80):
   db.add(Utterance(snapshot_id=s.id,reference=f'{name}-{i}',features={'duration':round(float(rng.lognormal(1,.5)),4),'noise':round(float(rng.normal(10,2)),4),'token_rate':round(float(rng.normal(5,1)),4),'language':['zh','en'][i%2],'device':['studio','mobile'][i%3>1]}))
 db.commit()
 rid=db.scalar(select(CorpusSnapshot.id).where(CorpusSnapshot.kind=='reference'))
 cid=db.scalar(select(CorpusSnapshot.id).where(CorpusSnapshot.kind=='candidate'))
r=client.post('/auth/login',json={'email':'analyst@yanyu.demo','password':'Yanyu2026!'})
token=r.json()['token'];H={'Authorization':'Bearer '+token}
# 建族
payload={'family_key':'http-key','name':'HTTP校对族','reference_id':rid,'candidate_id':cid,'features':['duration','noise','token_rate','language','device'],'bins':4,'smoothing':0.5,'fdr_alpha':0.05,'slices':[{'label':'全量'},{'label':'中文','language':'zh'},{'label':'英文移动','language':'en','device':'mobile'}]}
r=client.post('/families',json=payload,headers=H);assert r.status_code==201,r.text
fam=r.json();assert fam['status']=='queued' and fam['version']==1
assert len(fm.calls)==3 and len(fw.calls)==1
fid=fam['id']
# 第二版
payload2=dict(payload,slices=[{'label':'全量'}]);r=client.post('/families',json=payload2,headers=H);assert r.status_code==201
assert r.json()['version']==2
# 非法：重复切片
bad=dict(payload,slices=[{'label':'a','language':'zh'},{'label':'b','language':'zh'}])
r=client.post('/families',json=bad,headers=H);assert r.status_code==422
# 同步跑完v1成员
with SessionLocal() as db:
 from src.services import families
 for m in families.list_members(db,fid):families.run_member(db,m['id'])
r=client.get(f'/families/{fid}',headers=H);assert r.status_code==200 and r.json()['status']=='published'
r=client.get(f'/families/{fid}/members',headers=H);members=r.json()
assert [m['slice_index'] for m in members]==[0,1,2] and all(m['status']=='succeeded' for m in members)
r=client.get(f'/families/{fid}/findings',headers=H);findings=r.json()
assert len(findings)==15 and all(f['family_id']==fid for f in findings)
# 统一BH族 m = 3切片×3连续特征
tf=r.json() if False else client.get(f'/families/{fid}',headers=H).json()['result']['test_family']
assert tf['m']==9 and len(tf['keys'])==9
# 计划：未发布v2被拒；v1成功
v2=client.get('/families',headers=H).json();v2id=max(x['id'] for x in v2)
one_fid=findings[0]['id']
r=client.post('/plans',json={'family_id':v2id,'name':'p','finding_ids':[one_fid],'target_slice':'x','sample_target':200,'rationale':'r'},headers=H)
assert r.status_code==422
r=client.post('/plans',json={'family_id':fid,'name':'族计划','finding_ids':[one_fid],'target_slice':'zh','sample_target':200,'rationale':'r'},headers=H)
assert r.status_code==201,r.text;plan_id=r.json()['id']
# 越权：viewer不可建族、不可审稿
with SessionLocal() as db:
 db.add(User(email='v@x.demo',name='观',role='viewer',password_hash=hash_password('Yanyu2026!')));db.commit()
vt=client.post('/auth/login',json={'email':'v@x.demo','password':'Yanyu2026!'}).json()['token']
assert client.post('/families',json=payload,headers={'Authorization':'Bearer '+vt}).status_code==403
assert client.get('/families',headers={'Authorization':'Bearer '+vt}).status_code==200
# admin审稿 + viewer导出获批CSV
at=client.post('/auth/login',json={'email':'admin@yanyu.demo','password':'Yanyu2026!'}).json()['token']
AH={'Authorization':'Bearer '+at}
r=client.patch(f'/plans/{plan_id}/approval',json={'status':'approved','review_note':'核对来源后补采'},headers=AH);assert r.status_code==200
r=client.get(f'/plans/{plan_id}/export',headers={'Authorization':'Bearer '+vt});assert r.status_code==200 and '统一BH q' in r.content.decode()
# 未登录401
assert client.get('/families').status_code==401
print('ALL HTTP API TESTS PASSED')
