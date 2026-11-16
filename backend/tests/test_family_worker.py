import os
os.environ['DATABASE_URL']='sqlite:////tmp/family_worker.db'
os.environ['JWT_SECRET']='test-secret';os.environ['ARTIFACT_DIR']='/tmp/artifacts';os.environ['SEED_DEMO']='false'
import numpy as np
from sqlalchemy import select
from src.config.database import Base,engine,SessionLocal
from src.models import *
from src import worker
from src.services import families
from src.schemas.family import FamilyInput,SliceInput
from src.constants.enums import FamilyStatus

Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
rng=np.random.default_rng(11)
with SessionLocal() as db:
 u=User(email='a@x.demo',name='t',role='analyst',password_hash='x');db.add(u);db.flush()
 for kind,name in [('reference','R'),('candidate','C')]:
  s=CorpusSnapshot(name=name,kind=kind,filename=name+'.csv');db.add(s);db.flush()
  for i in range(120):
   db.add(Utterance(snapshot_id=s.id,reference=f'{name}-{i:03d}',features={
    'duration':round(float(rng.lognormal(1,.5)),4),'noise':round(float(rng.normal(10,2)),4),
    'token_rate':round(float(rng.normal(5,1)),4),'language':['zh','en'][i%2],'device':['studio','mobile'][i%3>1]}))
 db.commit()
 rid=db.scalar(select(CorpusSnapshot.id).where(CorpusSnapshot.kind=='reference'))
 cid=db.scalar(select(CorpusSnapshot.id).where(CorpusSnapshot.kind=='candidate'))
 uid=u.id

# 关闭真实retry：让retry直接抛回，触发任务体的兜底失败分支
def no_retry(exc=None,*a,**k):raise RuntimeError('retry exhausted')
worker.family_member_task.retry=no_retry
worker.family_watch_task.retry=no_retry
# 无Redis环境：保留真实任务对象（.run可用），仅屏蔽派发
worker.family_member_task.delay=lambda id_:None
worker.family_watch_task.delay=lambda id_:None

with SessionLocal() as db:
 user=db.get(User,uid)
 data=FamilyInput(family_key='w1',name='w',reference_id=rid,candidate_id=cid,
  features=['duration','noise','token_rate','language','device'],bins=4,smoothing=.5,fdr_alpha=.05,
  slices=[SliceInput(label='全量'),SliceInput(label='中文',language='zh')])
 fam=families.create_family(db,data,user);fid=fam['id']
 mids=[m['id'] for m in families.list_members(db,fid)]

# 直接调用Celery任务入口（成功路径）
for mid in mids:worker.family_member_task.run(mid)
with SessionLocal() as db:
 f=db.get(ComparisonFamily,fid)
 assert f.status==FamilyStatus.PUBLISHED,f.status
 assert f.result['test_family']['m']==2*3
 print('W1 celery task success + auto-finalize OK')

# 异常路径：篡改成员配置使比较抛错，任务兜底应标失败并阻止发布
with SessionLocal() as db:
 data2=FamilyInput(family_key='w2',name='w2',reference_id=rid,candidate_id=cid,
  features=['duration'],bins=4,smoothing=.5,fdr_alpha=.05,slices=[SliceInput(label='全量'),SliceInput(label='稀有',language='ko')])
 fam2=families.create_family(db,data2,db.get(User,uid));fid2=fam2['id']
 mids2=[m['id'] for m in families.list_members(db,fid2)]
for mid in mids2:worker.family_member_task.run(mid)
with SessionLocal() as db:
 f=db.get(ComparisonFamily,fid2)
 assert f.status==FamilyStatus.FAILED and f.error
 assert families.list_family_findings(db,fid2)==[]
 print('W2 celery failure path blocks publish OK:',f.error[:40])

# watcher在已终态时直接返回；未终态时推进
with SessionLocal() as db:
 assert worker.family_watch_task.run(fid) is None
 assert worker.family_watch_task.run(fid2) is None
 print('W3 watcher terminal no-op OK')
print('ALL WORKER TASK TESTS PASSED')
