import json
from pathlib import Path
from sqlalchemy import select
from celery import Celery
from src.config.database import SessionLocal
from src.config.settings import REDIS_URL,ARTIFACT_DIR
from src.models import ComparisonRun,DriftFinding,ComparisonFamily,FamilyMember
from src.services.snapshots import get_utterances
from src.services.comparison import compare_snapshots
from src.services.families import run_member,finalize_family
from src.services.audit import record
app=Celery('corpus_drift',broker=REDIS_URL,backend=REDIS_URL)
app.conf.update(task_track_started=True,worker_prefetch_multiplier=1,task_acks_late=True)
@app.task(name='corpus.compare',soft_time_limit=120,time_limit=150)
def compare_run(id):
 with SessionLocal() as db:
  run=db.get(ComparisonRun,id)
  if not run or run.status=='succeeded':return
  run.status='running';db.commit()
  try:
   result=compare_snapshots(get_utterances(db,run.reference_id),get_utterances(db,run.candidate_id),run.config)
   for f in result['findings']:
    if not db.scalar(select(DriftFinding).where(DriftFinding.run_id==id,DriftFinding.feature==f['feature'])):db.add(DriftFinding(run_id=id,**f))
   db.flush();Path(ARTIFACT_DIR).mkdir(parents=True,exist_ok=True);Path(ARTIFACT_DIR,f'comparison-{id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));run.result={k:v for k,v in result.items() if k!='findings'};run.status='succeeded';run.error=None;db.commit();record(db,'worker','comparison.succeeded',{'run_id':id,'findings':len(result['findings'])})
  except Exception as e:
   db.rollback();run=db.get(ComparisonRun,id);run.status='failed';run.error=str(e)[:1000];db.commit();record(db,'worker','comparison.failed',{'run_id':id,'error':run.error})

@app.task(name='corpus.family_member',soft_time_limit=120,time_limit=150,bind=True,max_retries=2,default_retry_delay=5)
def family_member_task(self,member_id):
 with SessionLocal() as db:
  try:run_member(db,member_id)
  except Exception as e:
   db.rollback()
   try:raise self.retry(exc=e)
   except Exception:
    with SessionLocal() as db2:
     member=db2.get(FamilyMember,member_id)
     if member and member.status not in ('succeeded','failed'):
      member.status='failed';member.error=f'切片任务执行异常：{e}'[:1000];db2.commit()
      finalize_family(db2,member.family_id)

@app.task(name='corpus.family_watch',soft_time_limit=60,time_limit=90,bind=True,max_retries=60,default_retry_delay=5)
def family_watch_task(self,family_id):
 with SessionLocal() as db:
  family=db.get(ComparisonFamily,family_id)
  if not family:return
  if family.status in ('published','failed'):return
  status=finalize_family(db,family_id)
  if status not in ('published','failed'):raise self.retry()
