from pydantic import BaseModel,Field,model_validator
from src.constants.features import FEATURES
class SliceInput(BaseModel):
 label:str=Field(min_length=1,max_length=160)
 language:str|None=Field(default=None,max_length=40)
 device:str|None=Field(default=None,max_length=40)
 @model_validator(mode='after')
 def validate_slice(self):
  self.language=(self.language or '').strip() or None
  self.device=(self.device or '').strip() or None
  if self.language in ('__NEW__','__MISSING__') or self.device in ('__NEW__','__MISSING__'):raise ValueError('保留桶名不得作为切片值')
  return self
class FamilyInput(BaseModel):
 family_key:str=Field(min_length=1,max_length=80)
 name:str=Field(min_length=1,max_length=100)
 reference_id:int=Field(gt=0)
 candidate_id:int=Field(gt=0)
 features:list[str]=Field(min_length=1,max_length=5)
 bins:int=Field(ge=2,le=10)
 smoothing:float=Field(gt=0,le=10,allow_inf_nan=False)
 fdr_alpha:float=Field(gt=0,le=.2,allow_inf_nan=False)
 slices:list[SliceInput]=Field(min_length=1,max_length=10)
 @model_validator(mode='after')
 def validate_config(self):
  if self.reference_id==self.candidate_id:raise ValueError('参考/候选不能是同一快照')
  if len(set(self.features))!=len(self.features) or not set(self.features)<=set(FEATURES):raise ValueError('特征不得重复或未知')
  pairs=[(s.language,s.device) for s in self.slices]
  if len(set(pairs))!=len(pairs):raise ValueError('切片清单不得重复')
  return self
