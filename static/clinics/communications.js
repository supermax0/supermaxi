(() => {
  const TABS = [["inbox", "صندوق الوارد", "fa-inbox"], ["bookings", "الحجوزات", "fa-calendar-check"], ["reminders", "التذكيرات", "fa-bell"], ["link", "رابط الحجز", "fa-qrcode"], ["settings", "الإعدادات", "fa-sliders"]];
  const labels = {new:"جديدة",waiting_reply:"بانتظار الرد",waiting_patient:"بانتظار المريض",in_progress:"قيد المعالجة",resolved:"محلولة",closed:"مغلقة",pending_approval:"بانتظار الموافقة",approved:"مؤكد",rejected:"مرفوض",suggested:"تم اقتراح وقت"};
  const statusLabel = {sent:"أُرسلت",delivered:"وُصلت",read:"مقروءة",failed:"فشلت",skipped:"لم تُرسل",internal:"داخلية",queued:"بالانتظار"};
  const state = {tab:"inbox", selected:null, snapshot:null, conversations:[], templates:[], filter:{status:"",channel:"",q:""}, pollTimer:null, lastFingerprint:""};
  const q = (s, r=document) => r.querySelector(s);
  const qa = (s, r=document) => [...r.querySelectorAll(s)];
  const fmt = v => v ? window.FinoraTime.format(v, {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}) : "";

  function fillPlaceholders(body, conversation) {
    const s = state.snapshot?.settings || {};
    const slug = document.querySelector(".cx-shell")?.dataset?.tenantSlug || "";
    const values = {
      clinic_name: s.clinic_name || "العيادة",
      booking_link: `${location.origin}/c/${slug}`,
      clinic_hours: s.public_working_hours || "حسب جدول العيادة",
      clinic_location: s.public_location || "راجع موقع العيادة",
      patient_name: conversation?.display_name || "المريض",
      phone: conversation?.phone || "",
      doctor_name: conversation?.next_doctor || "الطبيب",
      appointment_date: conversation?.next_date || "—",
      appointment_time: conversation?.next_time || "—",
    };
    return String(body || "").replace(/\{\{(\w+)\}\}|\{(\w+)\}/g, (full, a, b) => {
      const key = a || b;
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : full;
    });
  }

  function waLabel(wa) {
    if (wa?.enabled) return "متصل";
    if (wa?.configured) return "مهيأ وموقوف — فعّله من الإعدادات";
    return wa?.error || "خطأ في الإعداد — اضبط WhatsApp Cloud API";
  }

  async function render(app, root, ctx) {
    stopPoll();
    state.snapshot = await ctx.api("/clinics/api/communications");
    state.templates = await ctx.api("/clinics/api/communications/templates");
    root.innerHTML = shell(ctx);
    bindShell(root, ctx);
    await showTab(root, ctx);
    startPoll(root, ctx);
  }

  function shell(ctx) {
    const k=state.snapshot.kpis, wa=state.snapshot.whatsapp;
    return `<section class="comms">
      <header class="comms-head"><div><h1>التواصل والحجوزات</h1><p>إدارة رسائل المرضى والحجوزات والتذكيرات</p></div>
        <label class="comms-search"><i class="fa fa-magnifying-glass"></i><input id="commsGlobalSearch" placeholder="ابحث عن مريض، رقم هاتف أو محادثة..."><kbd>Ctrl K</kbd></label>
        <div class="comms-head__actions"><button class="cx-btn" id="commsNewBooking"><i class="fa fa-calendar-plus"></i> حجز جديد</button><button class="cx-btn cx-btn--primary" id="commsNew"><i class="fa fa-plus"></i> رسالة جديدة</button></div></header>
      <nav class="comms-tabs">${TABS.map(([id,label,icon])=>`<button data-tab="${id}" class="${state.tab===id?'active':''}"><i class="fa ${icon}"></i>${label}</button>`).join("")}</nav>
      <div class="comms-kpis">
        ${kpi("رسائل جديدة",k.new_messages,"mint","fa-envelope")}${kpi("بانتظار الرد",k.waiting_reply,"amber","fa-clock")}${kpi("حجوزات اليوم",k.today_bookings,"blue","fa-calendar-day")}${kpi("طلبات حجز",k.new_booking_requests,"violet","fa-calendar-plus")}${kpi("تذكيرات اليوم",k.today_reminders,"rose","fa-bell")}
        <article class="comms-kpi teal ${wa.enabled?'':'warn'}" title="${ctx.esc(wa.error||'')}"><i class="fab fa-whatsapp"></i><span>WhatsApp<small>${ctx.esc(waLabel(wa))}</small></span><b class="dot ${wa.enabled?'on':''}"></b></article>
      </div><div id="commsBody"></div></section>`;
  }
  function kpi(label,value,color,icon){return `<article class="comms-kpi ${color}"><i class="fa ${icon}"></i><span>${label}<strong>${value||0}</strong></span></article>`}
  function bindShell(root,ctx){
    qa("[data-tab]",root).forEach(b=>b.onclick=async()=>{state.tab=b.dataset.tab;qa("[data-tab]",root).forEach(x=>x.classList.toggle("active",x===b));await showTab(root,ctx)});
    q("#commsNew",root).onclick=()=>newConversation(root,ctx);
    q("#commsNewBooking",root).onclick=()=>appointmentModal(null,root,ctx);
    const search=q("#commsGlobalSearch",root);search.oninput=()=>{if(state.tab!=="inbox"){state.tab="inbox";qa("[data-tab]",root).forEach(x=>x.classList.toggle("active",x.dataset.tab==="inbox"))}state.filter.q=search.value;clearTimeout(search._t);search._t=setTimeout(()=>loadConversations(root,ctx),250)};
    document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="k"){e.preventDefault();search.focus()}},{once:false});
  }
  async function showTab(root,ctx){const body=q("#commsBody",root);body.innerHTML='<div class="cx-empty">جاري التحميل…</div>';if(state.tab==="inbox")await inbox(body,root,ctx);if(state.tab==="bookings")await bookings(body,ctx);if(state.tab==="reminders")await reminders(body,ctx);if(state.tab==="link")await bookingLink(body,ctx);if(state.tab==="settings"){await settings(body,ctx);portalSettings(body,ctx)}}

  function stopPoll(){if(state.pollTimer){clearInterval(state.pollTimer);state.pollTimer=null}}
  function startPoll(root,ctx){
    stopPoll();
    state.pollTimer=setInterval(async()=>{
      if(document.hidden||state.tab!=="inbox")return;
      try{
        const params=new URLSearchParams(Object.fromEntries(Object.entries(state.filter).filter(([,v])=>v)));
        const rows=await ctx.api(`/clinics/api/communications/conversations?${params}`);
        const fingerprint=rows.map(c=>`${c.id}:${c.last_message_at}:${c.unread_count}:${c.status}`).join("|");
        if(fingerprint===state.lastFingerprint)return;
        state.lastFingerprint=fingerprint;
        state.conversations=rows;
        const box=q("#convItems",root);
        if(!box)return;
        const drafting=q("#messageText",root);
        const draft=drafting?drafting.value:"";
        const keepOpen=state.selected;
        box.innerHTML=state.conversations.map(c=>convItem(c,ctx)).join("")||'<div class="cx-empty">لا توجد محادثات مطابقة</div>';
        qa("[data-conv]",box).forEach(b=>b.onclick=()=>openConversation(Number(b.dataset.conv),root,ctx));
        if(keepOpen&&state.conversations.some(x=>x.id===keepOpen)){
          await openConversation(keepOpen,root,ctx,{preserveDraft:draft});
        }
        const snap=await ctx.api("/clinics/api/communications");
        state.snapshot=snap;
        const kpiBox=q(".comms-kpis",root);
        if(kpiBox){
          const k=snap.kpis,wa=snap.whatsapp;
          kpiBox.innerHTML=`${kpi("رسائل جديدة",k.new_messages,"mint","fa-envelope")}${kpi("بانتظار الرد",k.waiting_reply,"amber","fa-clock")}${kpi("حجوزات اليوم",k.today_bookings,"blue","fa-calendar-day")}${kpi("طلبات حجز",k.new_booking_requests,"violet","fa-calendar-plus")}${kpi("تذكيرات اليوم",k.today_reminders,"rose","fa-bell")}<article class="comms-kpi teal ${wa.enabled?'':'warn'}" title="${ctx.esc(wa.error||'')}"><i class="fab fa-whatsapp"></i><span>WhatsApp<small>${ctx.esc(waLabel(wa))}</small></span><b class="dot ${wa.enabled?'on':''}"></b></article>`;
        }
      }catch{/* ignore transient poll errors */}
    },8000);
  }
  function convItem(c,ctx){
    return `<button class="conv-item ${state.selected===c.id?'active':''}" data-conv="${c.id}"><span class="conv-avatar">${ctx.esc(c.display_name.slice(0,2))}</span><span class="conv-copy"><b>${ctx.esc(c.display_name)}</b><small><i class="${c.channel==='whatsapp'?'fab fa-whatsapp':'fa fa-globe'}"></i> ${ctx.esc(c.last_message||'لا رسائل بعد')}</small><em>${ctx.esc(c.assigned_name)}</em></span><span class="conv-meta"><time>${fmt(c.last_message_at)}</time>${c.unread_count?`<b>${c.unread_count}</b>`:''}<i class="status ${c.status}">${labels[c.status]||c.status}</i></span></button>`;
  }

  function portalSettings(body,ctx){
    const s=state.snapshot.settings,grid=q(".settings-grid",body),save=q("#saveCommsSettings",body);if(!grid||!save)return;
    grid.insertAdjacentHTML("beforeend",`<article class="comms-section settings-panel settings-panel--wide">
      <header><div><h2><i class="fa fa-globe"></i> بوابة المريض العامة</h2><p>المعلومات الظاهرة في رابط الحجز العام</p></div></header>
      <div class="toggle-list">
        <label class="settings-check"><input type="checkbox" id="setPublicProfile" ${s.public_profile_enabled?'checked':''}><span><b>صفحة العيادة العامة</b><small>إظهار ملف العيادة للزوار</small></span></label>
        <label class="settings-check"><input type="checkbox" id="setPublicChat" ${s.public_chat_enabled?'checked':''}><span><b>Web Chat</b><small>محادثة مباشرة من الرابط</small></span></label>
      </div>
      <div class="settings-subhead">معلومات الظهور</div>
      <div class="settings-stack">
        <div class="cx-field"><label>رابط الشعار</label><input class="cx-input" id="setPublicLogo" dir="ltr" value="${ctx.esc(s.public_logo_url||'')}" placeholder="https://..."></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>الموقع / العنوان</label><input class="cx-input" id="setPublicLocation" value="${ctx.esc(s.public_location||'')}"></div>
          <div class="cx-field"><label>ساعات العمل</label><input class="cx-input" id="setPublicHours" value="${ctx.esc(s.public_working_hours||'')}"></div>
        </div>
      </div>
    </article>`);
    const original=save.onclick;save.onclick=async e=>{await original(e);await ctx.api("/clinics/api/communications/settings",{method:"POST",body:JSON.stringify({public_profile_enabled:q("#setPublicProfile",body).checked,public_chat_enabled:q("#setPublicChat",body).checked,public_logo_url:q("#setPublicLogo",body).value,public_location:q("#setPublicLocation",body).value,public_working_hours:q("#setPublicHours",body).value})});ctx.showNotice("تم حفظ إعدادات بوابة المريض",false)};
  }

  async function inbox(body,root,ctx){
    body.innerHTML=`<section class="inbox-grid"><aside class="conv-list"><div class="conv-filters"><select id="convStatus"><option value="">الكل</option><option value="unread">غير مقروءة</option><option value="waiting_reply">بانتظار الرد</option><option value="waiting_patient">بانتظار المريض</option></select><select id="convChannel"><option value="">كل القنوات</option><option value="whatsapp">WhatsApp</option><option value="web_chat">Web Chat</option><option value="phone">هاتف</option></select></div><label class="conv-search"><i class="fa fa-search"></i><input id="convQ" placeholder="بحث في المحادثات"></label><div id="convItems"></div></aside><main class="chat-panel" id="chatPanel"><div class="chat-empty"><i class="fa fa-comments"></i><h3>اختر محادثة</h3><p>ستظهر الرسائل والأحداث هنا</p></div></main><aside class="patient-panel" id="patientPanel"><div class="chat-empty small"><i class="fa fa-user-injured"></i><p>بيانات المريض</p></div></aside></section>`;
    q("#convStatus",body).value=state.filter.status;q("#convChannel",body).value=state.filter.channel;q("#convQ",body).value=state.filter.q;
    q("#convStatus",body).onchange=e=>{state.filter.status=e.target.value;loadConversations(root,ctx)};q("#convChannel",body).onchange=e=>{state.filter.channel=e.target.value;loadConversations(root,ctx)};q("#convQ",body).oninput=e=>{state.filter.q=e.target.value;clearTimeout(e.target._t);e.target._t=setTimeout(()=>loadConversations(root,ctx),250)};
    await loadConversations(root,ctx);
  }
  async function loadConversations(root,ctx){const params=new URLSearchParams(Object.fromEntries(Object.entries(state.filter).filter(([,v])=>v)));state.conversations=await ctx.api(`/clinics/api/communications/conversations?${params}`);state.lastFingerprint=state.conversations.map(c=>`${c.id}:${c.last_message_at}:${c.unread_count}:${c.status}`).join("|");const box=q("#convItems",root);if(!box)return;box.innerHTML=state.conversations.map(c=>convItem(c,ctx)).join("")||'<div class="cx-empty">لا توجد محادثات مطابقة</div>';qa("[data-conv]",box).forEach(b=>b.onclick=()=>openConversation(Number(b.dataset.conv),root,ctx));if(state.selected&&state.conversations.some(x=>x.id===state.selected))await openConversation(state.selected,root,ctx)}
  async function openConversation(id,root,ctx,opts={}){state.selected=id;qa("[data-conv]",root).forEach(b=>b.classList.toggle("active",Number(b.dataset.conv)===id));const d=await ctx.api(`/clinics/api/communications/conversations/${id}`),c=d.conversation,chat=q("#chatPanel",root),panel=q("#patientPanel",root);const next=d.patient?.next_appointment;c.next_doctor=next?.doctor||"";c.next_date=next?.date||"";c.next_time=next?.time||"";chat.innerHTML=`<header class="chat-head"><button class="mobile-back" id="chatBack"><i class="fa fa-arrow-right"></i></button><span class="conv-avatar">${ctx.esc(c.display_name.slice(0,2))}</span><div><h2>${ctx.esc(c.display_name)}</h2><p>${ctx.esc(c.patient_file||c.phone)} · ${ctx.esc(c.channel)}</p></div><select id="convAssign"><option value="">غير مسند</option>${state.snapshot.staff.map(x=>`<option value="${x.id}" ${x.id===c.assigned_user_id?'selected':''}>${ctx.esc(x.name)}</option>`).join('')}</select><select id="convState">${["new","waiting_reply","waiting_patient","in_progress","resolved","closed"].map(x=>`<option value="${x}" ${x===c.status?'selected':''}>${labels[x]}</option>`).join('')}</select>${c.patient_id?`<a class="cx-btn cx-btn--sm" href="/clinics/patients/${c.patient_id}">فتح المريض</a>`:''}<button class="cx-btn cx-btn--sm" id="chatAppt"><i class="fa fa-calendar-plus"></i> موعد</button></header><div class="typing-lock">${c.opened_by_name&&c.opened_by!==c.assigned_user_id?`<i class="fa fa-circle-info"></i> هذه المحادثة مفتوحة عند ${ctx.esc(c.opened_by_name)}`:''}</div><div class="messages" id="messages">${d.messages.map(m=>message(m,ctx)).join('')||'<div class="chat-empty small">لا رسائل بعد</div>'}</div><footer class="composer"><div class="composer-tools"><button id="composerMore" title="المزيد"><i class="fa fa-plus"></i></button><button id="quickReply" title="رد جاهز"><i class="fa fa-bolt"></i></button><button id="bookingReply" title="إرسال رابط الحجز"><i class="fa fa-link"></i></button></div><textarea id="messageText" rows="1" placeholder="اكتب رسالة أو اختصار مثل /اهلا">${ctx.esc(opts.preserveDraft||'')}</textarea><button class="send" id="sendMessage"><i class="fa fa-paper-plane"></i></button></footer></main>`;
    panel.innerHTML=patientPanel(d.patient,c,ctx);q(".inbox-grid",root)?.classList.add("chat-open");
    const messages=q("#messages",chat);messages.scrollTop=messages.scrollHeight;
    q("#chatBack",chat).onclick=()=>q(".inbox-grid",root).classList.remove("chat-open");
    q("#convAssign",chat).onchange=e=>updateConv(id,{assigned_user_id:e.target.value},ctx);q("#convState",chat).onchange=e=>updateConv(id,{status:e.target.value},ctx);
    q("#chatAppt",chat).onclick=()=>appointmentModal(c.patient_id,root,ctx);q("#sendMessage",chat).onclick=()=>send(id,"text",root,ctx);q("#messageText",chat).onkeydown=e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send(id,"text",root,ctx)}};
    q("#bookingReply",chat).onclick=()=>{q("#messageText",chat).value=fillPlaceholders("يمكنكم حجز موعد من الرابط:\n{{booking_link}}",c)};q("#quickReply",chat).onclick=()=>quickReplies(chat,c,ctx);
    q("#composerMore",chat).onclick=()=>moreActions(id,c,root,ctx);bindPatientActions(panel,id,c,root,ctx);
  }
  function message(m,ctx){const internal=m.direction==="internal";return `<article class="message ${m.direction} ${internal?'note':''} ${m.status==='failed'||m.status==='skipped'?'warn':''}"><div>${m.type==="event"?'<i class="fa fa-clock-rotate-left"></i> ':''}${ctx.esc(m.content).replace(/\n/g,'<br>')}</div><footer>${ctx.esc(m.sender_name)} <time>${fmt(m.created_at)}</time><span>${statusLabel[m.status]||m.status}</span>${m.failed_reason?`<b title="${ctx.esc(m.failed_reason)}"><i class="fa fa-circle-exclamation"></i></b>`:''}</footer></article>`}
  function patientPanel(p,c,ctx){if(!p)return `<div class="unknown-patient"><i class="fa fa-user-plus"></i><h3>رقم غير مسجل</h3><p>${ctx.esc(c.phone)}</p><button class="cx-btn cx-btn--primary" id="createPatient">+ إنشاء مريض</button></div>`;return `<div class="patient-card"><span class="patient-avatar">${ctx.esc(p.full_name.slice(0,2))}</span><h3>${ctx.esc(p.full_name)}</h3><p>${ctx.esc(p.file_number)}</p><dl><div><dt>الهاتف</dt><dd dir="ltr">${ctx.esc(p.phone)}</dd></div><div><dt>العمر</dt><dd>${p.age??'—'}</dd></div><div><dt>آخر زيارة</dt><dd>${p.last_visit||'—'}</dd></div><div><dt>متابعات مفتوحة</dt><dd>${p.open_followups||0}</dd></div></dl>${p.next_appointment?`<div class="next-appt"><i class="fa fa-calendar-check"></i><span>الموعد القادم<strong>${p.next_appointment.date} · ${p.next_appointment.time}</strong><small>${ctx.esc(p.next_appointment.doctor)}</small></span></div>`:''}<div class="patient-actions"><a class="cx-btn cx-btn--sm" href="/clinics/patients/${p.id}">فتح الملف</a><button class="cx-btn cx-btn--sm" id="patientAppointment">+ موعد</button><button class="cx-btn cx-btn--sm" id="patientFollowup">+ متابعة</button><a class="cx-btn cx-btn--sm" href="tel:${ctx.esc(p.phone)}"><i class="fa fa-phone"></i></a></div></div>`}
  function bindPatientActions(panel,id,c,root,ctx){q("#createPatient",panel)?.addEventListener("click",()=>createPatient(id,c,root,ctx));q("#patientAppointment",panel)?.addEventListener("click",()=>appointmentModal(c.patient_id,root,ctx));q("#patientFollowup",panel)?.addEventListener("click",()=>followupModal(id,c,root,ctx))}
  async function updateConv(id,payload,ctx){await ctx.api(`/clinics/api/communications/conversations/${id}`,{method:"PUT",body:JSON.stringify(payload)});ctx.showNotice("تم تحديث المحادثة",false)}
  async function send(id,type,root,ctx){const input=q("#messageText",root),content=input.value.trim();if(!content)return;const result=await ctx.api(`/clinics/api/communications/conversations/${id}/messages`,{method:"POST",body:JSON.stringify({content,type})});input.value="";if(result?.warning)ctx.showNotice(result.warning,true);else if(result?.status==="failed"||result?.status==="skipped")ctx.showNotice(result.failed_reason||"الرسالة لم تصل عبر واتساب",true);await openConversation(id,root,ctx);await loadConversations(root,ctx)}
  function quickReplies(chat,conversation,ctx){ctx.openModal("الردود الجاهزة",`<div class="quick-replies">${state.templates.filter(x=>x.active).map(t=>`<button data-template="${t.id}"><b>${ctx.esc(t.shortcut)}</b><span>${ctx.esc(t.title)}</span><small>${ctx.esc(fillPlaceholders(t.body,conversation))}</small></button>`).join('')}</div>`,async()=>{} ,{saveLabel:"إغلاق"});qa("[data-template]").forEach(b=>b.onclick=()=>{const t=state.templates.find(x=>x.id===Number(b.dataset.template));q("#messageText",chat).value=fillPlaceholders(t.body,conversation);document.getElementById("cxModal").hidden=true})}
  function moreActions(id,c,root,ctx){ctx.openModal("إجراءات المحادثة",`<div class="action-menu"><button id="actNote"><i class="fa fa-note-sticky"></i> ملاحظة داخلية</button><button id="actFollow"><i class="fa fa-phone-volume"></i> إضافة متابعة</button><button id="actTask"><i class="fa fa-list-check"></i> إنشاء مهمة</button><button id="actSlots"><i class="fa fa-clock"></i> إرسال أوقات متاحة</button></div>`,async()=>{}, {saveLabel:"إغلاق"});q("#actNote").onclick=()=>noteModal(id,root,ctx);q("#actFollow").onclick=()=>followupModal(id,c,root,ctx);q("#actTask").onclick=()=>taskModal(id,root,ctx);q("#actSlots").onclick=()=>slotMessage(c,root,ctx)}
  function noteModal(id,root,ctx){ctx.openModal("ملاحظة داخلية",`<div class="cx-field"><label>لن ترسل للمريض</label><textarea class="cx-textarea" id="noteText"></textarea></div>`,async()=>{await ctx.api(`/clinics/api/communications/conversations/${id}/messages`,{method:"POST",body:JSON.stringify({content:q("#noteText").value,type:"internal_note"})});await openConversation(id,root,ctx)})}
  function createPatient(id,c,root,ctx){ctx.openModal("إنشاء مريض",`<div class="cx-field"><label>الاسم الكامل *</label><input class="cx-input" id="cpName"></div><div class="cx-field"><label>الهاتف *</label><input class="cx-input" id="cpPhone" value="${ctx.esc(c.phone)}" dir="ltr"></div><div class="cx-field-row"><div class="cx-field"><label>الجنس</label><select class="cx-select" id="cpGender"><option value="">—</option><option value="male">ذكر</option><option value="female">أنثى</option></select></div><div class="cx-field"><label>تاريخ الميلاد</label><input type="date" class="cx-input" id="cpDob"></div></div>`,async()=>{await ctx.api(`/clinics/api/communications/conversations/${id}/patient`,{method:"POST",body:JSON.stringify({full_name:q("#cpName").value,phone:q("#cpPhone").value,gender:q("#cpGender").value,date_of_birth:q("#cpDob").value})});await openConversation(id,root,ctx)})}
  function localIsoDate(offsetDays=0){const d=new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+offsetDays);const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,"0"),day=String(d.getDate()).padStart(2,"0");return `${y}-${m}-${day}`}
  function followupModal(id,c,root,ctx){
    const tomorrow=localIsoDate(1);
    ctx.openModal("متابعة جديدة",`<div class="cx-field"><label>التاريخ</label><input type="date" class="cx-input" id="fuDate" value="${tomorrow}" required></div><div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="fuNotes" placeholder="المريض طلب الاتصال..."></textarea></div>${c?.patient_id?"":'<p class="field-hint" style="margin:0;color:#9a6610">إن لم يُربط مريض بعد، سيُحاول النظام المطابقة برقم الهاتف أو سيطلب إنشاء ملف.</p>'}`,async()=>{
      const due=q("#fuDate")?.value;
      if(!due)throw new Error("تاريخ المتابعة مطلوب");
      try{
        await ctx.api(`/clinics/api/communications/conversations/${id}/followups`,{method:"POST",body:JSON.stringify({due_date:due,followup_type:"administrative",type:"administrative",notes:q("#fuNotes")?.value||""})});
      }catch(err){
        const msg=String(err?.message||err||"");
        if(msg.includes("اربط المحادثة")||msg.includes("مريض")){
          document.getElementById("cxModal").hidden=true;
          createPatient(id,c,root,ctx);
        }
        throw err;
      }
      await openConversation(id,root,ctx);
    },{skipRender:true,successMessage:"تم إنشاء المتابعة"});
  }
  function taskModal(id,root,ctx){ctx.openModal("مهمة جديدة",`<div class="cx-field"><label>المهمة</label><input class="cx-input" id="taskTitle" placeholder="اتصل بالمريض"></div><div class="cx-field-row"><div class="cx-field"><label>الاستحقاق</label><input type="datetime-local" class="cx-input" id="taskDue"></div><div class="cx-field"><label>المسؤول</label><select class="cx-select" id="taskUser">${state.snapshot.staff.map(x=>`<option value="${x.id}">${ctx.esc(x.name)}</option>`).join('')}</select></div></div>`,async()=>{await ctx.api(`/clinics/api/communications/conversations/${id}/tasks`,{method:"POST",body:JSON.stringify({title:q("#taskTitle").value,due_at:q("#taskDue").value,assigned_user_id:q("#taskUser").value})});await openConversation(id,root,ctx)})}
  function appointmentModal(patientId,root,ctx){const doctors=state.snapshot.doctors,services=state.snapshot.services,today=new Date().toISOString().slice(0,10);ctx.openModal("موعد جديد",`<div class="cx-field"><label>المريض *</label><input class="cx-input" id="apPatient" value="${patientId||''}" placeholder="رقم المريض"></div><div class="cx-field-row"><div class="cx-field"><label>الطبيب</label><select class="cx-select" id="apDoctor"><option value="">اختر</option>${doctors.map(x=>`<option value="${x.id}">${ctx.esc(x.full_name)}</option>`).join('')}</select></div><div class="cx-field"><label>الخدمة</label><select class="cx-select" id="apService"><option value="">—</option>${services.map(x=>`<option value="${x.id}">${ctx.esc(x.name)}</option>`).join('')}</select></div></div><div class="cx-field"><label>التاريخ</label><input type="date" class="cx-input" id="apDate" value="${today}"></div><div class="cx-field"><label>الأوقات المتاحة</label><div class="slot-grid" id="apSlots"><small>اختر الطبيب</small></div><input type="hidden" id="apTime"></div><div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="apNotes"></textarea></div>`,async()=>{if(!q("#apTime").value)throw Error("اختر وقتاً متاحاً");await ctx.api("/clinics/api/appointments",{method:"POST",body:JSON.stringify({patient_id:q("#apPatient").value,doctor_id:q("#apDoctor").value,service_id:q("#apService").value,appointment_date:q("#apDate").value,start_time:q("#apTime").value,notes:q("#apNotes").value,source:"whatsapp"})});if(state.selected)await openConversation(state.selected,root,ctx)});const load=async()=>{const d=q("#apDoctor").value;if(!d)return;const p=new URLSearchParams({doctor_id:d,service_id:q("#apService").value,date:q("#apDate").value});const slots=await ctx.api(`/clinics/api/appointments/slots?${p}`);q("#apSlots").innerHTML=(slots.slots||slots).map(t=>`<button type="button" data-time="${t}">${t}</button>`).join('')||'<small>لا توجد أوقات متاحة</small>';qa("[data-time]",q("#apSlots")).forEach(b=>b.onclick=()=>{qa("[data-time]",q("#apSlots")).forEach(x=>x.classList.remove("active"));b.classList.add("active");q("#apTime").value=b.dataset.time})};q("#apDoctor").onchange=load;q("#apService").onchange=load;q("#apDate").onchange=load}
  function slotMessage(c,root,ctx){appointmentModal(c.patient_id,root,ctx);const save=document.getElementById("cxModalSave");save.textContent="إدراج الأوقات في الرسالة";save.onclick=()=>{const slots=qa("[data-time]",document.getElementById("cxModalBody")).slice(0,3).map(x=>x.dataset.time);if(!slots.length)return;document.getElementById("cxModal").hidden=true;q("#messageText",root).value=`الأوقات المتاحة:\n${slots.join('\n')}\n\n${fillPlaceholders('للحجز: {{booking_link}}',c)}`}}

  function newConversation(root,ctx){ctx.openModal("رسالة جديدة",`<div class="cx-field"><label>رقم المريض (اختياري)</label><input class="cx-input" id="newPatient" type="number"></div><div class="cx-field"><label>رقم الهاتف *</label><input class="cx-input" id="newPhone" dir="ltr"></div><div class="cx-field"><label>القناة</label><select class="cx-select" id="newChannel"><option value="whatsapp">WhatsApp</option><option value="phone">هاتف</option><option value="web_chat">Web Chat</option></select></div>`,async()=>{const c=await ctx.api("/clinics/api/communications/conversations",{method:"POST",body:JSON.stringify({patient_id:q("#newPatient").value,phone:q("#newPhone").value,channel:q("#newChannel").value})});state.selected=c.id;state.tab="inbox";await showTab(root,ctx)})}

  async function bookings(body,ctx){const rows=await ctx.api("/clinics/api/communications/booking-requests");body.innerHTML=`<article class="comms-section"><header><div><h2>مركز الحجوزات الإلكترونية</h2><p>راجع واعتمد طلبات المرضى</p></div></header><div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>وقت الطلب</th><th>المريض</th><th>الطبيب</th><th>الخدمة</th><th>الموعد</th><th>المصدر</th><th>الحالة</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td>${fmt(r.created_at)}</td><td><b>${ctx.esc(r.patient_name)}</b><small class="block" dir="ltr">${ctx.esc(r.phone)}</small></td><td>${ctx.esc(r.doctor_name||'—')}</td><td>${ctx.esc(r.service_name||'—')}</td><td>${fmt(r.requested_start)}</td><td><span class="source-badge">${ctx.esc(r.source)}</span></td><td><span class="booking-status ${r.status}">${labels[r.status]||r.status}</span></td><td>${r.status==='pending_approval'?`<button class="cx-btn cx-btn--sm cx-btn--primary" data-approve="${r.id}">قبول</button><button class="cx-btn cx-btn--sm" data-reject="${r.id}">رفض</button>`:(r.appointment_id?`<a href="/clinics/appointments" class="cx-btn cx-btn--sm">فتح</a>`:'')}</td></tr>`).join('')||'<tr><td colspan="8"><div class="cx-empty">لا توجد طلبات حجز</div></td></tr>'}</tbody></table></div></article>`;qa("[data-approve]",body).forEach(b=>b.onclick=async()=>{await ctx.api(`/clinics/api/communications/booking-requests/${b.dataset.approve}/approve`,{method:"POST",body:"{}"});ctx.showNotice("تم تأكيد الحجز",false);await bookings(body,ctx)});qa("[data-reject]",body).forEach(b=>b.onclick=async()=>{await ctx.api(`/clinics/api/communications/booking-requests/${b.dataset.reject}/reject`,{method:"POST",body:"{}"});await bookings(body,ctx)})}
  async function reminders(body,ctx){const d=await ctx.api("/clinics/api/communications/reminders");body.innerHTML=`<div class="reminder-stats">${kpi("مجدولة اليوم",d.stats.scheduled_today,"amber","fa-clock")}${kpi("أرسلت",d.stats.sent,"mint","fa-check")}${kpi("فشلت",d.stats.failed,"rose","fa-triangle-exclamation")}</div><article class="comms-section reminder-rules"><header><div><h2>قواعد التذكير</h2><p>كل قاعدة تنشئ مرجعاً فريداً لكل موعد</p></div><button class="cx-btn cx-btn--sm" id="addReminderRule">+ قاعدة</button></header><div class="specific-links">${(d.rules||[]).map(r=>`<div><i class="fa fa-bell"></i><b>${ctx.esc(r.name)}</b><span>${r.hours_before} ساعة · ${ctx.esc(r.channel)}</span><button class="cx-btn cx-btn--sm" data-rule="${r.id}">تعديل</button></div>`).join('')||'<div class="cx-empty">سيتم إنشاء قاعدتي 24 ساعة وساعتين عند الجدولة</div>'}</div></article><article class="comms-section"><header><div><h2>سجل التذكيرات</h2><p>كل رسالة مرتبطة بمرجع فريد لمنع التكرار</p></div><button class="cx-btn cx-btn--primary" id="runReminders"><i class="fa fa-play"></i> معالجة المستحق</button></header><div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>المريض</th><th>النوع</th><th>القناة</th><th>وقت الإرسال</th><th>الحالة</th></tr></thead><tbody>${d.items.map(r=>`<tr><td>${ctx.esc(r.patient_name||'—')}</td><td>${ctx.esc(r.type)}</td><td>${ctx.esc(r.channel)}</td><td>${fmt(r.scheduled_for)}</td><td><span class="booking-status ${r.status}">${ctx.esc(r.status)}</span></td></tr>`).join('')||'<tr><td colspan="5"><div class="cx-empty">لا توجد تذكيرات</div></td></tr>'}</tbody></table></div></article>`;q("#runReminders",body).onclick=async()=>{const r=await ctx.api("/clinics/api/reminders/process",{method:"POST",body:"{}"});ctx.showNotice(`تمت معالجة ${r.processed} وإرسال ${r.sent}`,false);await reminders(body,ctx)};q("#addReminderRule",body).onclick=()=>reminderRuleModal(null,body,ctx);qa("[data-rule]",body).forEach(b=>b.onclick=()=>reminderRuleModal((d.rules||[]).find(x=>x.id===Number(b.dataset.rule)),body,ctx))}
  function reminderRuleModal(rule,body,ctx){ctx.openModal(rule?"تعديل قاعدة":"قاعدة تذكير",`<div class="cx-field-row"><div class="cx-field"><label>الاسم</label><input class="cx-input" id="ruleName" value="${ctx.esc(rule?.name||'')}"></div><div class="cx-field"><label>قبل الموعد (ساعة)</label><input class="cx-input" type="number" id="ruleHours" value="${rule?.hours_before||24}"></div></div><div class="cx-field"><label>القناة المهيأة</label><select class="cx-select" id="ruleChannel"><option value="whatsapp">WhatsApp</option></select><small>SMS وEmail لن يظهرا حتى يتوفر تكامل فعلي.</small></div><div class="cx-field"><label>نص التذكير</label><textarea class="cx-textarea" rows="6" id="ruleBody">${ctx.esc(rule?.template_body||'مرحباً {patient_name}\nنذكرك بموعدك مع {doctor_name}\nبتاريخ {date} الساعة {time}')}</textarea></div>`,async()=>{await ctx.api("/clinics/api/communications/reminder-rules",{method:"POST",body:JSON.stringify({id:rule?.id,name:q("#ruleName").value,hours_before:q("#ruleHours").value,channel:q("#ruleChannel").value,template_body:q("#ruleBody").value,active:true})});await reminders(body,ctx)});q("#ruleChannel").value='whatsapp'}
  async function bookingLink(body,ctx){const slug=document.querySelector('.cx-shell').dataset.tenantSlug,url=`${location.origin}/c/${slug}`;const qr=await ctx.api("/clinics/api/booking-qr").catch(()=>null);body.innerHTML=`<article class="comms-section link-manager"><header><div><h2>رابط الحجز العام</h2><p>شاركه على الشبكات أو اطبع QR للاستقبال</p></div></header><div class="booking-link-card"><div class="link-copy"><label>الرابط العام</label><code>${ctx.esc(url)}</code><div><button class="cx-btn cx-btn--primary" data-copy="${ctx.esc(url)}"><i class="fa fa-copy"></i> نسخ</button><a class="cx-btn" href="${ctx.esc(url)}" target="_blank"><i class="fa fa-arrow-up-right-from-square"></i> فتح</a></div></div>${qr?.qr_image?`<div class="compact-qr"><img src="${ctx.esc(qr.qr_image)}" alt="QR"><a download="finora-booking-qr.png" href="${ctx.esc(qr.qr_image)}">تحميل QR</a></div>`:''}</div><h3>روابط خاصة بالطبيب</h3><div class="specific-links">${state.snapshot.doctors.map(d=>{const u=`${url}?doctor=${d.id}`;return `<div><span class="conv-avatar">${ctx.esc(d.full_name.slice(0,2))}</span><b>${ctx.esc(d.full_name)}</b><button class="cx-btn cx-btn--sm" data-copy="${ctx.esc(u)}">نسخ الرابط</button><a class="cx-btn cx-btn--sm" href="${ctx.esc(u)}" target="_blank">QR / فتح</a></div>`}).join('')}</div><h3>روابط الخدمات</h3><div class="specific-links">${state.snapshot.services.map(s=>{const u=`${url}?service=${s.id}`;return `<div><i class="fa fa-stethoscope"></i><b>${ctx.esc(s.name)}</b><button class="cx-btn cx-btn--sm" data-copy="${ctx.esc(u)}">نسخ</button></div>`}).join('')}</div></article>`;qa("[data-copy]",body).forEach(b=>b.onclick=async()=>{await navigator.clipboard.writeText(b.dataset.copy);ctx.showNotice("تم نسخ الرابط",false)})}
  async function settings(body,ctx){
    const s=state.snapshot.settings;const wa=state.snapshot.whatsapp;
    const templatesHtml=state.templates.length
      ? state.templates.map(t=>`<button type="button" class="template-row" data-edit-template="${t.id}"><code>${ctx.esc(t.shortcut)}</code><span><b>${ctx.esc(t.title)}</b><small>${ctx.esc(t.body)}</small></span><i class="fa fa-pen"></i></button>`).join("")
      : `<div class="templates-empty"><i class="fa fa-bolt"></i><b>لا توجد رسائل جاهزة</b><p>أضف اختصارات مثل /اهلا لتسريع الرد على المرضى</p></div>`;
    body.innerHTML=`<div class="settings-grid">
      <article class="comms-section settings-panel">
        <header><div><h2><i class="fab fa-whatsapp"></i> قنوات التواصل</h2><p>لا نعرض حالة اتصال غير مؤكدة</p></div></header>
        <div class="channel-row ${wa.enabled?'is-ok':'is-warn'}"><i class="fab fa-whatsapp"></i><span><b>WhatsApp Cloud API</b><small>${ctx.esc(waLabel(wa))}</small></span><b class="dot ${wa.enabled?'on':''}"></b></div>
        ${wa.error?`<div class="settings-alert"><i class="fa fa-triangle-exclamation"></i><span>${ctx.esc(wa.error)}</span></div>`:""}
        <div class="settings-stack">
          <label class="settings-switch"><input type="checkbox" id="setWaEnabled" ${s.whatsapp_notifications_enabled?"checked":""}><span class="settings-switch__ui" aria-hidden="true"></span><span class="settings-switch__copy"><b>تفعيل إرسال واتساب</b><small>من الرقم الرسمي للعيادة</small></span></label>
          <div class="cx-field-row">
            <div class="cx-field"><label>رقم WhatsApp الرسمي</label><input class="cx-input" id="setCommsPhone" dir="ltr" value="${ctx.esc(s.clinic_whatsapp_number||"")}" placeholder="07xxxxxxxxx"></div>
            <div class="cx-field"><label>اسم العيادة</label><input class="cx-input" id="setClinicName" value="${ctx.esc(s.clinic_name||"")}"><small class="field-hint">يظهر بدل {{clinic_name}}</small></div>
          </div>
        </div>
      </article>
      <article class="comms-section settings-panel">
        <header><div><h2><i class="fa fa-calendar-check"></i> الحجز الإلكتروني</h2><p>كيف يؤكد المرضى مواعيدهم عبر الرابط العام</p></div></header>
        <div class="mode-choice" role="radiogroup" aria-label="وضع الحجز">
          <label class="mode-card"><input type="radio" name="bookingMode" value="direct" ${s.booking_mode==="direct"?"checked":""}><span class="mode-card__icon"><i class="fa fa-bolt"></i></span><span class="mode-card__copy"><b>تأكيد مباشر</b><small>ينشئ الموعد فوراً</small></span></label>
          <label class="mode-card"><input type="radio" name="bookingMode" value="approval" ${s.booking_mode==="approval"?"checked":""}><span class="mode-card__icon"><i class="fa fa-user-check"></i></span><span class="mode-card__copy"><b>موافقة الاستقبال</b><small>ينشئ طلب حجز للمراجعة</small></span></label>
        </div>
        <div class="settings-subhead">نافذة الحجز</div>
        <div class="cx-field-row">
          <div class="cx-field"><label>أقل مهلة (ساعة)</label><input class="cx-input" id="setMinNotice" type="number" min="0" value="${s.minimum_booking_notice_hours}"></div>
          <div class="cx-field"><label>الحجز المسبق (يوم)</label><input class="cx-input" id="setMaxDays" type="number" min="1" value="${s.maximum_advance_booking_days}"></div>
        </div>
        <div class="settings-subhead">صلاحيات المريض</div>
        <div class="toggle-list">
          <label class="settings-check"><input type="checkbox" id="setSameDay" ${s.allow_same_day_booking?"checked":""}><span><b>حجز نفس اليوم</b><small>يسمح بالحجز لليوم الحالي</small></span></label>
          <label class="settings-check"><input type="checkbox" id="setReschedule" ${s.allow_public_reschedule?"checked":""}><span><b>إعادة الجدولة</b><small>تعديل الموعد من الرابط</small></span></label>
          <label class="settings-check"><input type="checkbox" id="setCancel" ${s.allow_public_cancellation?"checked":""}><span><b>الإلغاء</b><small>إلغاء الموعد ذاتياً</small></span></label>
          <label class="settings-check"><input type="checkbox" id="setPrices" ${s.public_show_prices?"checked":""}><span><b>عرض الأسعار</b><small>إظهار الأسعار للمريض</small></span></label>
        </div>
      </article>
      <article class="comms-section settings-panel templates-card">
        <header><div><h2><i class="fa fa-message"></i> الرسائل الجاهزة</h2><p>اكتب الاختصار في المحادثة مثل /اهلا</p></div><button type="button" class="cx-btn cx-btn--sm" id="addTemplate"><i class="fa fa-plus"></i> قالب</button></header>
        <div class="templates-list">${templatesHtml}</div>
      </article>
    </div>
    <div class="settings-save"><button type="button" class="cx-btn cx-btn--primary" id="saveCommsSettings"><i class="fa fa-floppy-disk"></i> حفظ إعدادات التواصل والحجز</button></div>`;
    q("#saveCommsSettings",body).onclick=async()=>{
      await ctx.api("/clinics/api/communications/settings",{method:"POST",body:JSON.stringify({
        booking_mode:q('[name="bookingMode"]:checked',body).value,
        clinic_whatsapp_number:q("#setCommsPhone",body).value,
        clinic_name:q("#setClinicName",body).value,
        whatsapp_notifications_enabled:q("#setWaEnabled",body).checked,
        minimum_booking_notice_hours:q("#setMinNotice",body).value,
        maximum_advance_booking_days:q("#setMaxDays",body).value,
        allow_same_day_booking:q("#setSameDay",body).checked,
        allow_public_reschedule:q("#setReschedule",body).checked,
        allow_public_cancellation:q("#setCancel",body).checked,
        public_show_prices:q("#setPrices",body).checked
      })});
      state.snapshot=await ctx.api("/clinics/api/communications");
      ctx.showNotice("تم حفظ الإعدادات",false);
    };
    q("#addTemplate",body).onclick=()=>templateModal(null,body,ctx);
    qa("[data-edit-template]",body).forEach(b=>b.onclick=()=>templateModal(state.templates.find(x=>x.id===Number(b.dataset.editTemplate)),body,ctx));
  }
  function templateModal(t,body,ctx){ctx.openModal(t?"تعديل قالب":"قالب جديد",`<div class="cx-field-row"><div class="cx-field"><label>الاختصار</label><input class="cx-input" id="tplShortcut" value="${ctx.esc(t?.shortcut||'/')}"></div><div class="cx-field"><label>العنوان</label><input class="cx-input" id="tplTitle" value="${ctx.esc(t?.title||'')}"></div></div><div class="cx-field"><label>النص</label><textarea class="cx-textarea" id="tplBody" rows="5">${ctx.esc(t?.body||'')}</textarea><small>المتغيرات: {{clinic_name}} {{booking_link}} {{clinic_hours}} {{clinic_location}} {{patient_name}}</small></div>`,async()=>{await ctx.api("/clinics/api/communications/templates",{method:"POST",body:JSON.stringify({id:t?.id,shortcut:q("#tplShortcut").value,title:q("#tplTitle").value,body:q("#tplBody").value,active:true})});state.templates=await ctx.api("/clinics/api/communications/templates");await settings(body,ctx);portalSettings(body,ctx)})}
  window.ClinicsCommunications={render};
})();
