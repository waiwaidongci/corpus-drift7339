<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import type {Family,FamilyMember,FamilyFinding,Snapshot,User} from '../types/domain';
import {researchApi} from '../api/research';
import {useAsync} from '../hooks/useAsync';
import PageTitle from '../components/common/PageTitle.vue';
import Badge from '../components/common/Badge.vue';
import Table from '../components/common/Table.vue';
import Empty from '../components/common/Empty.vue';
import Notice from '../components/common/Notice.vue';
import HistogramBins from '../components/HistogramBins.vue';
import {dec,scientific,date,labelBin} from '../utils/format';
const props=defineProps<{snapshots:Snapshot[];families:Family[];features:Record<string,string>;user:User;reload:()=>Promise<any>}>();
const refs=computed(()=>props.snapshots.filter(s=>s.kind==='reference'));
const cands=computed(()=>props.snapshots.filter(s=>s.kind==='candidate'));
const familyKey=ref('november-multi-slice'),name=ref('十一月多切片校对族'),referenceId=ref(0),candidateId=ref(0),bins=ref(6),smoothing=ref(.5),alpha=ref(.05);
const defaultFeatures=computed(()=>Object.keys(props.features));
const selected=ref<string[]>([]);
const chosen=computed(()=>selected.value.length?selected.value:defaultFeatures.value);
function toggle(key:string){const next=chosen.value.includes(key)?chosen.value.filter(k=>k!==key):[...chosen.value,key];if(next.length)selected.value=next}
const slices=ref<{label:string;language:string;device:string}[]>([{label:'全量',language:'',device:''}]);
function addSlice(){slices.value.push({label:'切片'+(slices.value.length+1),language:'',device:''})}
function removeSlice(i:number){if(slices.value.length>1)slices.value.splice(i,1)}
const selectedFamilyId=ref(0);
const family=computed(()=>props.families.find(f=>f.id===selectedFamilyId.value)||props.families[0]);
const members=ref<FamilyMember[]>([]),familyFindings=ref<FamilyFinding[]>([]),detailError=ref('');
const {task,act}=useAsync();
async function loadDetail(){
 if(!family.value){members.value=[];familyFindings.value=[];return}
 try{const [m,ff]=await Promise.all([researchApi.familyMembers(family.value.id),researchApi.familyFindings(family.value.id)]);members.value=m;familyFindings.value=ff;detailError.value=''}catch(e:any){detailError.value=e.message}
}
watch(family,loadDetail,{immediate:true});
watch(()=>props.families,loadDetail);
async function submit(){
 await act(async()=>{
  const created=await researchApi.queueFamily({family_key:familyKey.value,name:name.value,reference_id:referenceId.value||refs.value[0]?.id,candidate_id:candidateId.value||cands.value[0]?.id,features:chosen.value,bins:bins.value,smoothing:smoothing.value,fdr_alpha:alpha.value,slices:slices.value.map(s=>({label:s.label,language:s.language||null,device:s.device||null}))});
  await props.reload();selectedFamilyId.value=created.id;await loadDetail();
 },'校对族已入队：快照与切片清单已冻结，切片任务并发执行');
}
const memberName=(id:number)=>members.value.find(m=>m.id===id)?.label||('#'+id);
const memberIndex=(id:number)=>members.value.find(m=>m.id===id)?.slice_index??0;
const focusMemberId=ref(0),focusFeature=ref('');
const focusRows=computed(()=>{
 const mid=focusMemberId.value||members.value[0]?.id;
 return familyFindings.value.filter(f=>f.member_id===mid);
});
const focus=computed(()=>focusRows.value.find(f=>f.feature===(focusFeature.value||f.feature))||focusRows.value[0]);
const doneCount=computed(()=>members.value.filter(m=>m.status==='succeeded').length);
const failCount=computed(()=>members.value.filter(m=>m.status==='failed').length);
const planName=ref('多切片补采说明'),slice=ref('按族内建议核对切片补齐'),target=ref(200),rationale=ref('统一BH校正后仍建议核对的切片优先补采；先核对来源与采样口径，漂移不等于模型劣化。');
async function makePlan(){
 await act(async()=>{
  const ids=focusRows.value.filter(f=>f.status==='review').map(f=>f.id);
  if(!ids.length)throw new Error('当前切片没有建议核对的发现');
  await researchApi.plan({family_id:family.value!.id,name:planName.value,finding_ids:ids,target_slice:slice.value,sample_target:target.value,rationale:rationale.value});
  await props.reload();
 },'补采计划已建立，等待负责人审稿');
}
const versions=computed(()=>props.families.filter(f=>f.family_key===family.value?.family_key).sort((a,b)=>b.version-a.version));
</script>
<template>
 <PageTitle index="03B / PROOF FAMILY" title="一族切片，一次校正。" description="创建时冻结两份快照、切片清单、特征与阈值；全部切片的连续检验合成一个检验族，成员齐备后一次发布统一校正值，任一失败即不发布。"/>
 <Notice :error="task.error" :message="task.message"/>
 <div class="compare-layout">
  <form class="editor" @submit.prevent="submit">
   <h2>建立校对族（修改切片或参数会生成新版本）</h2>
   <fieldset :disabled="task.busy||user.role==='viewer'">
    <div class="form-grid">
     <label>族键（同键再建即新版本）<input v-model="familyKey" required maxlength="80"/></label>
     <label>校样名称<input v-model="name" required maxlength="100"/></label>
    </div>
    <div class="form-grid">
     <label>参考快照<select v-model="referenceId"><option :value="0" v-if="refs.length">{{refs[0].name}}</option><option v-for="s in refs" :key="s.id" :value="s.id">{{s.name}}</option></select></label>
     <label>候选快照<select v-model="candidateId"><option :value="0" v-if="cands.length">{{cands[0].name}}</option><option v-for="s in cands" :key="s.id" :value="s.id">{{s.name}}</option></select></label>
    </div>
    <label>比较特征（族内所有切片共用）</label>
    <div class="feature-checks"><label v-for="(label,key) in features" :key="key"><input type="checkbox" :checked="chosen.includes(String(key))" @change="toggle(String(key))"/>{{label}}</label></div>
    <div class="form-grid">
     <label>参考分位箱数<input type="number" v-model.number="bins" min="2" max="10" step="1"/></label>
     <label>每桶平滑伪计数<input type="number" v-model.number="smoothing" min=".1" max="10" step=".1"/></label>
     <label>统一 BH FDR α<input type="number" v-model.number="alpha" min=".01" max=".2" step=".01"/></label>
    </div>
    <label>切片清单（语言/设备留空表示该维不过滤）</label>
    <div v-for="(s,i) in slices" :key="i" class="slice-row">
     <input v-model="s.label" placeholder="切片名" required maxlength="160"/>
     <input v-model="s.language" placeholder="语言如 zh / 留空" maxlength="40"/>
     <input v-model="s.device" placeholder="设备如 mobile / 留空" maxlength="40"/>
     <button type="button" @click="removeSlice(i)" :disabled="slices.length===1">移除</button>
    </div>
    <button type="button" @click="addSlice">＋ 增加切片</button>
    <button class="primary" :disabled="!refs.length||!cands.length" style="margin-top:10px">{{task.busy?'正在提交…':'冻结快照并并发校对 →'}}</button>
   </fieldset>
   <p v-if="user.role==='viewer'">观察员可阅读校对族；建立需要研究员权限。</p>
  </form>
  <aside class="method-column">
   <small>FAMILY NOTES / 校正口径</small>
   <h2>切片越多，<br/>越不能各算各的。</h2>
   <ol>
    <li><b>创建即冻结</b><p>两份快照校验、切片清单、特征、分箱/平滑/α 写入版本，之后不可变。</p></li>
    <li><b>一个检验族</b><p>全部切片的连续KS原p进入同一次BH，m=切片数×连续特征数，统一q一次发布。</p></li>
    <li><b>全成才发布</b><p>切片任务并发，任一成员失败整族保持未发布并记录原因；旧任务按member_id归属，无法写入新版本。</p></li>
    <li><b>可追溯</b><p>补采计划只能引用已发布版本；旧版本结论、计划与冻结指纹长期保留。</p></li>
   </ol>
  </aside>
 </div>
 <div class="section-title"><h2>校对族进度与版本</h2><small>后端每3秒刷新</small></div>
 <Empty v-if="!families.length" title="尚无校对族" help="在上方冻结两份快照与切片清单，建立第一个校对族。"/>
 <template v-else>
  <div class="run-selector">
   <select aria-label="选择校对族" :value="family?.id" @change="selectedFamilyId=Number(($event.target as HTMLSelectElement).value)">
    <option v-for="f in families" :key="f.id" :value="f.id">{{f.name}} · v{{f.version}} · {{f.family_key}}</option>
   </select>
   <Badge v-if="family" :status="family.status"/>
   <small v-if="versions.length>1">同族版本：<b v-for="v in versions" :key="v.id">v{{v.version}} </b></small>
  </div>
  <template v-if="family">
   <Notice :error="family.error||detailError"/>
   <div class="family-strip">
    <span>成员完成 {{doneCount}}/{{members.length}}<template v-if="failCount"> · 失败 {{failCount}}</template></span>
    <span>切片数 {{family.slices.length}} · 统一检验族 m={{family.result.test_family?.m??'—'}}</span>
    <span>参考校验 {{family.reference_fingerprint.slice(0,16)}}…</span>
    <span>候选校验 {{family.candidate_fingerprint.slice(0,16)}}…</span>
   </div>
   <Table :headers="['切片 / 状态','语言','设备','参考 / 候选 n','尝试','失败原因','更新时间']">
    <tr v-for="m in members" :key="m.id" :class="{selected:m.id===focusMemberId}" @click="focusMemberId=m.id">
     <td><small>#{{m.slice_index}}</small> <strong>{{m.label}}</strong> <Badge :status="m.status"/></td>
     <td>{{m.slice_filter.language||'全量'}}</td><td>{{m.slice_filter.device||'全量'}}</td>
     <td>{{m.result.reference_n??'—'}} / {{m.result.candidate_n??'—'}}</td>
     <td>{{m.attempts}}</td><td class="detail">{{m.error||'—'}}</td><td class="mono">{{date(m.updated_at)}}</td>
    </tr>
   </Table>
   <Empty v-if="family.status!=='published'" title="统一校正值尚未发布" :help="family.status==='failed'?'存在失败成员，整族保持未发布；修正切片或参数后建立新版本。':'等待全部切片成员并发完成。'"/>
   <template v-else>
    <div class="section-title"><h2>每项原值与统一校正结果</h2><small>原p来自各切片KS；q为整族一次BH的统一校正值</small></div>
    <div class="run-selector">
     <label>查看切片
      <select v-model="focusMemberId">
       <option v-for="m in members" :key="m.id" :value="m.id">{{m.label}}</option>
      </select>
     </label>
    </div>
    <Table :headers="['特征 / 标记','PSI ln','JS log₂','KS统计量','原 p（切片原值）','统一 BH q / FDR','']">
     <tr v-for="f in focusRows" :key="f.id" :class="{selected:f.feature===focus?.feature}">
      <td><strong>{{features[f.feature]}}</strong><Badge :status="f.status"/></td>
      <td>{{dec(f.metrics.psi)}}</td><td>{{dec(f.metrics.js)}}</td><td>{{dec(f.metrics.ks_statistic)}}</td>
      <td>{{scientific(f.metrics.p_value)}}</td>
      <td>{{scientific(f.metrics.q_value)}}<small>{{f.metrics.q_value==null?'类别不做KS':f.metrics.fdr_reject?'q≤α，拒绝':'q>α，未拒绝'}}</small></td>
      <td><button class="text-button" @click="focusFeature=f.feature">校对分箱 ↗</button></td>
     </tr>
    </Table>
    <section v-if="focus" class="finding-detail">
     <div class="section-title"><h2>{{features[focus.feature]}} / {{memberName(focus.member_id)}}冻结分箱</h2><small>仅参考拟合 · {{focus.metrics.binning.kind}} · 切片#{{memberIndex(focus.member_id)}}</small></div>
     <div class="finding-summary">
      <div><small>PSI / ln</small><b>{{dec(focus.metrics.psi)}}</b></div>
      <div><small>JS / log₂</small><b>{{dec(focus.metrics.js)}}</b></div>
      <div><small>KS 原 p</small><b>{{scientific(focus.metrics.p_value)}}</b></div>
      <div><small>族统一 BH q</small><b>{{scientific(focus.metrics.q_value)}}</b></div>
     </div>
     <HistogramBins :finding="focus"/>
     <div class="missing-note">参考缺失 {{focus.metrics.reference_missing}} / 候选缺失 {{focus.metrics.candidate_missing}}；缺失进入独立桶。</div>
     <Table :headers="['冻结箱','参考计数','候选计数']">
      <tr v-for="(label,i) in focus.metrics.binning.labels" :key="i"><td class="mono">{{labelBin(label)}}</td><td>{{focus.metrics.reference_counts[i]}}</td><td>{{focus.metrics.candidate_counts[i]}}</td></tr>
     </Table>
    </section>
    <form v-if="user.role!=='viewer'" class="editor plan-editor" @submit.prevent="makePlan">
     <small>NEXT / 仅已发布版本可建计划</small>
     <h2>以当前切片的建议核对发现建立补采草案</h2>
     <div class="form-grid">
      <label>计划名称<input v-model="planName" required maxlength="100"/></label>
      <label>目标切片<input v-model="slice" required maxlength="160"/></label>
      <label>目标片段数<input type="number" v-model.number="target" min="20" max="10000" step="1" required/></label>
     </div>
     <label>补采依据<textarea rows="3" v-model="rationale" required maxlength="500"/></label>
     <button class="primary" :disabled="task.busy">建立补采计划 →</button>
    </form>
   </template>
  </template>
 </template>
</template>
