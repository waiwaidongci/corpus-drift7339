import hashlib,json
from src.constants.features import FEATURES
def _rows(items):return [{'id':r['id'],'reference':r['reference'],'features':{k:r['features'][k] for k in sorted(FEATURES)}} for r in sorted(items,key=lambda r:r['reference'])]
def snapshot_checksum(rows):
 # 冻结单份快照：覆盖全部片段id/reference/五特征（含null），按reference稳定排序
 return hashlib.sha256(json.dumps(_rows(rows),sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
def family_fingerprint(reference,candidate,config,slices):
 # 校对族指纹：两份快照校验、冻结切片清单、特征与阈值、族版本算法
 data={'reference':_rows(reference),'candidate':_rows(candidate),'config':config,'slices':slices,'algorithm':'frozen-family-psi-js-ks-bh-v1'}
 return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
def fingerprint(reference,candidate,config):
 data={'reference':_rows(reference),'candidate':_rows(candidate),'config':config,'algorithm':'frozen-quantile-psi-js-ks-bh-v1'}
 return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
