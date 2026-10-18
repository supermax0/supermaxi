(() => {
  const qs=(s,r=document)=>r.querySelector(s);const fmt=v=>v?new Intl.DateTimeFormat("ar-IQ",{dateStyle:"medium"}).format(new Date(v)):"—";const initials=n=>String(n||"؟").split(/\s+/).slice(0,2).map(x=>x[0]).join("");
  const TAB_LABELS={overview:"الملخص",timeline:"الخط الزمني",visits:"الزيارات",diagnoses:"التشخيصات",prescriptions:"الأدوية والوصفات",labs:"التحاليل",radiology:"الأشعة",attachments:"المرفقات",vitals:"تطور العلامات الحيوية"};
  const TYPES={visit:["زيارة","stethoscope","teal"],diagnosis:["تشخيص","notes-medical","red"],prescription:["وصفة","prescription-bottle-medical","orange"],lab:["تحليل","flask","blue"],radiology:["أشعة","x-ray","purple"],attachment:["مرفق","paperclip","gray"],followup:["متابعة","phone","orange"],procedure:["إجراء","syringe","teal"]};
  function empty(t){return `<div class="cx-cl-empty"><i class="fa fa-folder-open"></i><p>${t}</p></div>`}
  function genderLabel(g){return g==="male"?"ذكر":g==="female"?"أنثى":g||"—"}
  function patientHeader(d,e){
    const p=d.patient,v=d.latest_visit;
    const age=p.age!=null?`${p.age} سنة`:"العمر غير محدد";
    return `<header class="cx-cl-patient">
      <div class="cx-cl-avatar">${e(initials(p.full_name))}</div>
      <div class="cx-cl-identity">
        <div class="cx-cl-kicker">ملف سريري · ${e(p.file_number)}</div>
        <h1>${e(p.full_name)}</h1>
        <div class="cx-cl-chips">
          <span>${e(age)}</span>
          <span>${e(genderLabel(p.gender))}</span>
          ${p.blood_type?`<span><i class="fa fa-droplet"></i>${e(p.blood_type)}</span>`:""}
        </div>
      </div>
      <div class="cx-cl-contact">
        <span><i class="fa fa-phone"></i><b dir="ltr">${e(p.phone||"—")}</b></span>
        <span><i class="fa fa-location-dot"></i>${e(p.city||p.address||"—")}</span>
      </div>
      <div class="cx-cl-allergy ${p.allergies?"has":""}">
        <span><i class="fa fa-triangle-exclamation"></i> الحساسية</span>
        <strong>${e(p.allergies||"لا توجد حساسية مسجلة")}</strong>
      </div>
      <div class="cx-cl-last">
        <span>آخر زيارة</span>
        <strong>${v?fmt(v.visit_date):"لا توجد"}</strong>
        <small>${v?.doctor_name?`الطبيب: ${e(v.doctor_name)}`:""}</small>
      </div>
    </header>`;
  }
  function printStyles(){
    return `*{box-sizing:border-box}
      body{margin:0;padding:28px 32px;color:#0f172a;background:#fff;
        font-family:"IBM Plex Sans Arabic",Tahoma,Arial,sans-serif;font-size:12.5px;line-height:1.55}
      .sheet{max-width:820px;margin:0 auto}
      .brand{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;
        padding-bottom:14px;border-bottom:3px solid #0f766e;margin-bottom:18px}
      .brand__mark{display:flex;align-items:center;gap:12px}
      .brand__logo{width:48px;height:48px;border-radius:12px;background:linear-gradient(145deg,#0d9488,#0e7490);
        color:#fff;display:grid;place-items:center;font-weight:800;font-size:18px}
      .brand h1{margin:0;font-size:20px;color:#0f766e}
      .brand p{margin:2px 0 0;color:#64748b;font-size:12px}
      .brand__meta{text-align:left;color:#64748b;font-size:11px}
      .brand__meta strong{display:block;color:#0f172a;font-size:13px;margin-bottom:2px}
      .doc-title{margin:0 0 14px;font-size:16px;color:#0f172a;letter-spacing:.02em}
      .patient-box{display:grid;grid-template-columns:1.2fr .8fr;gap:10px 18px;
        padding:14px 16px;border:1px solid #cbd5e1;border-radius:10px;background:#f8fafc;margin-bottom:16px}
      .patient-box .row{display:flex;gap:8px}
      .patient-box .lbl{color:#64748b;min-width:88px;font-weight:700}
      .patient-box .val{font-weight:700;color:#0f172a}
      .alert{padding:10px 12px;border-radius:8px;border:1px solid #fdba74;background:#fff7ed;
        color:#9a3412;margin-bottom:14px;font-weight:700}
      .alert.warn{border-color:#fca5a5;background:#fef2f2;color:#991b1b}
      h2{margin:18px 0 8px;font-size:13px;color:#0f766e;border-bottom:1px solid #99f6e4;padding-bottom:4px}
      table{width:100%;border-collapse:collapse;margin:0 0 6px}
      th,td{padding:7px 8px;border:1px solid #e2e8f0;text-align:right;vertical-align:top}
      th{background:#f0fdfa;color:#0f766e;font-size:11px}
      td{font-size:12px}
      .muted{color:#64748b}
      .empty{color:#94a3b8;font-style:italic;padding:6px 0}
      .vitals{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:4px}
      .vitals div{border:1px solid #e2e8f0;border-radius:8px;padding:8px;background:#fff}
      .vitals span{display:block;color:#64748b;font-size:10px;font-weight:700}
      .vitals strong{font-size:14px}
      .sign{display:grid;grid-template-columns:1fr 1fr;gap:40px;margin-top:36px}
      .sign div{border-top:1px solid #94a3b8;padding-top:8px;text-align:center;color:#475569;font-size:12px}
      .foot{margin-top:28px;padding-top:10px;border-top:1px dashed #cbd5e1;color:#64748b;font-size:10px;
        display:flex;justify-content:space-between;gap:12px}
      @media print{body{padding:12mm 14mm}.brand{border-bottom-width:2.5px}a{color:inherit;text-decoration:none}}`;
  }
  function printSection(title,rowsHtml,emptyText){
    return `<h2>${title}</h2>${rowsHtml||`<div class="empty">${emptyText}</div>`}`;
  }
  async function printPatientFile(patientId,ctx,app){
    const e=ctx.esc;
    try{
      const [overview,visitsData]=await Promise.all([
        ctx.api(`/clinics/api/clinical/patients/${patientId}?section=overview&per_page=20`),
        ctx.api(`/clinics/api/clinical/patients/${patientId}?section=visits&per_page=15`),
      ]);
      try{await ctx.api(`/clinics/api/clinical/patients/${patientId}/print-audit`,{method:"POST",body:"{}"})}catch(_){/* audit best-effort */}
      const p=overview.patient||{};
      const clinic=app?.bootstrap?.settings||{};
      const clinicName=clinic.clinic_name||"Finora Clinics";
      const clinicSub=[clinic.organization_mode_label,clinic.clinic_type_label,clinic.phone,clinic.address].filter(Boolean).join(" · ");
      const now=new Date().toLocaleString("ar-IQ");
      const age=p.age!=null?`${p.age} سنة`:"—";
      const meds=(overview.prescriptions||[]).flatMap(x=>x.items||[]);
      const vitals=overview.vitals;
      const visits=visitsData.items||[];
      const diagnoses=overview.diagnoses||[];
      const w=window.open("","_blank","width=900,height=1100");
      if(!w){ctx.showNotice("تعذر فتح نافذة الطباعة — اسمح بالنوافذ المنبثقة");return}
      const vitalsHtml=vitals?`<div class="vitals">${[
        ["ضغط الدم",vitals.blood_pressure],["النبض",vitals.heart_rate],["الحرارة",vitals.temperature],
        ["الوزن",vitals.weight_kg],["الطول",vitals.height_cm],["الأكسجين",vitals.oxygen_sat],
      ].map(([l,v])=>`<div><span>${l}</span><strong>${v??"—"}</strong></div>`).join("")}</div>
        <div class="muted">تاريخ القياس: ${fmt(vitals.recorded_at)}</div>`:"";
      const diagRows=diagnoses.length?`<table><thead><tr><th>التشخيص</th><th>الرمز</th><th>الحالة</th><th>التاريخ</th><th>الطبيب</th></tr></thead><tbody>${
        diagnoses.map(x=>`<tr><td>${e(x.title)}</td><td>${e(x.code||"—")}</td><td>${e(x.status)}</td><td>${fmt(x.created_at)}</td><td>${e(x.doctor_name||"—")}</td></tr>`).join("")
      }</tbody></table>`:"";
      const medRows=meds.length?`<table><thead><tr><th>الدواء</th><th>الجرعة</th><th>التكرار</th><th>المدة / التعليمات</th></tr></thead><tbody>${
        meds.map(x=>`<tr><td>${e(x.medicine_name)}</td><td>${e(x.dosage||"—")}</td><td>${e(x.frequency||"—")}</td><td>${e(x.duration||x.instructions||"—")}</td></tr>`).join("")
      }</tbody></table>`:"";
      const visitRows=visits.length?`<table><thead><tr><th>التاريخ</th><th>الطبيب</th><th>الشكوى / النوع</th><th>الحالة</th></tr></thead><tbody>${
        visits.map(v=>`<tr><td>${fmt(v.visit_date)}</td><td>${e(v.doctor_name||"—")}<div class="muted">${e(v.specialty_name||"")}</div></td><td>${e(v.chief_complaint||"زيارة")}</td><td>${e(v.status)}</td></tr>`).join("")
      }</tbody></table>`:"";
      const lab=overview.last_lab;
      const rad=overview.last_radiology;
      const labHtml=lab?`<table><thead><tr><th>التحاليل</th><th>الحالة</th><th>التاريخ</th><th>الطبيب</th></tr></thead><tbody><tr>
        <td>${e((lab.items||[]).map(i=>i.name).filter(Boolean).join("، ")||"طلب تحليل")}</td>
        <td>${e(lab.status)}</td><td>${fmt(lab.ordered_at)}</td><td>${e(lab.doctor_name||"—")}</td></tr></tbody></table>`:"";
      const radHtml=rad?`<table><thead><tr><th>الفحص</th><th>الحالة</th><th>التاريخ</th><th>الانطباع</th></tr></thead><tbody><tr>
        <td>${e(rad.body_part||rad.modality||"أشعة")}</td><td>${e(rad.status)}</td><td>${fmt(rad.ordered_at)}</td>
        <td>${e(rad.impression||"—")}</td></tr></tbody></table>`:"";
      const allergyBlock=p.allergies
        ?`<div class="alert warn">⚠ حساسية مسجّلة: ${e(p.allergies)}</div>`
        :`<div class="alert">لا توجد حساسية مسجّلة</div>`;
      const chronic=p.chronic_conditions?`<p><strong>الأمراض المزمنة:</strong> ${e(p.chronic_conditions)}</p>`:"";
      const notes=p.notes?`<p><strong>تنبيهات:</strong> ${e(p.notes)}</p>`:"";
      w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
        <title>الملف الطبي — ${e(p.full_name||"")}</title>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700&display=swap">
        <style>${printStyles()}</style></head><body><div class="sheet">
        <header class="brand">
          <div class="brand__mark">
            <div class="brand__logo">FC</div>
            <div><h1>${e(clinicName)}</h1><p>${e(clinicSub||"نظام إدارة العيادات")}</p></div>
          </div>
          <div class="brand__meta">
            <strong>الملف الطبي للمريض</strong>
            تاريخ الطباعة: ${e(now)}<br>
            رقم الملف: ${e(p.file_number||"—")}
          </div>
        </header>
        <h1 class="doc-title">ملخص السجل السريري</h1>
        <section class="patient-box">
          <div>
            <div class="row"><span class="lbl">الاسم</span><span class="val">${e(p.full_name||"—")}</span></div>
            <div class="row"><span class="lbl">رقم الملف</span><span class="val">${e(p.file_number||"—")}</span></div>
            <div class="row"><span class="lbl">الهاتف</span><span class="val" dir="ltr">${e(p.phone||"—")}</span></div>
            <div class="row"><span class="lbl">العنوان</span><span class="val">${e(p.city||p.address||"—")}</span></div>
          </div>
          <div>
            <div class="row"><span class="lbl">العمر</span><span class="val">${e(age)}</span></div>
            <div class="row"><span class="lbl">الجنس</span><span class="val">${e(genderLabel(p.gender))}</span></div>
            <div class="row"><span class="lbl">فصيلة الدم</span><span class="val">${e(p.blood_type||"—")}</span></div>
            <div class="row"><span class="lbl">المتابعة</span><span class="val">${fmt(overview.next_followup)||"—"}</span></div>
          </div>
        </section>
        ${allergyBlock}${chronic}${notes}
        ${printSection("آخر العلامات الحيوية",vitalsHtml,"لا توجد علامات حيوية مسجّلة")}
        ${printSection("التشخيصات النشطة",diagRows,"لا توجد تشخيصات مسجّلة")}
        ${printSection("الأدوية الحالية",medRows,"لا توجد أدوية حالية")}
        ${printSection("آخر التحاليل",labHtml,"لا توجد تحاليل")}
        ${printSection("آخر الأشعة",radHtml,"لا توجد أشعة")}
        ${printSection("آخر الزيارات",visitRows,"لا توجد زيارات")}
        <div class="sign">
          <div>توقيع الطبيب / الختم</div>
          <div>توقيع الاستقبال</div>
        </div>
        <footer class="foot">
          <span>مستند صادر من Finora Clinics — للاستخدام الطبي الداخلي</span>
          <span>${e(clinicName)} · ${e(now)}</span>
        </footer>
      </div></body></html>`);
      w.document.close();
      w.focus();
      setTimeout(()=>{try{w.print()}catch(_){}},350);
    }catch(err){
      ctx.showNotice(err.message||String(err));
    }
  }
  window.ClinicsClinical={async render(app,root,ctx){
    const u=new URLSearchParams(location.search);
    const s=app.clinical||(app.clinical={patientId:u.get("patient_id")||"",visitId:u.get("visit_id")||"",tab:"overview",page:1,timelineType:""});
    if(!s.patientId)return search(root,s,ctx);
    const data=await ctx.api(`/clinics/api/clinical/patients/${s.patientId}?section=${s.tab}&page=${s.page}&per_page=20&doctor_id=${encodeURIComponent(s.doctorId||"")}&specialty_id=${encodeURIComponent(s.specialtyId||"")}&date_from=${s.dateFrom||""}&date_to=${s.dateTo||""}&event_type=${s.timelineType||""}`);
    root.innerHTML=`<section class="cx-cl">
      ${patientHeader(data,ctx.esc)}
      ${currentVisit(data.current_visit,ctx.esc)}
      <div class="cx-cl-toolbar">
        <div class="cx-cl-actions">
          <button class="cx-btn cx-btn--primary" data-act="visit"><i class="fa fa-plus"></i> زيارة جديدة</button>
          <button class="cx-btn" data-act="appt"><i class="fa fa-calendar-plus"></i> موعد جديد</button>
          <a class="cx-btn" href="/clinics/labs?patient_id=${s.patientId}"><i class="fa fa-flask"></i> طلب تحليل</a>
          <a class="cx-btn" href="/clinics/radiology?patient_id=${s.patientId}"><i class="fa fa-x-ray"></i> طلب أشعة</a>
          <a class="cx-btn" href="/clinics/attachments?patient_id=${s.patientId}${s.visitId?`&visit_id=${s.visitId}`:""}"><i class="fa fa-paperclip"></i> رفع مرفق</a>
          <button class="cx-btn cx-btn--print" data-act="print"><i class="fa fa-print"></i> طباعة الملف</button>
          <button class="cx-btn cx-btn--ghost" data-act="change"><i class="fa fa-user"></i> تغيير المريض</button>
        </div>
        <div class="cx-cl-filters">
          <select class="cx-select" data-cl-filter="doctorId"><option value="">كل الأطباء</option>${(app.bootstrap?.doctors||[]).map(d=>`<option value="${d.id}" ${String(d.id)===String(s.doctorId)?"selected":""}>${ctx.esc(d.full_name)}</option>`).join("")}</select>
          <select class="cx-select" data-cl-filter="specialtyId"><option value="">كل الاختصاصات</option>${(app.bootstrap?.specialties||[]).map(d=>`<option value="${d.id}" ${String(d.id)===String(s.specialtyId)?"selected":""}>${ctx.esc(d.name_ar)}</option>`).join("")}</select>
          <label class="cx-cl-date">من<input type="date" class="cx-input" data-cl-filter="dateFrom" value="${s.dateFrom||""}"></label>
          <label class="cx-cl-date">إلى<input type="date" class="cx-input" data-cl-filter="dateTo" value="${s.dateTo||""}"></label>
        </div>
      </div>
      <nav class="cx-cl-tabs" aria-label="أقسام السجل">${Object.entries(TAB_LABELS).map(([k,v])=>`<button type="button" class="${s.tab===k?"active":""}" data-tab="${k}">${v}</button>`).join("")}</nav>
      <main class="cx-cl-body">${body(s.tab,data,ctx.esc,s)}</main>
    </section>`;
    root.querySelectorAll("[data-cl-filter]").forEach(input=>input.onchange=()=>{s[input.dataset.clFilter]=input.value;s.page=1;ctx.render()});
    root.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{s.tab=b.dataset.tab;s.page=1;ctx.render()});
    root.querySelectorAll("[data-timeline]").forEach(b=>b.onclick=()=>{s.timelineType=b.dataset.timeline;s.page=1;ctx.render()});
    qs('[data-act="change"]',root).onclick=()=>{s.patientId="";history.replaceState(null,"","/clinics/clinical");ctx.render()};
    qs('[data-act="appt"]',root).onclick=()=>ctx.promptNewAppointment(Number(s.patientId));
    qs('[data-act="visit"]',root).onclick=async()=>{try{const v=await ctx.api("/clinics/api/visits",{method:"POST",body:JSON.stringify({patient_id:Number(s.patientId)})});location.href=`/clinics/doctor/${v.id}`}catch(err){ctx.showNotice(err.message)}};
    qs('[data-act="print"]',root).onclick=()=>printPatientFile(s.patientId,ctx,app);
    root.querySelectorAll("[data-page]").forEach(b=>b.onclick=()=>{s.page=Number(b.dataset.page);ctx.render()});
  }};
  async function search(root,s,ctx){
    const recent=await ctx.api("/clinics/api/clinical/recent-patients");
    const count=Array.isArray(recent)?recent.length:0;
    root.innerHTML=`<section class="cx-cl-search">
      <div class="cx-cl-search__title">
        <i class="fa fa-folder-medical" aria-hidden="true"></i>
        <h1>السجل الطبي</h1>
        <p>ابحث عن مريض لعرض تاريخه السريري الكامل</p>
      </div>
      <div class="cx-cl-search__panel">
        <label class="cx-cl-search__field">
          <i class="fa fa-magnifying-glass" aria-hidden="true"></i>
          <input class="cx-input" id="clQ" placeholder="ابحث بالاسم أو الهاتف أو رقم الملف..." autocomplete="off">
        </label>
        <div id="clResults" class="cx-cl-search__results" hidden></div>
      </div>
      <div class="cx-cl-search__section">
        <div class="cx-cl-search__section-head">
          <h2>المرضى الذين تم فتح ملفاتهم مؤخراً</h2>
          <span class="cx-cl-search__count">${count}</span>
        </div>
        <div class="cx-cl-recent">${count?recent.map(p=>patientCard(p,ctx.esc)).join(""):empty("لا يوجد مرضى بعد")}</div>
      </div>
    </section>`;
    let t;
    qs("#clQ",root).oninput=e=>{
      clearTimeout(t);
      const q=String(e.target.value||"").trim();
      const box=qs("#clResults",root);
      if(!q){box.hidden=true;box.innerHTML="";return}
      t=setTimeout(async()=>{
        const rows=await ctx.api(`/clinics/api/clinical/recent-patients?q=${encodeURIComponent(q)}`);
        box.hidden=false;
        box.innerHTML=rows.length
          ?`<div class="cx-cl-search__section-head"><h2>نتائج البحث</h2><span class="cx-cl-search__count">${rows.length}</span></div>${patients(rows,ctx.esc)}`
          :empty("لا توجد نتائج مطابقة");
        bind(root,s,ctx);
      },300);
    };
    bind(root,s,ctx);
  }
  function patients(rows,e){return `<div class="cx-cl-hits">${rows.map(p=>patientCard(p,e)).join("")}</div>`}
  function patientCard(p,e){
    const visit=p.last_visit?`آخر زيارة ${fmt(p.last_visit)}`:"لا توجد زيارات";
    return `<button type="button" class="cx-cl-hit" data-patient="${p.id}">
      <span class="cx-cl-avatar">${e(initials(p.full_name))}</span>
      <span class="cx-cl-hit__body">
        <strong>${e(p.full_name)}</strong>
        <small>${e(p.file_number)} · <b dir="ltr">${e(p.phone||"بدون هاتف")}</b></small>
      </span>
      <em class="cx-cl-hit__meta">${visit}</em>
      <i class="fa fa-chevron-left" aria-hidden="true"></i>
    </button>`;
  }function bind(root,s,ctx){root.querySelectorAll("[data-patient]").forEach(b=>b.onclick=()=>{s.patientId=b.dataset.patient;history.replaceState(null,"",`/clinics/clinical?patient_id=${s.patientId}`);ctx.render()})}
  function currentVisit(v,e){if(!v)return"";return `<div class="cx-cl-current"><span class="cx-cl-pulse"></span><div><strong>زيارة جارية الآن</strong><small>${e(v.doctor_name||"بدون طبيب")} · بدأت ${v.started_at?new Date(v.started_at).toLocaleTimeString("ar-IQ",{hour:"2-digit",minute:"2-digit"}):"الآن"}</small></div><a class="cx-btn cx-btn--primary" href="/clinics/doctor/${v.id}">فتح الزيارة الحالية</a></div>`}
  function body(tab,d,e,s){if(tab==="vitals")return vitalTrends(d,e);if(tab==="overview")return overview(d,e);if(tab==="timeline")return timeline(d,e,s);if(tab==="visits")return visits(d,e);if(tab==="diagnoses")return diagnoses(d,e);if(tab==="prescriptions")return prescriptions(d,e);if(tab==="labs")return labs(d,e);if(tab==="radiology")return radiology(d,e);return attachments(d,e)}
  function overview(d,e){
    const p=d.patient,v=d.vitals;
    const meds=(d.prescriptions||[]).flatMap(x=>x.items||[]);
    return `<div class="cx-cl-overview">
      <section class="cx-cl-maincol">
        <article class="cx-cl-card cx-cl-card--alert ${p.allergies?"has":""}">
          <h2><i class="fa fa-triangle-exclamation"></i> الحساسيات</h2>
          <p>${e(p.allergies||"لا توجد حساسية مسجلة")}</p>
        </article>
        <article class="cx-cl-card">
          <h2><i class="fa fa-notes-medical"></i> المشاكل / التشخيصات النشطة</h2>
          ${(d.diagnoses||[]).map(x=>`<div class="cx-cl-row"><span><strong>${e(x.title)}</strong><small>منذ ${fmt(x.created_at)}</small></span><b class="cx-cl-status">${e(x.status)}</b></div>`).join("")||empty("لا توجد تشخيصات مسجلة")}
        </article>
        <article class="cx-cl-card">
          <h2><i class="fa fa-pills"></i> الأدوية الحالية</h2>
          ${meds.map(x=>`<div class="cx-cl-row"><span><strong>${e(x.medicine_name)} ${e(x.dosage)}</strong><small>${e(x.frequency||x.instructions||"")}</small></span><b class="cx-cl-status">نشط</b></div>`).join("")||empty("لا توجد أدوية حالية")}
        </article>
      </section>
      <aside class="cx-cl-side">
        <article class="cx-cl-card">
          <h2><i class="fa fa-heart-pulse"></i> آخر العلامات الحيوية</h2>
          ${v?`<div class="cx-cl-vitals">${[["ضغط الدم",v.blood_pressure],["النبض",v.heart_rate],["الحرارة",v.temperature],["الوزن",v.weight_kg],["الطول",v.height_cm],["الأكسجين",v.oxygen_sat]].map(x=>`<div><span>${x[0]}</span><strong>${x[1]??"—"}</strong></div>`).join("")}</div><small>قُيست ${fmt(v.recorded_at)}</small>`:empty("لا توجد علامات حيوية")}
        </article>
        <article class="cx-cl-card cx-cl-card--soft">
          <h2><i class="fa fa-calendar-check"></i> المتابعة القادمة</h2>
          <strong class="cx-cl-followup">${fmt(d.next_followup)}</strong>
        </article>
        <article class="cx-cl-card">
          <h2><i class="fa fa-flask"></i> آخر التحاليل</h2>
          ${d.last_lab?`<strong>${e((d.last_lab.items||[]).map(x=>x.name).join("، ")||"طلب تحليل")}</strong><small>${fmt(d.last_lab.ordered_at)} · ${e(d.last_lab.status)}</small>`:empty("لا توجد تحاليل")}
        </article>
        <article class="cx-cl-card">
          <h2><i class="fa fa-x-ray"></i> آخر الأشعة</h2>
          ${d.last_radiology?`<strong>${e(d.last_radiology.body_part||d.last_radiology.modality)}</strong><small>${fmt(d.last_radiology.ordered_at)} · ${e(d.last_radiology.status)}</small>`:empty("لا توجد أشعة")}
        </article>
      </aside>
    </div>`;
  }
  function timeline(d,e,s){const items=(d.items||[]).filter(x=>!s.timelineType||x.type===s.timelineType);return `<div class="cx-cl-timeline-filter"><button data-timeline="" class="${!s.timelineType?"active":""}">كل الأحداث</button>${Object.entries(TYPES).map(([k,v])=>`<button data-timeline="${k}" class="${s.timelineType===k?"active":""}">${v[0]}</button>`).join("")}</div><div class="cx-cl-timeline">${items.map(x=>{const t=TYPES[x.type],z=x.data,title=x.type==="visit"?(z.chief_complaint||"زيارة طبية"):x.type==="diagnosis"?z.title:x.type==="prescription"?`${(z.items||[]).length} أدوية`:x.type==="lab"?(z.items||[]).map(i=>i.name).join("، "):x.type==="radiology"?(z.body_part||z.modality):x.type==="procedure"?z.procedure_name:x.type==="followup"?(z.event==="contact"?"تم التواصل مع المريض":`متابعة مستحقة ${z.due_date||""}`):z.file_name;return `<article><div class="cx-cl-event cx-cl-event--${t[2]}"><i class="fa fa-${t[1]}"></i></div><time>${fmt(x.at)}</time><div><span>${t[0]}</span><h3>${e(title||t[0])}</h3><p>${e(z.doctor_name||z.notes||z.status||"")}</p></div></article>`}).join("")||empty("لا توجد أحداث طبية")}</div>${pager(d)}`}
  function visits(d,e){return table(["التاريخ","الطبيب","نوع الزيارة","التشخيص","الحالة","الإجراء"],(d.items||[]).map(v=>`<tr><td>${fmt(v.visit_date)}</td><td>${e(v.doctor_name||"—")}<small>${e(v.specialty_name||"")} ${v.template_version?"v"+v.template_version:""}</small></td><td>${e(v.chief_complaint||"زيارة")}</td><td>${e(v.clinical_notes||"—")}</td><td>${e(v.status)}</td><td><a class="cx-btn cx-btn--sm" href="/clinics/doctor/${v.id}">فتح</a></td></tr>`),"لا توجد زيارات")+pager(d)}
  function diagnoses(d,e){return table(["التشخيص","الحالة","أول تسجيل","آخر تحديث","سجل بواسطة"],(d.items||[]).map(x=>`<tr><td><strong>${e(x.title)}</strong><small>${e(x.code)}</small></td><td>${e(x.status)}</td><td>${fmt(x.created_at)}</td><td>${fmt(x.updated_at)}</td><td>${e(x.doctor_name||"—")}</td></tr>`),"لا توجد تشخيصات مسجلة")+pager(d)}
  function prescriptions(d,e){return `<div class="cx-cl-list">${(d.items||[]).map(x=>`<article class="cx-cl-card"><div><time>${fmt(x.created_at)}</time><h3>${e(x.doctor_name||"وصفة طبية")}</h3><p>${(x.items||[]).map(i=>`${e(i.medicine_name)} ${e(i.dosage)} · ${e(i.frequency)}`).join("<br>")}</p></div><a class="cx-btn" href="/clinics/doctor/${x.visit_id}">فتح الوصفة</a></article>`).join("")||empty("لا توجد وصفات")}</div>${pager(d)}`}
  function labs(d,e){return listOrders(d,e,"flask",x=>(x.items||[]).map(i=>`${e(i.name)}${i.value?` — ${e(i.value)} ${e(i.unit)}`:""}`).join("<br>"),"لا توجد تحاليل")}
  function radiology(d,e){return listOrders(d,e,"x-ray",x=>`${e(x.body_part||x.modality)}${x.impression?`<br><small>${e(x.impression)}</small>`:""}`,"لا توجد أشعة")}
  function listOrders(d,e,icon,content,msg){return `<div class="cx-cl-list">${(d.items||[]).map(x=>`<article class="cx-cl-card"><i class="fa fa-${icon}"></i><div><time>${fmt(x.ordered_at)}</time><h3>${content(x)}</h3><p>${e(x.status)} · ${e(x.doctor_name||"")}</p></div>${x.visit_id?`<a class="cx-btn" href="/clinics/doctor/${x.visit_id}">عرض</a>`:""}</article>`).join("")||empty(msg)}</div>${pager(d)}`}
  function attachments(d,e){return `<div class="cx-cl-attachments">${(d.items||[]).map(a=>`<a class="cx-cl-card" href="/clinics/attachments?patient_id=${a.patient_id}"><i class="fa fa-${a.mime_type?.startsWith("image/")?"file-image":"file"}"></i><div><h3>${e(a.file_name)}</h3><p>${e(a.category_label)} · ${fmt(a.document_date||a.uploaded_at)}</p></div><span>معاينة</span></a>`).join("")||empty("لا توجد مرفقات لهذا المريض")}</div>${pager(d)}`}

  function vitalTrends(d,e){
    const rows=d.items||[];
    const measures=[['weight_kg','الوزن'],['oxygen_sat','SpO2'],['temperature','الحرارة'],['blood_glucose','سكر الدم'],['bmi','BMI']];
    return '<p>قياسات تاريخية للتوثيق فقط، دون تفسير أو تشخيص آلي. آخر 200 قياس.</p>'+measures.map(([key,label])=>{
      const points=rows.filter(r=>r[key]!==null&&Number.isFinite(Number(r[key])));
      if(!points.length)return '<article class="cx-cl-card"><h3>'+label+'</h3>لا توجد قياسات</article>';
      const values=points.map(p=>Number(p[key])),min=Math.min(...values),max=Math.max(...values);
      const coords=values.map((v,i)=>[(i/(values.length-1||1))*560+20,100-(v-min)/(max-min||1)*80]);
      return `<article class="cx-cl-card"><h3>${label}</h3><svg viewBox="0 0 600 120" role="img" aria-label="${label}" style="width:100%;max-height:160px"><polyline points="${coords.map(p=>p.join(',')).join(' ')}" fill="none" stroke="currentColor" stroke-width="2"/>${coords.map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="3"><title>${e(points[i].recorded_at)}: ${values[i]}</title></circle>`).join('')}</svg><small>${fmt(points[0].recorded_at)} — ${fmt(points.at(-1).recorded_at)}</small><details><summary>عرض القيم</summary>${points.map(p=>`<p>${fmt(p.recorded_at)}: ${p[key]}</p>`).join('')}</details></article>`;
    }).join('')+table(['التاريخ','ضغط الدم'],rows.filter(r=>r.blood_pressure).map(r=>`<tr><td>${fmt(r.recorded_at)}</td><td>${e(r.blood_pressure)}</td></tr>`),'لا توجد قياسات ضغط');
  }
  function table(head,rows,msg){return `<div class="cx-card cx-table-wrap"><table class="cx-table"><thead><tr>${head.map(x=>`<th>${x}</th>`).join("")}</tr></thead><tbody>${rows.join("")||`<tr><td colspan="${head.length}">${empty(msg)}</td></tr>`}</tbody></table></div>`}function pager(d){return d.pages>1?`<div class="cx-cl-pager"><button class="cx-btn" data-page="${d.page-1}" ${d.page<=1?"disabled":""}>السابق</button><span>${d.page} / ${d.pages}</span><button class="cx-btn" data-page="${d.page+1}" ${d.page>=d.pages?"disabled":""}>التالي</button></div>`:""}
})();
