from pydantic import BaseModel,Field,model_validator
from typing import Literal
class PlanInput(BaseModel):
 run_id:int|None=Field(default=None,gt=0)
 family_id:int|None=Field(default=None,gt=0)
 name:str=Field(min_length=1,max_length=100)
 finding_ids:list[int]=Field(min_length=1,max_length=200)
 target_slice:str=Field(min_length=1,max_length=160)
 sample_target:int=Field(ge=20,le=10000)
 rationale:str=Field(min_length=1,max_length=500)
 @model_validator(mode='after')
 def single_source(self):
  if (self.run_id is None)==(self.family_id is None):raise ValueError('补采计划须且只能引用单次比较或一个校对族版本')
  if len(set(self.finding_ids))!=len(self.finding_ids):raise ValueError('发现不得重复')
  return self
class ApprovalInput(BaseModel):
 status:Literal['approved','rejected']
 review_note:str=Field(min_length=1,max_length=500)
