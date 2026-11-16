from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,JSON,ForeignKey,DateTime,UniqueConstraint,Integer
from datetime import datetime,timezone
from src.config.database import Base
class ComparisonFamily(Base):
 __tablename__='comparison_families'
 __table_args__=(UniqueConstraint('family_key','version'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 family_key:Mapped[str]=mapped_column(String(80),index=True)
 version:Mapped[int]=mapped_column(Integer,default=1)
 name:Mapped[str]=mapped_column(String(100))
 reference_id:Mapped[int]=mapped_column(ForeignKey('corpus_snapshots.id'))
 candidate_id:Mapped[int]=mapped_column(ForeignKey('corpus_snapshots.id'))
 # 创建时冻结：两份快照校验、切片清单、特征与阈值，之后不可变
 config:Mapped[dict]=mapped_column(JSON)
 slices:Mapped[list]=mapped_column(JSON)
 reference_fingerprint:Mapped[str]=mapped_column(String(64))
 candidate_fingerprint:Mapped[str]=mapped_column(String(64))
 status:Mapped[str]=mapped_column(String(20),default='queued')
 result:Mapped[dict]=mapped_column(JSON,default=dict)
 error:Mapped[str|None]=mapped_column(String(1000),nullable=True)
 creator_id:Mapped[int]=mapped_column(ForeignKey('users.id'))
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
 published_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class FamilyMember(Base):
 __tablename__='family_members'
 __table_args__=(UniqueConstraint('family_id','slice_index'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 family_id:Mapped[int]=mapped_column(ForeignKey('comparison_families.id'),index=True)
 slice_index:Mapped[int]=mapped_column(Integer)
 label:Mapped[str]=mapped_column(String(160))
 slice_filter:Mapped[dict]=mapped_column(JSON)
 status:Mapped[str]=mapped_column(String(20),default='queued')
 result:Mapped[dict]=mapped_column(JSON,default=dict)
 error:Mapped[str|None]=mapped_column(String(1000),nullable=True)
 attempts:Mapped[int]=mapped_column(Integer,default=0)
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
 updated_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class FamilyFinding(Base):
 __tablename__='family_findings'
 __table_args__=(UniqueConstraint('family_id','member_id','feature'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 family_id:Mapped[int]=mapped_column(ForeignKey('comparison_families.id'),index=True)
 member_id:Mapped[int]=mapped_column(ForeignKey('family_members.id'))
 feature:Mapped[str]=mapped_column(String(50))
 status:Mapped[str]=mapped_column(String(20))
 metrics:Mapped[dict]=mapped_column(JSON)
