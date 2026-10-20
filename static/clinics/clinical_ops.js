(() => {
  const q=(s,r=document)=>r.querySelector(s), fmt=v=>v?window.FinoraTime.format(new Date(v), {dateStyle:"medium",timeStyle:v.includes?.("T")?"short":undefined}):"—", money=n=>Number(n||0).toLocaleString("en-IQ")+" د.ع";
  const labels={requested:"طلب جديد",ordered:"طلب جديد",waiting_sample:"بانتظار العينة",sample_collected:"تم أخذ العينة",processing:"قيد التحليل",result_ready:"النتيجة جاهزة",reviewed:"تمت المراجعة",completed:"مكتمل",cancelled:"ملغي",invalid_sample:"عينة غير صالحة",repeat_required:"إعادة مطلوبة",waiting_imaging:"بانتظار التصوير",imaging_done:"تم التصوير",waiting_report:"بانتظار التقرير",report_ready:"التقرير جاهز",scheduled:"قادمة",due:"مستحقة",overdue:"متأخرة",contacted:"تم التواصل",no_answer:"لم يرد",callback:"إعادة اتصال",action_required:"تحتاج إجراء",in_progress:"قيد التنفيذ",not_done:"لم يتم"};
  const status=s=>`<span class="cx-op-status cx-op-status--${s}">${labels[s]||s}</span>`, patient=(x,e)=>`<span class="cx-op-person"><i>${e((x.patient_name||"؟").split(/\s+/).slice(0,2).map(z=>z[0]).join(""))}</i><span><strong>${e(x.patient_name)}</strong><small>${e(x.patient_file)}</small></span></span>`, doctor=(x,e)=>`<span class="cx-op-doctor"><i class="fa fa-user-doctor"></i>${e(x.doctor_name||"—")}</span>`;
  function base(type){const u=new URLSearchParams(location.search);return {page:1,per_page:25,q:"",date:"",status:"",doctor_id:"",priority:"",patient_id:u.get("patient_id")||"",visit_id:u.get("visit_id")||"",type}}
  function params(s,extra={}){const p=new URLSearchParams({center:"1",page:s.page,per_page:s.per_page,...extra});Object.entries(s).forEach(([k,v])=>{if(v&&!['type'].includes(k))p.set(k,v)});return p}
  function shell(title,desc,placeholder,action,s,data,filters,kpis,body){return `<section class="cx-op"><header class="cx-op-head"><div><h1>${title}</h1><p>${desc}</p></div><label><i class="fa fa-magnifying-glass"></i><input id="opSearch" class="cx-input" value="${s.q}" placeholder="${placeholder}"></label><button id="opPrimary" class="cx-btn cx-btn--primary"><i class="fa fa-plus"></i>${action}</button></header><div class="cx-op-filters">${filters}</div><section class="cx-op-kpis">${kpis}</section><div class="cx-op-work">${body}</div>${pager(data)}<aside class="cx-op-drawer" id="opDrawer" hidden></aside><div class="cx-op-backdrop" id="opBackdrop" hidden></div></section>`}
  function kpis(items){return items.map(x=>`<article><i class="fa fa-${x[2]}"></i><div><span>${x[0]}</span><strong>${Number(x[1]||0).toLocaleString("ar-IQ")}</strong></div></article>`).join("")}
  function pager(d){return `<footer class="cx-op-pager"><select id="opPer" class="cx-select">${[25,50,100].map(n=>`<option ${d.per_page===n?"selected":""}>${n}</option>`).join("")}</select><span>عرض ${d.items.length} من ${d.total}</span><div><button class="cx-btn cx-btn--sm" data-p="${d.page-1}" ${d.page<=1?"disabled":""}>السابق</button><b>${d.page} / ${d.pages}</b><button class="cx-btn cx-btn--sm" data-p="${d.page+1}" ${d.page>=d.pages?"disabled":""}>التالي</button></div></footer>`}
  function table(head,rows){return `<div class="cx-card cx-table-wrap"><table class="cx-table cx-op-table"><thead><tr>${head.map(x=>`<th>${x}</th>`).join("")}</tr></thead><tbody>${rows.join("")||`<tr><td colspan="${head.length}"><div class="cx-empty">لا توجد سجلات مطابقة</div></td></tr>`}</tbody></table></div>`}
  function bind(root,s,ctx){let t;q("#opSearch",root).oninput=e=>{clearTimeout(t);t=setTimeout(()=>{s.q=e.target.value;s.page=1;ctx.render()},350)};root.querySelectorAll("[data-filter]").forEach(x=>x.onchange=()=>{s[x.dataset.filter]=x.value;s.page=1;ctx.render()});root.querySelectorAll("[data-p]").forEach(x=>x.onclick=()=>{s.page=Number(x.dataset.p);ctx.render()});q("#opPer",root).onchange=e=>{s.per_page=Number(e.target.value);s.page=1;ctx.render()}}
  function drawer(root,html){const d=q("#opDrawer",root),b=q("#opBackdrop",root);d.innerHTML=html;d.hidden=b.hidden=false;const close=()=>d.hidden=b.hidden=true;b.onclick=close;q("[data-close]",d).onclick=close;return d}
  async function options(ctx){const [patients]=await Promise.all([ctx.api("/clinics/api/patients?limit=100")]);return {patients,doctors:ctx.bootstrap?.doctors||[]}}
  const patientOptions=(o,e,id)=>o.patients.map(x=>`<option value="${x.id}" ${String(x.id)===String(id)?"selected":""}>${e(x.full_name)} · ${e(x.file_number)}</option>`).join(""), doctorOptions=(o,e,id)=>`<option value="">—</option>`+o.doctors.map(x=>`<option value="${x.id}" ${String(x.id)===String(id)?"selected":""}>${e(x.full_name)}</option>`).join("");

  async function labs(app,root,ctx){const s=app.opsLabs||(app.opsLabs=base("labs")),d=await ctx.api(`/clinics/api/lab-orders?${params(s)}`),st=d.stats;root.innerHTML=shell("التحاليل","إدارة طلبات ونتائج التحاليل","ابحث عن مريض، رقم ملف، تحليل أو رقم طلب...","طلب تحاليل",s,d,filters(s,ctx,[['date','التاريخ',[['','كل التواريخ'],['today','اليوم']]],['status','الحالة',labStates()],['doctor_id','الطبيب',doctorsList(ctx)],['priority','الأولوية',priorities()]]),kpis([["طلبات اليوم",st.today,"vials"],["بانتظار العينة",st.waiting_sample,"droplet"],["قيد التحليل",st.processing,"microscope"],["النتائج جاهزة",st.result_ready,"file-circle-check"],["بانتظار المراجعة",st.reviewed,"user-doctor"],["مكتملة",st.completed,"circle-check"]]),table(["رقم الطلب","المريض","التحاليل","الطبيب","وقت الطلب","الأولوية","الحالة","النتيجة","الإجراء"],d.items.map(x=>`<tr><td><strong>${x.order_number}</strong></td><td>${patient(x,ctx.esc)}</td><td>${ctx.esc(x.items.map(i=>i.name).join(" + "))}</td><td>${doctor(x,ctx.esc)}</td><td>${fmt(x.ordered_at)}</td><td>${x.priority==='urgent'?'<b class="cx-op-priority">مستعجل</b>':'عادي'}</td><td>${status(x.status)}</td><td>${resultBadge(x.result_summary)}</td><td><button class="cx-btn cx-btn--sm" data-open="${x.id}">فتح</button></td></tr>`)));bind(root,s,ctx);q("#opPrimary",root).onclick=()=>labOrder(s,ctx);root.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>labDrawer(d.items.find(x=>x.id===Number(b.dataset.open)),root,ctx,s))}
  function labStates(){return [['','كل الحالات'],...['requested','waiting_sample','sample_collected','processing','result_ready','reviewed','completed','cancelled'].map(x=>[x,labels[x]])]}
  function resultBadge(x){return `<span class="cx-op-result cx-op-result--${x}">${{normal:'طبيعي',abnormal:'غير طبيعي',critical:'حرج',pending:'بانتظار النتيجة'}[x]||x}</span>`}
  async function labOrder(s,ctx){const [o,tests]=await Promise.all([options(ctx),ctx.api("/clinics/api/lab-tests")]);ctx.openModal("طلب تحاليل",`<div class="cx-field"><label>المريض *</label><select id="loPatient" class="cx-select">${patientOptions(o,ctx.esc,s.patient_id)}</select></div><div class="cx-field-row"><div class="cx-field"><label>الزيارة</label><input id="loVisit" class="cx-input" type="number" value="${s.visit_id}"></div><div class="cx-field"><label>الطبيب *</label><select id="loDoctor" class="cx-select">${doctorOptions(o,ctx.esc,"")}</select></div></div><div class="cx-field"><label>التحاليل *</label><div class="cx-op-checks">${tests.map(x=>`<label><input type="checkbox" value="${x.id}">${ctx.esc(x.name)}</label>`).join("")}</div></div><div class="cx-field"><label>الأولوية</label><select id="loPriority" class="cx-select"><option value="normal">عادي</option><option value="urgent">مستعجل</option></select></div><div class="cx-field"><label>ملاحظات سريرية</label><textarea id="loNotes" class="cx-textarea"></textarea></div>`,async()=>{await ctx.api("/clinics/api/lab-orders",{method:"POST",body:JSON.stringify({patient_id:Number(q("#loPatient").value),visit_id:q("#loVisit").value||null,doctor_id:q("#loDoctor").value||null,test_ids:[...document.querySelectorAll('.cx-op-checks input:checked')].map(x=>Number(x.value)),priority:q("#loPriority").value,notes:q("#loNotes").value})})})}
  function labDrawer(x,root,ctx,s){const tests=x.items.map(i=>`<tr><td>${ctx.esc(i.name)}</td><td>${ctx.esc(i.value||"—")}</td><td>${ctx.esc(i.unit)}</td><td>${ctx.esc(i.reference_range)}</td><td>${resultBadge(i.flag)}</td></tr>`).join("");const d=drawer(root,drawerHead("تفاصيل طلب التحليل",x.order_number,ctx.esc)+summary(x,ctx.esc)+`<h3>التحاليل والنتائج</h3><div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>التحليل</th><th>النتيجة</th><th>الوحدة</th><th>المرجع</th><th>العلم</th></tr></thead><tbody>${tests}</tbody></table></div><div class="cx-op-drawer-actions"><button class="cx-btn" data-lab="waiting_sample">بانتظار العينة</button><button class="cx-btn" data-lab="sample_collected">تسجيل أخذ العينة</button><button class="cx-btn" data-lab="processing">بدء التحليل</button><button class="cx-btn cx-btn--primary" data-results>تسجيل النتائج</button><button class="cx-btn" data-lab="result_ready">اعتماد النتائج</button><button class="cx-btn" data-lab="reviewed">مراجعة الطبيب</button><a class="cx-btn" href="/clinics/patients/${x.patient_id}">فتح المريض</a>${x.visit_id?`<a class="cx-btn" href="/clinics/doctor/${x.visit_id}">فتح الزيارة</a>`:""}</div>`);d.querySelectorAll("[data-lab]").forEach(b=>b.onclick=async()=>{await workflow(ctx,`/clinics/api/lab-orders/${x.id}/workflow`,x.status,b.dataset.lab);s.page=s.page;ctx.render()});q("[data-results]",d).onclick=()=>labResults(x,ctx)}
  function labResults(x,ctx){ctx.openModal("تسجيل نتائج التحاليل",`<div class="cx-op-results">${x.items.map(i=>`<div data-item="${i.id}"><strong>${ctx.esc(i.name)}</strong><input class="cx-input val" placeholder="النتيجة" value="${ctx.esc(i.value)}"><input class="cx-input unit" placeholder="الوحدة" value="${ctx.esc(i.unit)}"><input class="cx-input ref" placeholder="المرجع" value="${ctx.esc(i.reference_range)}"><select class="cx-select flag"><option value="normal">طبيعي</option><option value="high">مرتفع</option><option value="low">منخفض</option><option value="critical">حرج</option></select></div>`).join("")}</div>`,async()=>{for(const r of document.querySelectorAll("[data-item]"))await ctx.api(`/clinics/api/lab-order-items/${r.dataset.item}/result`,{method:"POST",body:JSON.stringify({value:q('.val',r).value,unit:q('.unit',r).value,reference_range:q('.ref',r).value,abnormal_flag:q('.flag',r).value})})})}

  async function radiology(app,root,ctx){const s=app.opsRad||(app.opsRad=base("rad")),d=await ctx.api(`/clinics/api/radiology-orders?${params(s)}`),st=d.stats;root.innerHTML=shell("الأشعة","إدارة طلبات التصوير والتقارير","ابحث عن مريض، رقم ملف، نوع أشعة أو رقم طلب...","طلب أشعة",s,d,filters(s,ctx,[['date','التاريخ',[['','كل التواريخ'],['today','اليوم']]],['status','الحالة',radStates()],['modality','النوع',modalities()],['doctor_id','الطبيب',doctorsList(ctx)],['priority','الأولوية',priorities()]]),kpis([["طلبات اليوم",st.today,"x-ray"],["بانتظار التصوير",st.waiting_imaging,"clock"],["تم التصوير",st.imaging_done,"camera"],["بانتظار التقرير",st.waiting_report,"file-pen"],["التقرير جاهز",st.report_ready,"file-circle-check"],["تمت المراجعة",st.reviewed,"circle-check"]]),table(["رقم الطلب","المريض","نوع الأشعة","المنطقة","الطبيب","التاريخ","الحالة","التقرير","الإجراء"],d.items.map(x=>`<tr><td><strong>${x.order_number}</strong></td><td>${patient(x,ctx.esc)}</td><td>${ctx.esc(modalityLabel(x.modality))}</td><td>${ctx.esc(x.body_part)}</td><td>${doctor(x,ctx.esc)}</td><td>${fmt(x.ordered_at)}</td><td>${status(x.status)}</td><td>${x.report?'متاح':'—'}</td><td><button class="cx-btn cx-btn--sm" data-open="${x.id}">عرض</button></td></tr>`)));bind(root,s,ctx);q("#opPrimary",root).onclick=()=>radOrder(s,ctx);root.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>radDrawer(d.items.find(x=>x.id===Number(b.dataset.open)),root,ctx))}
  const modalities=()=>[['','كل الأنواع'],['xray','X-Ray'],['ultrasound','Ultrasound'],['ct','CT'],['mri','MRI'],['mammography','Mammography'],['dental','Dental Imaging'],['other','Other']], modalityLabel=x=>Object.fromEntries(modalities())[x]||x, radStates=()=>[['','كل الحالات'],...['requested','waiting_imaging','imaging_done','waiting_report','report_ready','reviewed','completed','cancelled'].map(x=>[x,labels[x]])];
  async function radOrder(s,ctx){const o=await options(ctx);ctx.openModal("طلب أشعة",`<div class="cx-field"><label>المريض *</label><select id="roPatient" class="cx-select">${patientOptions(o,ctx.esc,s.patient_id)}</select></div><div class="cx-field-row"><div class="cx-field"><label>الزيارة</label><input id="roVisit" class="cx-input" type="number" value="${s.visit_id}"></div><div class="cx-field"><label>الطبيب *</label><select id="roDoctor" class="cx-select">${doctorOptions(o,ctx.esc,"")}</select></div></div><div class="cx-field-row"><div class="cx-field"><label>نوع الأشعة *</label><select id="roMod" class="cx-select">${modalities().slice(1).map(x=>`<option value="${x[0]}">${x[1]}</option>`).join("")}</select></div><div class="cx-field"><label>المنطقة *</label><input id="roPart" class="cx-input"></div></div><div class="cx-field"><label>الأولوية</label><select id="roPriority" class="cx-select"><option value="normal">عادي</option><option value="urgent">مستعجل</option></select></div><div class="cx-field"><label>سبب الطلب / ملاحظات</label><textarea id="roNotes" class="cx-textarea"></textarea></div>`,async()=>ctx.api("/clinics/api/radiology-orders",{method:"POST",body:JSON.stringify({patient_id:Number(q("#roPatient").value),visit_id:q("#roVisit").value||null,doctor_id:q("#roDoctor").value||null,modality:q("#roMod").value,body_part:q("#roPart").value,priority:q("#roPriority").value,notes:q("#roNotes").value})}))}
  function radImageGrid(items,esc){
    if(!items.length) return `<div class="cx-empty cx-op-images__empty">لا توجد صور مرفوعة بعد</div>`;
    return `<div class="cx-op-images">${items.map(a=>{
      const img=a.mime_type?.startsWith("image/");
      return `<a class="cx-op-image" href="${esc(a.preview_url)}" target="_blank" rel="noopener" title="${esc(a.file_name)}">${
        img?`<img src="${esc(a.preview_url)}" alt="${esc(a.file_name)}">`:`<i class="fa fa-file"></i>`
      }<span>${esc(a.file_name)}</span></a>`;
    }).join("")}</div>`;
  }
  async function radImages(x,ctx){
    const qs=new URLSearchParams({patient_id:String(x.patient_id),category:"radiology",per_page:"50"});
    if(x.visit_id) qs.set("visit_id",String(x.visit_id));
    const data=await ctx.api(`/clinics/api/attachments?${qs}`);
    return data.items||[];
  }
  function bindRadUpload(d,x,ctx){
    const input=q("#radFiles",d),drop=q("#radDrop",d),pick=q("#radPickFiles",d),status=q("#radImgStatus",d),grid=q("#radImgGrid",d),count=q("#radImgCount",d);
    if(!input||!drop) return;
    async function uploadFiles(files){
      const list=[...files||[]].slice(0,10);
      if(!list.length) return;
      status.hidden=false;
      status.textContent="جاري الرفع...";
      try{
        const fd=new FormData();
        fd.append("patient_id",String(x.patient_id));
        if(x.visit_id) fd.append("visit_id",String(x.visit_id));
        fd.append("category","radiology");
        fd.append("notes",x.order_number||"");
        list.forEach(f=>fd.append("files",f));
        const res=await fetch("/clinics/api/attachments",{
          method:"POST",
          headers:{"X-CSRFToken":document.querySelector('meta[name="csrf-token"]')?.content||""},
          body:fd
        });
        const data=await res.json().catch(()=>({}));
        if(!res.ok||data.ok===false) throw new Error(data.error||"فشل الرفع");
        ctx.showNotice("تم رفع الصور",false);
        const items=await radImages(x,ctx);
        grid.innerHTML=radImageGrid(items,ctx.esc);
        if(count) count.textContent=`${items.length} ملف`;
        status.textContent=`تم رفع ${list.length} ملف`;
        input.value="";
      }catch(err){
        status.textContent=err.message||String(err);
        ctx.showNotice(err.message||String(err));
      }
    }
    input.onchange=()=>uploadFiles(input.files);
    if(pick) pick.onclick=()=>input.click();
    ["dragenter","dragover"].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.add("active")}));
    ["dragleave","drop"].forEach(n=>drop.addEventListener(n,e=>{e.preventDefault();drop.classList.remove("active")}));
    drop.addEventListener("drop",e=>uploadFiles(e.dataTransfer.files));
  }
  async function radDrawer(x,root,ctx){
    let images=[];
    try{images=await radImages(x,ctx)}catch(_){images=[]}
    const d=drawer(root,drawerHead("تفاصيل طلب الأشعة",x.order_number,ctx.esc)+summary(x,ctx.esc)+`<article class="cx-op-report"><h3>التقرير</h3><p>${ctx.esc(x.report||"لم يضف التقرير بعد")}</p><h4>الانطباع</h4><p>${ctx.esc(x.impression||"—")}</p><h4>التوصيات</h4><p>${ctx.esc(x.recommendations||"—")}</p></article>
      <section class="cx-op-images-panel">
        <div class="cx-op-images-panel__head"><h3>صور الأشعة</h3><span id="radImgCount">${images.length} ملف</span></div>
        <div id="radImgGrid">${radImageGrid(images,ctx.esc)}</div>
        <label class="cx-doc-drop cx-op-drop" id="radDrop">
          <i class="fa fa-cloud-arrow-up"></i>
          <strong>اسحب الصور هنا أو اضغط للاختيار</strong>
          <small>JPG, PNG, WEBP, PDF — حتى 10 ملفات</small>
          <input id="radFiles" type="file" multiple accept="image/jpeg,image/png,image/webp,application/pdf,.jpg,.jpeg,.png,.webp,.pdf">
        </label>
        <p class="cx-op-images-status" id="radImgStatus" hidden></p>
      </section>
      <div class="cx-op-drawer-actions"><button class="cx-btn" data-rad="waiting_imaging">بانتظار التصوير</button><button class="cx-btn" data-rad="imaging_done">تم التصوير</button><button class="cx-btn" data-rad="waiting_report">بانتظار التقرير</button><button class="cx-btn cx-btn--primary" data-report>إضافة تقرير</button><button class="cx-btn" data-rad="reviewed">تمت المراجعة</button><button type="button" class="cx-btn" id="radPickFiles"><i class="fa fa-upload"></i> رفع صور</button></div>`);
    bindRadUpload(d,x,ctx);
    d.querySelectorAll("[data-rad]").forEach(b=>b.onclick=async()=>{await workflow(ctx,`/clinics/api/radiology-orders/${x.id}/workflow`,x.status,b.dataset.rad);ctx.render()});
    q("[data-report]",d).onclick=()=>ctx.openModal("تقرير الأشعة",`<div class="cx-field"><label>Findings / التقرير</label><textarea id="rrReport" class="cx-textarea">${ctx.esc(x.report)}</textarea></div><div class="cx-field"><label>Impression</label><textarea id="rrImp" class="cx-textarea">${ctx.esc(x.impression)}</textarea></div><div class="cx-field"><label>Recommendations</label><textarea id="rrRec" class="cx-textarea">${ctx.esc(x.recommendations)}</textarea></div>`,async()=>ctx.api(`/clinics/api/radiology-orders/${x.id}/workflow`,{method:"PATCH",body:JSON.stringify({expected_status:x.status,status:"report_ready",report:q("#rrReport").value,impression:q("#rrImp").value,recommendations:q("#rrRec").value})}));
  }

  async function followups(app,root,ctx){const s=app.opsFu||(app.opsFu=base("fu")),d=await ctx.api(`/clinics/api/followups?${params(s)}`),st=d.stats;root.innerHTML=shell("المتابعات","إدارة متابعة المرضى والتواصل بعد الزيارة","ابحث عن مريض، رقم ملف أو متابعة...","متابعة جديدة",s,d,filters(s,ctx,[['doctor_id','الطبيب',doctorsList(ctx)],['followup_type','النوع',[['','كل الأنواع'],...Object.entries(d.types)]],['status','الحالة',[['','كل الحالات'],...['scheduled','due','overdue','contacted','no_answer','callback','action_required','completed'].map(x=>[x,labels[x]])]]]),kpis([["مستحقة اليوم",st.due_today,"calendar-day"],["متأخرة",st.overdue,"triangle-exclamation"],["قادمة",st.upcoming,"calendar"],["تم التواصل",st.contacted,"phone"],["لم يرد",st.no_answer,"phone-slash"],["تحتاج إجراء",st.action_required,"bell"]]),table(["المريض","الطبيب","نوع المتابعة","تاريخ الاستحقاق","الحالة","آخر محاولة","النتيجة","الإجراء"],d.items.map(x=>`<tr><td>${patient(x,ctx.esc)}</td><td>${doctor(x,ctx.esc)}</td><td>${ctx.esc(x.followup_type_label)}</td><td>${fmt(x.due_date)}</td><td>${status(x.status)}</td><td>${fmt(x.last_attempt_at)}</td><td>${ctx.esc(x.outcome||"—")}</td><td><button class="cx-btn cx-btn--sm cx-btn--primary" data-contact="${x.id}">تواصل</button><button class="cx-btn cx-btn--sm" data-open="${x.id}">فتح</button></td></tr>`)));bind(root,s,ctx);q("#opPrimary",root).onclick=()=>followupCreate(s,d,ctx);root.querySelectorAll("[data-contact]").forEach(b=>b.onclick=()=>contact(d.items.find(x=>x.id===Number(b.dataset.contact)),ctx));root.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>followDrawer(d.items.find(x=>x.id===Number(b.dataset.open)),root,ctx))}
  async function followupCreate(s,d,ctx){const o=await options(ctx);ctx.openModal("متابعة جديدة",`<div class="cx-field"><label>المريض *</label><select id="fuPatient" class="cx-select">${patientOptions(o,ctx.esc,s.patient_id)}</select></div><div class="cx-field-row"><div class="cx-field"><label>الزيارة</label><input id="fuVisit" type="number" class="cx-input" value="${s.visit_id}"></div><div class="cx-field"><label>الطبيب</label><select id="fuDoctor" class="cx-select">${doctorOptions(o,ctx.esc,"")}</select></div></div><div class="cx-field-row"><div class="cx-field"><label>النوع</label><select id="fuType" class="cx-select">${Object.entries(d.types).map(x=>`<option value="${x[0]}">${x[1]}</option>`).join("")}</select></div><div class="cx-field"><label>تاريخ الاستحقاق</label><input id="fuDue" type="date" class="cx-input"></div></div><div class="cx-field"><label>ملاحظات</label><textarea id="fuNotes" class="cx-textarea"></textarea></div>`,async()=>ctx.api("/clinics/api/followups",{method:"POST",body:JSON.stringify({patient_id:Number(q("#fuPatient").value),visit_id:q("#fuVisit").value||null,doctor_id:q("#fuDoctor").value||null,followup_type:q("#fuType").value,due_date:q("#fuDue").value,notes:q("#fuNotes").value})}))}
  function contact(x,ctx){ctx.openModal("نتيجة التواصل",`<div class="cx-field"><label>هل تم الرد؟</label><select id="fcResult" class="cx-select"><option value="answered">تم الرد</option><option value="no_answer">لم يرد</option><option value="closed">الهاتف مغلق</option><option value="busy">مشغول</option><option value="invalid_number">الرقم غير صحيح</option></select></div><div class="cx-field"><label>نتيجة المتابعة</label><select id="fcOutcome" class="cx-select"><option value="good">الحالة جيدة</option><option value="partial_improvement">تحسن جزئي</option><option value="no_improvement">لا يوجد تحسن</option><option value="needs_review">يحتاج مراجعة</option><option value="needs_appointment">يحتاج موعد</option><option value="needs_doctor">يحتاج طبيب</option><option value="needs_lab">يحتاج تحليل</option><option value="needs_radiology">يحتاج أشعة</option><option value="callback">يحتاج إعادة اتصال</option><option value="other">أخرى</option></select></div><div class="cx-field"><label>المتابعة القادمة</label><input id="fcNext" type="date" class="cx-input"></div><div class="cx-field"><label>ملاحظات</label><textarea id="fcNotes" class="cx-textarea"></textarea></div>`,async()=>ctx.api(`/clinics/api/followups/${x.id}/contact`,{method:"POST",body:JSON.stringify({contact_result:q("#fcResult").value,outcome:q("#fcOutcome").value,next_due_date:q("#fcNext").value||null,notes:q("#fcNotes").value})}))}
  function followDrawer(x,root,ctx){drawer(root,drawerHead("تفاصيل المتابعة",x.followup_type_label,ctx.esc)+summary(x,ctx.esc)+`<article class="cx-op-report"><h3>ملاحظات المتابعة</h3><p>${ctx.esc(x.notes||"—")}</p><h4>آخر نتيجة</h4><p>${ctx.esc(x.outcome||"—")}</p></article><div class="cx-op-drawer-actions"><button class="cx-btn cx-btn--primary" data-contact-now>تواصل</button><a class="cx-btn" href="/clinics/patients/${x.patient_id}">فتح المريض</a>${x.visit_id?`<a class="cx-btn" href="/clinics/doctor/${x.visit_id}">فتح الزيارة</a>`:""}</div>`);q("[data-contact-now]",root).onclick=()=>contact(x,ctx)}

  async function procedures(app,root,ctx){const s=app.opsPr||(app.opsPr={...base("pr"),tab:"catalog"}),d=await ctx.api(`/clinics/api/procedures?${params(s,{tab:s.tab})}`),st=d.stats;const tabs=`<nav class="cx-op-tabs"><button data-tab="catalog" class="${s.tab==='catalog'?'active':''}">دليل الإجراءات</button><button data-tab="performed" class="${s.tab==='performed'?'active':''}">الإجراءات المنفذة</button></nav>`;const rows=s.tab==='catalog'?table(["الإجراء","التصنيف","السعر","المدة","المواد المستخدمة","الحالة","الإجراء"],d.items.map(x=>`<tr><td><strong>${ctx.esc(x.name)}</strong></td><td>${ctx.esc(x.category||"—")}</td><td>${money(x.price)}</td><td>${x.duration_minutes} دقيقة</td><td>${x.recipe.length?`${x.recipe.length} مواد`:'بدون مواد'}</td><td>${x.active?status('completed'):status('cancelled')}</td><td><button class="cx-btn cx-btn--sm" data-edit="${x.id}">تعديل</button></td></tr>`)):table(["الوقت","المريض","الإجراء","الطبيب / المنفذ","الزيارة","الكمية","السعر","الحالة","الإجراء"],d.items.map(x=>`<tr><td>${fmt(x.performed_at)}</td><td>${patient(x,ctx.esc)}</td><td>${ctx.esc(x.procedure_name)}</td><td>${doctor(x,ctx.esc)}</td><td>VIS-${String(x.visit_id).padStart(5,'0')}</td><td>${x.quantity}</td><td>${money(x.price)}</td><td>${status(x.status)}</td><td><button class="cx-btn cx-btn--sm" data-open="${x.id}">فتح</button></td></tr>`));const metricRows=[["إجمالي الإجراءات",st.total,"syringe"],["إجراءات فعالة",st.active,"circle-check"],["منفذة اليوم",st.performed_today,"clipboard-check"],["تستهلك مخزون",st.inventory,"boxes-stacked"]];if(st.revenue_today!==undefined)metricRows.splice(3,0,["إيراد اليوم",st.revenue_today,"money-bill"]);root.innerHTML=shell("الإجراءات الطبية","إدارة الإجراءات والأسعار والمواد المستخدمة","ابحث عن إجراء أو مريض...",s.tab==='catalog'?"إجراء جديد":"إضافة إجراء للزيارة",s,d,tabs+filters(s,ctx,s.tab==='catalog'?[['active','الحالة',[['','الكل'],['1','فعال'],['0','غير فعال']]],['consumes_inventory','المخزون',[['','الكل'],['1','يستهلك مخزون'],['0','بدون مخزون']]]]:[['status','الحالة',[['','كل الحالات'],...['requested','scheduled','in_progress','completed','cancelled'].map(x=>[x,labels[x]])]]]),kpis(metricRows),rows);bind(root,s,ctx);root.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{s.tab=b.dataset.tab;s.page=1;ctx.render()});q("#opPrimary",root).onclick=()=>s.tab==='catalog'?procedureForm(null,ctx):executionForm(s,ctx);root.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>procedureForm(d.items.find(x=>x.id===Number(b.dataset.edit)),ctx));root.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>executionDrawer(d.items.find(x=>x.id===Number(b.dataset.open)),root,ctx))}
  async function procedureForm(x,ctx){
    const inv=await ctx.api("/clinics/api/inventory");
    const recipe=(x?.recipe||[])[0];
    const selected=new Set((x?.specialty_ids||[]).map(Number));
    const specialties=(ctx.bootstrap?.specialties||[]).filter(s=>s.is_active!==false);
    const chips=specialties.length
      ? specialties.map(s=>`<label class="cx-svc-chip"><input type="checkbox" data-procedure-specialty value="${s.id}" ${selected.has(s.id)?"checked":""}><span>${ctx.esc(s.name_ar)}</span></label>`).join("")
      : `<div class="cx-empty" style="padding:8px">لا توجد اختصاصات معرفة</div>`;
    const items=(inv||[]).map(i=>`<option value="${i.id}" ${recipe?.item_id===i.id?"selected":""}>${ctx.esc(i.name)} (${i.current_stock} ${ctx.esc(i.unit)})</option>`).join("");
    ctx.openModal(x?"تعديل الإجراء":"إجراء جديد",`
      <div class="cx-proc-form cx-svc-form">
        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head"><strong>بيانات الإجراء</strong><span>الاسم والسعر والمدة</span></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>اسم الإجراء *</label><input id="pfName" class="cx-input" value="${ctx.esc(x?.name||"")}" placeholder="مثال: قلع سن، حشوة"></div>
            <div class="cx-field"><label>التصنيف *</label><input id="pfCat" class="cx-input" value="${ctx.esc(x?.category||"")}" placeholder="جراحة · تجميل · أسنان"></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>السعر (د.ع)</label><input id="pfPrice" type="number" min="0" step="1000" class="cx-input" value="${x?.price||0}"></div>
            <div class="cx-field"><label>المدة (دقيقة)</label><input id="pfDuration" type="number" min="1" class="cx-input" value="${x?.duration_minutes||15}"></div>
          </div>
          <div class="cx-field"><label>الوصف</label><textarea id="pfDesc" class="cx-textarea" rows="3" placeholder="وصف داخلي للإجراء">${ctx.esc(x?.description||"")}</textarea></div>
        </section>
        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head"><strong>المخزون</strong><span>اختياري — يُخصم عند إكمال الزيارة</span></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>مادة مخزون</label><select id="pfItem" class="cx-select"><option value="">بدون</option>${items}</select></div>
            <div class="cx-field"><label>الكمية</label><input id="pfQty" type="number" step="0.001" min="0" class="cx-input" value="${recipe?.quantity||1}"></div>
          </div>
        </section>
        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head"><strong>الاختصاصات</strong><span>بدون اختيار = متاح للجميع</span></div>
          <div class="cx-svc-chip-grid">${chips}</div>
          <small class="cx-svc-hint">حدد الاختصاصات التي يظهر فيها هذا الإجراء.</small>
        </section>
        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head"><strong>خيارات</strong><span>الحجز · المالية · الحالة</span></div>
          <div class="cx-svc-option-grid">
            <label class="cx-svc-option"><input id="pfBooking" type="checkbox" ${x?.available_for_booking?"checked":""}><span><b>متاح للحجز</b><small>يظهر في الحجز الإلكتروني</small></span></label>
            <label class="cx-svc-option"><input id="pfCharge" type="checkbox" ${x?.creates_charge!==false?"checked":""}><span><b>قيد مالي</b><small>ينشئ Charge عند التنفيذ</small></span></label>
            <label class="cx-svc-option"><input id="pfActive" type="checkbox" ${x?.active!==false?"checked":""}><span><b>فعّال</b><small>ظاهر في دليل الإجراءات</small></span></label>
          </div>
        </section>
      </div>`,async()=>{
      const item=q("#pfItem").value;
      const p={
        name:q("#pfName").value,category:q("#pfCat").value,price:q("#pfPrice").value,
        duration_minutes:q("#pfDuration").value,description:q("#pfDesc").value,
        available_for_booking:q("#pfBooking").checked,creates_charge:q("#pfCharge").checked,active:q("#pfActive").checked,
        specialty_ids:Array.from(document.querySelectorAll("[data-procedure-specialty]:checked"),el=>Number(el.value)),
        recipe:item?[{item_id:Number(item),quantity:q("#pfQty").value}]:[]
      };
      return ctx.api(x?`/clinics/api/procedures/${x.id}`:"/clinics/api/procedures",{method:x?"PUT":"POST",body:JSON.stringify(p)});
    });
  }
  async function executionForm(s,ctx){const [o,procs]=await Promise.all([options(ctx),ctx.api("/clinics/api/procedures")]);ctx.openModal("إضافة إجراء للزيارة",`<div class="cx-field"><label>المريض *</label><select id="pePatient" class="cx-select">${patientOptions(o,ctx.esc,s.patient_id)}</select></div><div class="cx-field"><label>الزيارة *</label><input id="peVisit" type="number" class="cx-input" value="${s.visit_id}"></div><div class="cx-field"><label>الإجراء *</label><select id="peProc" class="cx-select">${procs.map(x=>`<option value="${x.id}">${ctx.esc(x.name)} · ${money(x.price)}</option>`).join('')}</select></div><div class="cx-field-row"><div class="cx-field"><label>المنفذ</label><select id="peDoctor" class="cx-select">${doctorOptions(o,ctx.esc,'')}</select></div><div class="cx-field"><label>الكمية</label><input id="peQty" type="number" min="1" class="cx-input" value="1"></div></div><div class="cx-field"><label>ملاحظات</label><textarea id="peNotes" class="cx-textarea"></textarea></div>`,async()=>ctx.api("/clinics/api/procedure-executions",{method:"POST",body:JSON.stringify({visit_id:Number(q("#peVisit").value),procedure_id:Number(q("#peProc").value),doctor_id:q("#peDoctor").value||null,quantity:q("#peQty").value,notes:q("#peNotes").value})}))}
  function executionDrawer(x,root,ctx){const d=drawer(root,drawerHead("تفاصيل الإجراء",x.procedure_name,ctx.esc)+summary(x,ctx.esc)+`<article class="cx-op-report"><h3>المواد المتوقعة</h3><p>${x.recipe.map(i=>`${ctx.esc(i.item_name)} × ${i.quantity*x.quantity}`).join('<br>')||'بدون مواد'}</p><h4>حالة الصرف</h4><p>${x.inventory_deducted?'تم الخصم مرة واحدة':'بانتظار إكمال الإجراء'}</p></article><div class="cx-op-drawer-actions"><button class="cx-btn" data-proc="in_progress">بدء الإجراء</button><button class="cx-btn cx-btn--primary" data-proc="completed">إكمال الإجراء</button><button class="cx-btn cx-btn--danger" data-proc="cancelled">إلغاء</button><a class="cx-btn" href="/clinics/patients/${x.patient_id}">فتح المريض</a><a class="cx-btn" href="/clinics/doctor/${x.visit_id}">فتح الزيارة</a></div>`);d.querySelectorAll("[data-proc]").forEach(b=>b.onclick=async()=>{await workflow(ctx,`/clinics/api/procedure-executions/${x.id}`,x.status,b.dataset.proc);ctx.render()})}

  function filters(s,ctx,defs){return defs.map(([key,label,opts])=>`<select class="cx-select" data-filter="${key}" aria-label="${label}">${opts.map(x=>`<option value="${x[0]}" ${String(s[key]||'')===String(x[0])?'selected':''}>${ctx.esc(x[1])}</option>`).join('')}</select>`).join('')}
  const doctorsList=ctx=>[['','كل الأطباء'],...(ctx.bootstrap?.doctors||[]).map(x=>[String(x.id),x.full_name])], priorities=()=>[['','كل الأولويات'],['normal','عادي'],['urgent','مستعجل']];
  function drawerHead(t,n,e){return `<header><div><h2>${t}</h2><p>${e(n)}</p></div><button class="cx-btn cx-btn--sm" data-close><i class="fa fa-xmark"></i></button></header>`}function summary(x,e){return `<div class="cx-op-summary"><div>${patient(x,e)}</div><div><span>الطبيب</span><strong>${e(x.doctor_name||'—')}</strong></div><div><span>الزيارة</span><strong>${x.visit_id?`VIS-${String(x.visit_id).padStart(5,'0')}`:'غير مرتبط'}</strong></div><div><span>الحالة</span>${status(x.status)}</div><div><span>التاريخ</span><strong>${fmt(x.ordered_at||x.due_date||x.performed_at)}</strong></div></div>`}
  async function workflow(ctx,url,old,statusValue){try{return await ctx.api(url,{method:"PATCH",body:JSON.stringify({expected_status:old,status:statusValue})})}catch(e){ctx.showNotice(e.message);throw e}}
  async function proceduresWithSpecialties(app,root,ctx){
    let catalog=[];
    const wrapped={...ctx};
    wrapped.api=async(url,options={})=>{
      if(/^\/clinics\/api\/procedures(?:\/\d+)?$/.test(url)&&['POST','PUT'].includes(options.method)){
        const payload=JSON.parse(options.body||'{}');
        payload.specialty_ids=Array.from(document.querySelectorAll('[data-procedure-specialty]:checked'),input=>Number(input.value));
        options={...options,body:JSON.stringify(payload)};
      }
      const result=await ctx.api(url,options);
      if(url.startsWith('/clinics/api/procedures?')&&result?.items)catalog=result.items;
      return result;
    };
    await procedures(app,root,wrapped);
    root.querySelectorAll('[data-edit]').forEach(button=>{
      const item=catalog.find(row=>row.id===Number(button.dataset.edit));
      if(!item?.specialty_ids?.length)return;
      const names=(ctx.bootstrap?.specialties||[]).filter(spec=>item.specialty_ids.includes(spec.id)).map(spec=>spec.name_ar).join('، ');
      button.closest('tr')?.querySelector('td strong')?.insertAdjacentHTML('afterend',`<small style="display:block">${ctx.esc(names)}</small>`);
    });
  }
  window.ClinicsOps={labs,radiology,followups,procedures:proceduresWithSpecialties};
})();
