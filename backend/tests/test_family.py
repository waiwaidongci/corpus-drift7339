import os
os.environ['DATABASE_URL']='sqlite:////tmp/family_test.db'
os.environ['JWT_SECRET']='test-secret'
os.environ['ARTIFACT_DIR']='/tmp/artifacts'
os.environ['SEED_DEMO']='false'
import json
import numpy as np
from sqlalchemy import select
from src.config.database import Base,engine,SessionLocal
from src.models import *
from src.services.snapshots import get_utterances
from src.services.comparison import compare_snapshots,compare_slice,apply_family_correction
from src.services.fingerprint import snapshot_checksum
from src.services import families,plans
from src.schemas.family import FamilyInput,SliceInput
from src.schemas.plan import PlanInput
from src.constants.enums import FamilyStatus,MemberStatus,PlanStatus,RunStatus

# 测试环境无Redis：把Celery任务替换为同步假任务，仅记录派发
from src import worker
class _FakeTask:
 def __init__(self):self.dispatched=[]
 def delay(self,id_):self.dispatched.append(id_)
fake_member,fake_watch=_FakeTask(),_FakeTask()
worker.family_member_task=fake_member;worker.family_watch_task=fake_watch

Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
rng=np.random.default_rng(7)

def make_rows(prefix,n,shift=False):
 rows=[]
 for i in range(n):
  dur=float(rng.lognormal(np.log(2.0 if shift else 3.0),.5))
  rows.append({'reference':f'{prefix}-{i:04d}','features':{
   'duration':round(dur,5) if rng.random()>.03 else None,
   'noise':round(float(rng.normal(10,3)),5),
   'token_rate':round(float(rng.normal(5,.8)),5),
   'language':str(rng.choice(['zh','en','ja'],p=[.6,.3,.1])),
   'device':str(rng.choice(['studio','mobile'],p=[.5,.5]))}})
 return rows

with SessionLocal() as db:
 user=User(email='a@x.demo',name='测试员',role='analyst',password_hash='x');db.add(user);db.commit()
 ref_snap=CorpusSnapshot(name='ref',kind='reference',filename='r.csv');cand_snap=CorpusSnapshot(name='cand',kind='candidate',filename='c.csv')
 db.add_all([ref_snap,cand_snap]);db.flush()
 db.add_all([Utterance(snapshot_id=ref_snap.id,**r) for r in make_rows('REF',300)])
 db.add_all([Utterance(snapshot_id=cand_snap.id,**r) for r in make_rows('NEW',300,shift=True)])
 db.commit()
 ref_id,cand_id,user_id=ref_snap.id,cand_snap.id,user.id

# 1) 单次比较路径未变：重构后 compare_snapshots 仍返回原结构
with SessionLocal() as db:
 ref=get_utterances(db,ref_id);cand=get_utterances(db,cand_id)
 cfg={'features':['duration','noise','token_rate','language','device'],'bins':6,'smoothing':.5,'fdr_alpha':.05,'slice_language':None,'slice_device':None}
 out=compare_snapshots(ref,cand,cfg)
 assert set(out)>={'fingerprint','findings','test_family','reference_n','candidate_n'}
 assert out['test_family']['m']==3
 assert all(f['metrics']['q_value'] is not None for f in out['findings'] if f['feature'] in ('duration','noise','token_rate'))
 print('T1 single-run comparison OK; n=',out['reference_n'],out['candidate_n'])

# 2) 建族 + 并发成员全部成功 → 统一发布，BH族覆盖全部切片×连续特征
def build_family_input(slices,key='k1',alpha=.05,bins=6,smoothing=.5,features=None):
 return FamilyInput(family_key=key,name='校对族',reference_id=ref_id,candidate_id=cand_id,
  features=features or ['duration','noise','token_rate','language','device'],bins=bins,smoothing=smoothing,fdr_alpha=alpha,
  slices=[SliceInput(label=l,language=la,device=dv) for l,la,dv in slices])

with SessionLocal() as db:
 user=db.get(User,user_id)
 data=build_family_input([('全量',None,None),('中文', 'zh',None),('移动端',None,'mobile'),('中文移动端','zh','mobile')])
 fam_row=families.create_family(db,data,user)
 fid=fam_row['id']
 # 模拟worker：并发等价地逐成员执行服务层任务体
 members=families.list_members(db,fid)
 for m in members:families.run_member(db,m['id'])
 fam=db.get(ComparisonFamily,fid)
 assert fam.status==FamilyStatus.PUBLISHED,fam.error
 assert fam.published_at is not None
 tf=fam.result['test_family']
 assert tf['m']==4*3,tf
 # 每个成员的每个连续特征都拿到统一族q，且成员结果q在发布前为None（原值）
 findings=families.list_family_findings(db,fid)
 assert len(findings)==4*5
 qs=[f['metrics']['q_value'] for f in findings if f['feature']=='duration']
 assert all(q is not None for q in qs)
 # 统一校正q与手工族BH一致
 raw=[]
 members2=families.list_members(db,fid)
 for m in members2:
  r=m['result']
  for ci in r['continuous_index']:raw.append(r['findings'][ci]['metrics']['p_value'])
 from src.services.multiple_testing import benjamini_hochberg
 expected=benjamini_hochberg(raw)
 got=sorted(f['metrics']['q_value'] for f in findings if f['metrics']['p_value'] is not None)
 assert np.allclose(got,sorted(expected),atol=1e-12)
 print('T2 family publish OK; family m=',tf['m'],'findings=',len(findings))

# 3) 任一成员失败 → 整族保持未发布，失败原因可追溯；无FamilyFinding写入
with SessionLocal() as db:
 user=db.get(User,user_id)
 data=build_family_input([('全量',None,None),('极稀有切片','ko','wearable')],key='k2')
 fam_row=families.create_family(db,data,user);fid2=fam_row['id']
 for m in families.list_members(db,fid2):families.run_member(db,m['id'])
 fam=db.get(ComparisonFamily,fid2)
 assert fam.status==FamilyStatus.FAILED
 assert '极稀有切片' in fam.error and '不足' in fam.error
 failed_member=[m for m in families.list_members(db,fid2) if m['status']=='failed']
 assert failed_member and failed_member[0]['error']
 assert families.list_family_findings(db,fid2)==[]
 print('T3 member failure blocks publish OK; error=',fam.error)

# 4) 未发布/失败族不能建计划；已发布族可以；单次比较计划仍可用
with SessionLocal() as db:
 user=db.get(User,user_id)
 ok_fid=fid
 good_finding=db.scalar(select(FamilyFinding.id).where(FamilyFinding.family_id==ok_fid).limit(1))
 try:
  plans.create_plan(db,PlanInput(family_id=fid2,name='p',finding_ids=[good_finding],target_slice='x',sample_target=200,rationale='r'),user)
  raise AssertionError('应拒绝失败族')
 except Exception as e:assert '已发布' in str(e),str(e)
 plan_row=plans.create_plan(db,PlanInput(family_id=ok_fid,name='族计划',finding_ids=[good_finding],target_slice='zh/mobile',sample_target=200,rationale='r'),user)
 assert plan_row['family_id']==ok_fid and plan_row['run_id'] is None
 # 单次比较路径
 run=ComparisonRun(name='r',reference_id=ref_id,candidate_id=cand_id,config=cfg,status=RunStatus.SUCCEEDED,creator_id=user.id)
 db.add(run);db.flush();db.add(DriftFinding(run_id=run.id,feature='duration',status='quiet',metrics={'psi':0,'js':0,'p_value':.5,'q_value':.5,'fdr_reject':False}));db.commit()
 dfid=db.scalar(select(DriftFinding.id).where(DriftFinding.run_id==run.id))
 rp=plans.create_plan(db,PlanInput(run_id=run.id,name='单次计划',finding_ids=[dfid],target_slice='x',sample_target=200,rationale='r'),user)
 assert rp['run_id']==run.id and rp['family_id'] is None
 # 二选一校验
 try:
  plans.create_plan(db,PlanInput(run_id=run.id,family_id=ok_fid,name='x',finding_ids=[dfid],target_slice='x',sample_target=200,rationale='r'),user)
  raise AssertionError('应拒绝双来源')
 except Exception as e:assert '只能引用' in str(e)
 print('T4 plan gating OK')

# 5) 版本化：改切片/参数生成新版本；旧任务晚到不能写入新版本
with SessionLocal() as db:
 user=db.get(User,user_id)
 d1=build_family_input([('全量',None,None)],key='vk')
 v1=families.create_family(db,d1,user);assert v1['version']==1
 d2=build_family_input([('全量',None,None),('中文','zh',None)],key='vk')
 v2=families.create_family(db,d2,user);assert v2['version']==2
 # v1的旧成员任务“晚到”：重新执行v1成员只写v1，v2成员/发现数量不受影响
 v1_members=families.list_members(db,v1['id'])
 for m in v1_members:families.run_member(db,m['id'])
 v2_members=families.list_members(db,v2['id'])
 for m in v2_members:families.run_member(db,m['id'])
 f1=db.get(ComparisonFamily,v1['id']);f2=db.get(ComparisonFamily,v2['id'])
 assert f1.status==FamilyStatus.PUBLISHED and f2.status==FamilyStatus.PUBLISHED
 assert len(families.list_family_findings(db,v1['id']))==5
 assert len(families.list_family_findings(db,v2['id']))==10
 # 直接用旧member_id调用也不会触碰v2
 old_mid=v1_members[0]['id']
 families.run_member(db,old_mid)
 assert db.get(FamilyMember,old_mid).family_id==v1['id']
 assert len(families.list_family_findings(db,v2['id']))==10
 print('T5 versioning and stale-task isolation OK')

# 6) 旧版本结论与计划仍可追溯；计划只能引用已发布版本（v2发布后建的计划指向v2，v1计划保留）
with SessionLocal() as db:
 user=db.get(User,user_id)
 v1_fid=db.scalar(select(FamilyFinding.id).where(FamilyFinding.family_id==v1['id']).limit(1))
 p_old=plans.create_plan(db,PlanInput(family_id=v1['id'],name='旧版计划',finding_ids=[v1_fid],target_slice='a',sample_target=200,rationale='r'),user)
 assert db.get(ResamplingPlan,p_old['id']).family_id==v1['id']
 assert db.get(ComparisonFamily,v1['id']).version==1
 print('T6 traceability OK')

# 7) 冻结证据：快照checksum、族指纹、切片/参数不可变
with SessionLocal() as db:
 f=db.get(ComparisonFamily,v2['id'])
 assert len(f.reference_fingerprint)==64 and len(f.candidate_fingerprint)==64
 assert f.reference_fingerprint==snapshot_checksum(get_utterances(db,ref_id))
 assert f.result['fingerprint'] and f.slices==[{'label':'全量','language':None,'device':None},{'label':'中文','language':'zh','device':None}]
 print('T7 frozen checksums OK')

# 8) 幂等：成员重复执行、finalize重复调用不产生重复发现
with SessionLocal() as db:
 for m in families.list_members(db,v2['id']):
  families.run_member(db,m['id']);families.run_member(db,m['id'])
 families.finalize_family(db,v2['id'])
 assert len(families.list_family_findings(db,v2['id']))==10
 print('T8 idempotency OK')

# 9) 全量切片与单次比较数值一致（同切片、同配置下原始PSI/JS/KS/p一致）
with SessionLocal() as db:
 single=compare_snapshots(get_utterances(db,ref_id),get_utterances(db,cand_id),cfg)
 part=compare_slice(get_utterances(db,ref_id),get_utterances(db,cand_id),cfg,{})
 sf={f['feature']:f['metrics'] for f in single['findings']}
 pf={f['feature']:f['metrics'] for f in part['findings']}
 for k,m in sf.items():
  for key in ('psi','js','ks_statistic','p_value','reference_counts','candidate_counts'):
   assert m[key]==pf[k][key],(k,key)
 print('T9 slice/single numeric parity OK')
print('ALL BACKEND TESTS PASSED')
