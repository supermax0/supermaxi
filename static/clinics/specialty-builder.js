/* Versioned forms editor: only drafts can be edited; published forms are copied. */
(() => {
  const types = ['text', 'textarea', 'number', 'date', 'time', 'select', 'multi_select', 'radio', 'checkbox', 'boolean', 'measurement', 'table', 'file', 'image', 'dental_chart', 'pediatric_growth_history', 'vaccination_history', 'development_tracker'];
  window.ClinicsSpecialtyBuilder = async function (root, specialty, ctx) {
    const { api, esc, showNotice, back, fieldHtml } = ctx;
    let draft = null;
    const safe = (fn) => async () => { try { await fn(); } catch (err) { showNotice(err.message || String(err)); } };
    const allFields = () => (draft.sections || []).flatMap(section => section.fields || []);
    const findField = key => allFields().find(field => field.key === key);
    function ruleEditor(f, i, j, locked) {
      const rule = f.visibility_rules || {};
      if (!rule.field_key) {
        return locked ? '<p class="cx-muted">يظهر دائماً</p>' : `<button type="button" class="cx-btn" data-add-rule="${i}:${j}">+ إضافة شرط إظهار</button>`;
      }
      const candidates = allFields().filter(item => item !== f && item.key);
      const operators = [['eq','يساوي'],['ne','لا يساوي'],['contains','يحتوي'],['not_empty','غير فارغ']];
      return `<div class="cx-field-row" data-rule-editor><div class="cx-field"><label>إظهار هذا الحقل عندما يكون الحقل</label><select class="cx-select" data-rule-field ${locked ? 'disabled' : ''}><option value="">اختر الحقل</option>${candidates.map(item => `<option value="${esc(item.key)}" ${item.key === rule.field_key ? 'selected' : ''}>${esc(item.label_ar || item.key)}</option>`).join('')}</select></div><div class="cx-field"><label>الشرط</label><select class="cx-select" data-rule-operator ${locked ? 'disabled' : ''}>${operators.map(([value,label]) => `<option value="${value}" ${value === (rule.operator || 'eq') ? 'selected' : ''}>${label}</option>`).join('')}</select></div><div class="cx-field"><label>القيمة</label><input class="cx-input" data-rule-value value="${esc(rule.value === undefined || rule.value === null ? '' : String(rule.value))}" ${(rule.operator === 'not_empty' || locked) ? 'disabled' : ''}></div>${locked ? '' : '<button type="button" class="cx-btn" data-remove-rule>إزالة الشرط</button>'}</div>`;
    }
    async function list() {
      const rows = await api(`/clinics/api/specialties/${specialty.id}/templates`);
      root.innerHTML = `<section class="cx-hero"><div><h1>نماذج ${esc(specialty.name_ar)}</h1><p>النشر يثبت الإصدار؛ الزيارات السابقة لا تتغير.</p></div><div class="cx-actions"><button class="cx-btn" id="sbBack">الاختصاصات</button><button class="cx-btn cx-btn--primary" id="sbNew">نموذج جديد</button></div></section><section class="cx-card">${rows.map(t => `<article class="cx-feed__item"><strong>${esc(t.name)} · v${t.version}</strong><small>${esc(t.status)}</small><div class="cx-actions"><button class="cx-btn" data-open="${t.id}">${t.status === 'draft' ? 'تحرير المسودة' : 'معاينة / إنشاء نسخة'}</button>${t.status !== 'archived' ? `<button class="cx-btn" data-archive="${t.id}">أرشفة</button>` : ''}</div></article>`).join('') || '<p>لا توجد نماذج بعد.</p>'}</section>`;
      root.querySelector('#sbBack').onclick = back;
      root.querySelector('#sbNew').onclick = () => { draft = { name: specialty.name_ar, sections: [], status: 'draft' }; editor(); };
      root.querySelectorAll('[data-open]').forEach(b => b.onclick = safe(async () => {
        draft = await api(`/clinics/api/visit-templates/${b.dataset.open}`);
        editor();
      }));
      root.querySelectorAll('[data-archive]').forEach(b => b.onclick = safe(async () => {
        if (!confirm('أرشفة هذا النموذج للزيارات الجديدة؟ ستبقى الزيارات السابقة محفوظة.')) return;
        await api(`/clinics/api/visit-templates/${b.dataset.archive}/archive`, {method:'POST'});
        await list();
      }));
    }
    function capture() {
      if (draft.status !== 'draft') return;
      draft.name = root.querySelector('#sbName').value;
      root.querySelectorAll('[data-section]').forEach(el => {
        const section = draft.sections[Number(el.dataset.section)];
        section.title_ar = el.querySelector('[data-title]').value;
        el.querySelectorAll('[data-field]').forEach(box => {
          const field = section.fields[Number(box.dataset.field)];
          ['key','label_ar','field_type','unit','placeholder'].forEach(k => field[k] = box.querySelector(`[data-prop="${k}"]`).value);
          field.required = box.querySelector('[data-prop="required"]').checked;
          const ruleBox = box.querySelector('[data-rule-editor]');
          if (ruleBox) {
            const fieldKey = ruleBox.querySelector('[data-rule-field]').value;
            const operator = ruleBox.querySelector('[data-rule-operator]').value;
            let value = ruleBox.querySelector('[data-rule-value]').value;
            const controller = findField(fieldKey);
            if (controller && ['boolean','checkbox'].includes(controller.field_type)) value = value === 'true';
            else if (controller && ['number','measurement'].includes(controller.field_type) && value !== '') value = Number(value);
            field.visibility_rules = fieldKey ? {field_key: fieldKey, operator, ...(operator === 'not_empty' ? {} : {value})} : {};
          } else field.visibility_rules = {};
          field.validation = JSON.parse(box.querySelector('[data-prop="validation"]').value || '{}');
          field.options = box.querySelector('[data-prop="options"]').value.split('\n').map(v => v.trim()).filter(Boolean);
        });
      });
    }
    function editor() {
      const locked = draft.status !== 'draft';
      root.innerHTML = `<section class="cx-hero"><div><h1>محرر نموذج الزيارة</h1><p>${locked ? 'نسخة ثابتة — أنشئ نسخة جديدة للتعديل' : 'مسودة — لن تظهر في الزيارات حتى النشر'}</p></div><div class="cx-actions"><button class="cx-btn" id="sbList">النماذج</button><button class="cx-btn" id="sbPreview">معاينة</button>${locked ? '<button class="cx-btn cx-btn--primary" id="sbCopy">إنشاء نسخة جديدة</button>' : '<button class="cx-btn" id="sbSave">حفظ مسودة</button><button class="cx-btn cx-btn--primary" id="sbPublish">حفظ ونشر</button>'}</div></section><section class="cx-card"><div class="cx-field"><label>اسم النموذج</label><input class="cx-input" id="sbName" value="${esc(draft.name)}" ${locked ? 'disabled' : ''}></div><div id="sbSections">${draft.sections.map((s,i) => `<fieldset data-section="${i}" style="margin:16px 0;padding:16px;border:1px solid var(--cx-line);border-radius:12px"><div class="cx-field"><label>عنوان القسم</label><input class="cx-input" data-title value="${esc(s.title_ar)}" ${locked ? 'disabled' : ''}></div>${s.fields.map((f,j) => `<article data-field="${j}" style="border-top:1px solid var(--cx-line);padding:12px 0"><div class="cx-field-row">${[['key','المفتاح الإنجليزي'],['label_ar','التسمية'],['unit','الوحدة'],['placeholder','نص توضيحي']].map(([k,l]) => `<div class="cx-field"><label>${l}</label><input class="cx-input" data-prop="${k}" value="${esc(f[k] || '')}" ${locked ? 'disabled' : ''}></div>`).join('')}<div class="cx-field"><label>نوع الحقل</label><select class="cx-select" data-prop="field_type" ${locked ? 'disabled' : ''}>${[...new Set([...types, f.field_type])].map(t => `<option ${t === f.field_type ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div><div class="cx-field"><label>خيارات (كل خيار بسطر)</label><textarea class="cx-textarea" data-prop="options" ${locked ? 'disabled' : ''}>${esc((f.options || []).join('\n'))}</textarea></div></div><div class="cx-field"><label>قواعد التحقق JSON (min / max / max_length)</label><textarea class="cx-textarea" data-prop="validation" ${locked ? 'disabled' : ''}>${esc(JSON.stringify(f.validation || {}))}</textarea></div>${ruleEditor(f,i,j,locked)}<label><input type="checkbox" data-prop="required" ${f.required ? 'checked' : ''} ${locked ? 'disabled' : ''}> مطلوب</label>${locked ? '' : `<div class="cx-actions"><button class="cx-btn" data-up="${i}:${j}">نقل لأعلى</button><button class="cx-btn" data-remove="${i}:${j}">حذف الحقل</button></div>`}</article>`).join('')}${locked ? '' : `<div class="cx-actions"><button class="cx-btn" data-add="${i}">إضافة حقل</button><button class="cx-btn" data-delete-section="${i}">حذف القسم</button></div>`}</fieldset>`).join('')}</div>${locked ? '' : '<button class="cx-btn" id="sbAddSection">إضافة قسم</button>'}<div id="sbPreviewBox"></div></section>`;
      root.querySelectorAll('[data-rule-operator]').forEach(select => select.onchange = () => {
        const value = select.closest('[data-rule-editor]').querySelector('[data-rule-value]');
        value.disabled = select.value === 'not_empty';
        if (value.disabled) value.value = '';
      });
      root.querySelectorAll('[data-add-rule]').forEach(button => button.onclick = () => {
        capture();
        const [i,j] = button.dataset.addRule.split(':').map(Number);
        const field = draft.sections[i].fields[j];
        const controller = allFields().find(item => item !== field && item.key);
        if (!controller) { showNotice('أضف حقلاً آخر وحدد مفتاحه قبل إنشاء الشرط'); return; }
        field.visibility_rules = {field_key: controller.key, operator: 'eq', value: ''};
        editor();
      });
      root.querySelectorAll('[data-remove-rule]').forEach(button => button.onclick = () => {
        capture();
        const box = button.closest('[data-field]');
        const i = Number(box.closest('[data-section]').dataset.section), j = Number(box.dataset.field);
        draft.sections[i].fields[j].visibility_rules = {};
        editor();
      });
      root.querySelector('#sbList').onclick = safe(list);
      root.querySelector('#sbPreview').onclick = () => {
        capture();
        root.querySelector('#sbPreviewBox').innerHTML = `<h2>معاينة نموذج الطبيب</h2>${draft.sections.map(s => `<h3>${esc(s.title_ar)}</h3>${s.fields.map((f,i) => fieldHtml({...f, id:i}, null, true)).join('')}`).join('')}`;
      };
      if (locked) {
        root.querySelector('#sbCopy').onclick = () => { draft = {...draft, id:null, status:'draft'}; editor(); };
        return;
      }
      root.querySelector('#sbAddSection').onclick = () => { capture(); draft.sections.push({title_ar:'قسم جديد',fields:[]}); editor(); };
      root.querySelectorAll('[data-add]').forEach(b => b.onclick = () => { capture(); draft.sections[Number(b.dataset.add)].fields.push({key:'',label_ar:'',field_type:'text',options:[]}); editor(); });
      root.querySelectorAll('[data-delete-section]').forEach(b => b.onclick = () => { capture(); draft.sections.splice(Number(b.dataset.deleteSection),1); editor(); });
      root.querySelectorAll('[data-remove]').forEach(b => b.onclick = () => { capture(); const [i,j]=b.dataset.remove.split(':').map(Number); draft.sections[i].fields.splice(j,1); editor(); });
      root.querySelectorAll('[data-up]').forEach(b => b.onclick = () => { capture(); const [i,j]=b.dataset.up.split(':').map(Number); if(j>0) {const fields=draft.sections[i].fields; [fields[j-1],fields[j]]=[fields[j],fields[j-1]];} editor(); });
      const save = async (publish) => {
        capture();
        draft.sections.forEach((s,i) => {s.sort_order=i; s.fields.forEach((f,j)=>f.sort_order=j);});
        draft = await api(draft.id ? `/clinics/api/visit-templates/${draft.id}` : `/clinics/api/specialties/${specialty.id}/templates`, {method:draft.id?'PUT':'POST',body:JSON.stringify(draft)});
        if(publish) draft = await api(`/clinics/api/visit-templates/${draft.id}/publish`,{method:'POST'});
        showNotice(publish ? 'تم نشر الإصدار' : 'تم حفظ المسودة',false);
        editor();
      };
      root.querySelector('#sbSave').onclick = safe(()=>save(false));
      root.querySelector('#sbPublish').onclick = safe(()=>save(true));
    }
    await list();
  };
})();
