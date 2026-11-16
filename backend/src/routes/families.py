from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers
from src.schemas.family import FamilyInput
from src.services import families
from src.utils.serialize import row
router=APIRouter()
@router.get('/families')
def index(db:Session=Depends(get_db),user=Depends(current_user)):return families.list_families(db)
@router.post('/families',status_code=201)
def create(data:FamilyInput,db:Session=Depends(get_db),user=Depends(writers)):return families.create_family(db,data,user)
@router.get('/families/{id}')
def detail(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return row(families.get_family(db,id))
@router.get('/families/{id}/members')
def members(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return families.list_members(db,id)
@router.get('/families/{id}/findings')
def findings(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return families.list_family_findings(db,id)
