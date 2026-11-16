import numpy as np
from scipy.stats import ks_2samp
from src.constants.features import FEATURES,NUMERIC
from .binning import freeze_numeric,freeze_categorical,count_bins
from .distributions import divergence
from .multiple_testing import benjamini_hochberg
from .fingerprint import fingerprint

def _validate_inputs(reference,candidate,config):
 if not reference or not candidate:raise ValueError('参考和候选快照均不得为空')
 features=config['features']
 if not features or len(set(features))!=len(features) or not set(features)<=set(FEATURES):raise ValueError('未知或重复特征')
 if not 2<=config['bins']<=10 or not 0<config['fdr_alpha']<=.2:raise ValueError('分箱数/FDR范围不合法')
 for rows in (reference,candidate):
  if len({r['reference'] for r in rows})!=len(rows):raise ValueError('片段reference重复')
  if any(set(r['features'])!=set(FEATURES) for r in rows):raise ValueError('特征模式不合法')

def _select_slice(rows,slice_filter):
 def selected(row):return all(slice_filter.get(key) in (None,'',row['features'][key]) for key in ('language','device'))
 return [r for r in rows if selected(r)]

def compare_slice(reference,candidate,config,slice_filter=None):
 """对单个切片计算分箱、散度与连续KS原p；不做任何多重检验校正。"""
 slice_filter=slice_filter or {}
 ref=_select_slice(reference,slice_filter);cand=_select_slice(candidate,slice_filter)
 if len(ref)<5 or len(cand)<5:raise ValueError('空切片或样本不足：参考和候选切片各至少5片段')
 findings=[];continuous=[]
 for feature in config['features']:
  a=[r['features'][feature] for r in ref];b=[r['features'][feature] for r in cand]
  spec=freeze_numeric(a,config['bins']) if feature in NUMERIC else freeze_categorical(a)
  ac=count_bins(a,spec);bc=count_bins(b,spec);metrics=divergence(ac,bc,config['smoothing'])
  metrics.update({'binning':spec,'reference_counts':ac,'candidate_counts':bc,'reference_n':len(a),'candidate_n':len(b),'reference_missing':sum(x is None for x in a),'candidate_missing':sum(x is None for x in b),'ks_statistic':None,'p_value':None,'q_value':None,'fdr_reject':False})
  if feature in NUMERIC:
   av=[float(x) for x in a if x is not None];bv=[float(x) for x in b if x is not None]
   if len(av)<2 or len(bv)<2:raise ValueError('连续特征有效值不足，无法KS检验')
   ks=ks_2samp(av,bv,alternative='two-sided',method='auto');metrics.update(ks_statistic=float(ks.statistic),p_value=float(ks.pvalue),ks_reference_n=len(av),ks_candidate_n=len(bv));continuous.append(len(findings))
  findings.append({'feature':feature,'status':'quiet','metrics':metrics})
 return {'reference_n':len(ref),'candidate_n':len(cand),'reference_ids':[x['id'] for x in ref],'candidate_ids':[x['id'] for x in cand],'findings':findings,'continuous_index':continuous}

def apply_family_correction(slice_results,features,fdr_alpha):
 """把全部切片的连续检验合成一个检验族，一次BH后回写统一校正q。"""
 keys=[];pvalues=[]
 for si,result in enumerate(slice_results):
  for ci in result['continuous_index']:
   keys.append((si,ci));pvalues.append(result['findings'][ci]['metrics']['p_value'])
 qvalues=benjamini_hochberg(pvalues)
 for (si,ci),q in zip(keys,qvalues):
  m=slice_results[si]['findings'][ci]['metrics'];m.update(q_value=q,fdr_reject=bool(q<=fdr_alpha))
 for result in slice_results:
  for f in result['findings']:
   m=f['metrics'];f['status']='review' if m['fdr_reject'] or m['psi']>=.2 or m['js']>=.05 else 'quiet'
 return {'method':'Benjamini-Hochberg','m':len(keys),'alpha':fdr_alpha,'features':sorted({slice_results[si]['findings'][ci]['feature'] for si,ci in keys}),'keys':[{'slice_index':si,'feature':slice_results[si]['findings'][ci]['feature']} for si,ci in keys]}

def compare_snapshots(reference,candidate,config):
 _validate_inputs(reference,candidate,config)
 slice_filter={'language':config.get('slice_language'),'device':config.get('slice_device')}
 part=compare_slice(reference,candidate,config,slice_filter)
 findings=part['findings']
 qvalues=benjamini_hochberg([findings[i]['metrics']['p_value'] for i in part['continuous_index']])
 for i,q in zip(part['continuous_index'],qvalues):findings[i]['metrics'].update(q_value=q,fdr_reject=bool(q<=config['fdr_alpha']))
 for f in findings:
  m=f['metrics'];f['status']='review' if m['fdr_reject'] or m['psi']>=.2 or m['js']>=.05 else 'quiet'
 return {'fingerprint':fingerprint(reference,candidate,config),'reference_n':part['reference_n'],'candidate_n':part['candidate_n'],'reference_ids':part['reference_ids'],'candidate_ids':part['candidate_ids'],'findings':findings,'test_family':{'method':'Benjamini-Hochberg','m':len(part['continuous_index']),'alpha':config['fdr_alpha'],'features':[findings[i]['feature'] for i in part['continuous_index']]},'method':'Reference-only frozen quantile/category bins; additive pseudocount; PSI natural log; JS log2; two-sided KS nonmissing; BH across selected numeric features','interpretation':'Distribution difference is not evidence of downstream model quality degradation; review markers combine FDR and explicit heuristic effect-size thresholds.'}
