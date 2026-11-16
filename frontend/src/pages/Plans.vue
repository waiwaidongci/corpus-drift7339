<script setup lang="ts">
import {ref,computed} from 'vue';
import type {Plan,Family,User} from '../types/domain';
import {researchApi} from '../api/research';
import {useAsync} from '../hooks/useAsync';
import PageTitle from '../components/common/PageTitle.vue';
import Badge from '../components/common/Badge.vue';
import Notice from '../components/common/Notice.vue';
import Empty from '../components/common/Empty.vue';
const props=defineProps<{plans:Plan[];families:Family[];user:User;reload:()=>Promise<any>}>();
const note=ref('先核对采样口径，再按切片补齐；后续使用独立质量评测验证效果。');
const {task,act}=useAsync();
const familyOf=(id:number|null)=>props.families.find(f=>f.id===id);
const sourceText=(p:Plan)=>{
 const f=familyOf(p.family_id);
 return f?`校对族「${f.name}」v${f.version}`:`单次比较 RUN #${p.run_id}`;
};
const sorted=computed(()=>[...props.plans].sort((a,b)=>b.id-a.id));
</script>
<template>
 <PageTitle index="05 / RESAMPLING DESK" title="补采之前，先把理由写清楚。" description="研究员把发现转成切片、目标样本量与依据；校对族计划只能引用已发布版本，旧版本结论仍可追溯。负责人确认后开放CSV。"/>
 <Notice :error="task.error" :message="task.message"/>
 <label class="approval-note" v-if="user.role==='admin'">本次审稿说明<input v-model="note" required maxlength="500"/></label>
 <Empty v-if="!plans.length" title="等待第一份补采草案" help="在漂移发现页选择单次比较，或在校对族页选择已发布版本的发现。"/>
 <div class="plan-list">
  <article v-for="p in sorted" :key="p.id">
   <header>
    <span class="proof-number">{{String(p.id).padStart(2,'0')}}</span>
    <div>
     <small>{{sourceText(p)}} · FINDINGS {{p.finding_ids.join(', ')}}</small>
     <h2>{{p.name}}</h2>
    </div>
    <Badge :status="p.status"/>
   </header>
   <div class="plan-body">
    <dl>
     <dt>目标切片</dt><dd>{{p.target_slice}}</dd>
     <dt>目标片段</dt><dd>{{p.sample_target}}</dd>
     <dt>引用来源</dt><dd>{{sourceText(p)}}<small v-if="familyOf(p.family_id)"> · 状态：{{familyOf(p.family_id)?.status==='published'?'已发布':familyOf(p.family_id)?.status}}</small></dd>
    </dl>
    <section>
     <small>研究员依据</small><p>{{p.rationale}}</p>
     <small v-if="p.review_note">负责人说明</small><p v-if="p.review_note">{{p.review_note}}</p>
    </section>
   </div>
   <div class="plan-actions">
    <button :disabled="p.status!=='approved'" @click="act(()=>researchApi.export(p.id),'获批补采CSV已导出')">导出获批CSV ↗</button>
    <template v-if="user.role==='admin'&&p.status==='draft'">
     <button :disabled="task.busy" @click="act(async()=>{await researchApi.approve(p.id,'rejected',note);await reload()},'计划已退回修改')">退回修改</button>
     <button class="primary" :disabled="task.busy" @click="act(async()=>{await researchApi.approve(p.id,'approved',note);await reload()},'补采计划已确认')">确认补采说明 →</button>
    </template>
   </div>
  </article>
 </div>
</template>
