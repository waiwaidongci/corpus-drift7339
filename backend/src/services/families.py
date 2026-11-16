import json
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy import select,func
from fastapi import HTTPException
from src.models import ComparisonFamily,FamilyMember,FamilyFinding,CorpusSnapshot
from src.utils.serialize import row
from src.constants.enums import FamilyStatus,MemberStatus
from src.services.snapshots import get_utterances
from src.services.comparison import compare_slice,apply_family_correction
from src.services.fingerprint import snapshot_checksum,family_fingerprint
from src.config.settings import ARTIFACT_DIR
from .audit import record

def list_families(db):return [row(x) for x in db.scalars(select(ComparisonFamily).order_by(ComparisonFamily.id.desc()))]
def get_family(db,id):
 obj=db.get(ComparisonFamily,id)
 if not obj:raise HTTPException(404,'校对族不存在')
 return obj
def list_members(db,family_id):
 get_family(db,family_id)
 return [row(x) for x in db.scalars(select(FamilyMember).where(FamilyMember.family_id==family_id).order_by(FamilyMember.slice_index))]
def list_family_findings(db,family_id):
 get_family(db,family_id)
 return [row(x) for x in db.scalars(select(FamilyFinding).where(FamilyFinding.family_id==family_id).order_by(FamilyFinding.member_id,FamilyFinding.id))]

def create_family(db,data,user,dispatch=True):
 ref=db.get(CorpusSnapshot,data.reference_id);cand=db.get(CorpusSnapshot,data.candidate_id)
 if not ref or not cand:raise HTTPException(404,'快照不存在')
 if ref.kind!='reference' or cand.kind!='candidate':raise HTTPException(422,'请按参考/候选快照类型选择')
 reference=get_utterances(db,ref.id);candidate=get_utterances(db,cand.id)
 ref_checksum=snapshot_checksum(reference);cand_checksum=snapshot_checksum(candidate)
 last=db.scalar(select(func.max(ComparisonFamily.version)).where(ComparisonFamily.family_key==data.family_key))
 version=int(last or 0)+1
 config={'features':data.features,'bins':data.bins,'smoothing':data.smoothing,'fdr_alpha':data.fdr_alpha}
 slices=[{'label':s.label,'language':s.language,'device':s.device} for s in data.slices]
 fp=family_fingerprint(reference,candidate,config,slices)
 family=ComparisonFamily(family_key=data.family_key,version=version,name=data.name,reference_id=ref.id,candidate_id=cand.id,config=config,slices=slices,reference_fingerprint=ref_checksum,candidate_fingerprint=cand_checksum,status=FamilyStatus.QUEUED,creator_id=user.id,result={'fingerprint':fp})
 db.add(family);db.flush()
 for index,sl in enumerate(slices):
  db.add(FamilyMember(family_id=family.id,slice_index=index,label=sl['label'],slice_filter={'language':sl['language'],'device':sl['device']},status=MemberStatus.QUEUED))
 db.commit();member_ids=list(db.scalars(select(FamilyMember.id).where(FamilyMember.family_id==family.id).order_by(FamilyMember.slice_index)))
 # 切片任务并发分发；队列不可用时整族保持未发布
 from src.worker import family_member_task,family_watch_task
 if dispatch:
  try:
   for member_id in member_ids:family_member_task.delay(member_id)
   family_watch_task.delay(family.id)
  except Exception:
   family=db.get(ComparisonFamily,family.id);family.status=FamilyStatus.FAILED;family.error='队列不可用';db.commit();raise HTTPException(503,family.error)
 record(db,user.email,'family.queued',{'family_id':family.id,'family_key':family.family_key,'version':version,'members':len(member_ids),'dispatched':dispatch})
 return row(db.get(ComparisonFamily,family.id))

def run_member(db,member_id):
 """单个切片任务体：只按member_id定位，天然无法写入后续新版本。"""
 member=db.get(FamilyMember,member_id)
 if not member:return
 family=db.get(ComparisonFamily,member.family_id)
 if family.status in (FamilyStatus.PUBLISHED,FamilyStatus.FAILED):return
 if member.status!=MemberStatus.SUCCEEDED:
  member.attempts+=1;member.status=MemberStatus.RUNNING;member.error=None
  if family.status==FamilyStatus.QUEUED:family.status=FamilyStatus.RUNNING
  member.updated_at=datetime.now(timezone.utc);db.commit()
  try:
   reference=get_utterances(db,family.reference_id);candidate=get_utterances(db,family.candidate_id)
   result=compare_slice(reference,candidate,family.config,member.slice_filter)
   member.result=result;member.status=MemberStatus.SUCCEEDED;member.error=None;member.updated_at=datetime.now(timezone.utc);db.commit()
  except Exception as e:
   db.rollback();member=db.get(FamilyMember,member_id);member.status=MemberStatus.FAILED;member.error=str(e)[:1000];member.updated_at=datetime.now(timezone.utc);db.commit()
   record(db,'worker','family.member_failed',{'family_id':member.family_id,'member_id':member_id,'slice':member.label,'error':member.error})
 # 幂等：任务重试（含旧版本晚到）也会再尝试发布，已发布/失败直接返回
 finalize_family(db,member.family_id)

def finalize_family(db,family_id):
 """所有成员齐备后一次发布统一校正；任一失败则整族保持未发布。"""
 family=db.get(ComparisonFamily,family_id)
 if not family or family.status in (FamilyStatus.PUBLISHED,FamilyStatus.FAILED):return family.status if family else None
 members=list(db.scalars(select(FamilyMember).where(FamilyMember.family_id==family_id).order_by(FamilyMember.slice_index)))
 failed=next((m for m in members if m.status==MemberStatus.FAILED),None)
 if failed:
  family.status=FamilyStatus.FAILED;family.error=f"切片「{failed.label}」失败：{failed.error}";db.commit()
  record(db,'worker','family.failed',{'family_id':family_id,'failed_slice':failed.label,'error':failed.error});return family.status
 if any(m.status!=MemberStatus.SUCCEEDED for m in members):return family.status
 # 行锁内做幂等发布，防止并发成员任务重复写入
 locked=db.scalar(select(ComparisonFamily).where(ComparisonFamily.id==family_id).with_for_update())
 if locked.status in (FamilyStatus.PUBLISHED,FamilyStatus.FAILED):return locked.status
 slice_results=[m.result for m in members]
 test_family=apply_family_correction(slice_results,family.config['features'],family.config['fdr_alpha'])
 for member,result in zip(members,slice_results):
  for f in result['findings']:
   exists=db.scalar(select(FamilyFinding.id).where(FamilyFinding.family_id==family_id,FamilyFinding.member_id==member.id,FamilyFinding.feature==f['feature']))
   if not exists:db.add(FamilyFinding(family_id=family_id,member_id=member.id,feature=f['feature'],status=f['status'],metrics=f['metrics']))
 payload={'fingerprint':family.result.get('fingerprint'),'reference_checksum':family.reference_fingerprint,'candidate_checksum':family.candidate_fingerprint,'test_family':test_family,'member_count':len(members),'member_ids':[m.id for m in members]}
 Path(ARTIFACT_DIR).mkdir(parents=True,exist_ok=True)
 Path(ARTIFACT_DIR,f'family-{family_id}-v{family.version}.json').write_text(json.dumps({'family':row(family),'members':[row(m) for m in members],'result':payload},ensure_ascii=False,allow_nan=False))
 family.result=payload;family.status=FamilyStatus.PUBLISHED;family.error=None;family.published_at=datetime.now(timezone.utc);db.commit()
 record(db,'worker','family.published',{'family_id':family_id,'version':family.version,'tests':test_family['m'],'members':len(members)})
 return family.status
