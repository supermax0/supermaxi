/* Generic options editor for the web form; the server owns prices and stock. */
(function () {
  const root = document.querySelector('[data-product-options-editor]');
  if (!root) return;
  const form = root.closest('form');
  const config = JSON.parse(root.querySelector('[data-option-config]').textContent);
  const editing = root.dataset.edit === '1';
  const originalStock = Number(root.dataset.stock);
  const original = config.rows;
  let axes = config.axes.length ? config.axes : ['اللون'];
  let rows = original.map((row) => ({ ...row, attributes: row.attributes || { اللون: row.name }, active: row.active !== false }));
  const enabled = root.querySelector('[data-option-enable]');
  const content = root.querySelector('[data-option-content]');
  const payload = root.querySelector('[data-option-payload]');
  const error = root.querySelector('[data-option-error]');
  enabled.checked = rows.length > 0;
  enabled.disabled = original.length > 0;
  const el = (tag, text) => { const node = document.createElement(tag); if (text) node.textContent = text; return node; };
  const help = (text) => { const node = el('details'); node.className = 'inv-option-help'; const summary = el('summary', '?'); summary.setAttribute('aria-label', 'شرح الميزة'); node.append(summary, el('p', text)); return node; };
  const button = (text, callback) => { const node = el('button', text); node.type = 'button'; node.className = 'inv-option-btn'; node.addEventListener('click', callback); return node; };
  const field = (label, value, callback, type = 'text') => {
    const wrapper = el('label', label); const input = el('input'); input.type = type; input.value = value ?? ''; input.setAttribute('aria-label', label);
    if (type === 'number') { input.min = '0'; input.step = '1'; input.dir = 'ltr'; }
    input.addEventListener('input', () => callback(input.value)); wrapper.append(input); return { wrapper, input };
  };
  function render() {
    content.hidden = !enabled.checked;
    content.replaceChildren(); payload.disabled = !enabled.checked;
    const oldToggle = document.getElementById('hasColorsCheck');
    const oldBlock = document.getElementById('colorVariantsBlock');
    if (oldToggle) oldToggle.closest('.inv-check-row').hidden = enabled.checked;
    if (oldBlock) { oldBlock.hidden = enabled.checked; if (enabled.checked) oldBlock.style.display = 'none'; }
    if (!enabled.checked) return;
    const attrs = el('div'); attrs.className = 'inv-option-fields';
    attrs.append(el('span', 'صفات المنتج: ' + axes.join(' / ')), help('أضف الصفات التي يحتاجها المنتج فقط. الصفات المحفوظة ثابتة لحماية الفواتير. عند إضافة صفة جديدة تتوقف الخيارات القديمة حتى توزّع رصيدها على التركيبات الجديدة.'));
    if (!rows.length) ['اللون', 'المقاس', 'الحجم', 'السعة'].forEach((axis) => attrs.append(button(axis + ' فقط', () => { axes = [axis]; render(); })));
    let newAxis = ''; const axisField = field('اسم صفة إضافية', '', (value) => { newAxis = value; }); axisField.input.maxLength = 24;
    attrs.append(axisField.wrapper, button('إضافة صفة', () => {
      newAxis = newAxis.trim(); if (!newAxis || axes.includes(newAxis) || axes.length >= 4) return;
      axes.push(newAxis); rows.forEach((row) => { row.attributes[newAxis] = 'غير محدد'; if (row.id) row.active = false; }); render();
    })); content.append(attrs);
    const entry = el('div'); entry.className = 'inv-option-fields'; const values = {};
    axes.forEach((axis) => { const f = field('قيمة ' + axis, '', (value) => { values[axis] = value.trim(); }); f.input.maxLength = 32; entry.append(f.wrapper); });
    entry.append(button('إضافة خيار', () => {
      if (axes.some((axis) => !values[axis])) { error.textContent = 'أدخل قيمة لكل صفة.'; return; }
      const name = axes.length === 1 && axes[0] === 'اللون' ? values['اللون'] : axes.map((axis) => `${axis}: ${values[axis]}`).join(' / ');
      if (name.length > 80 || rows.length >= 40 || rows.some((row) => row.name.toLocaleLowerCase() === name.toLocaleLowerCase())) { error.textContent = 'الخيار مكرر أو اسمه طويل أو وصل العدد إلى 40.'; return; }
      rows.push({ name, attributes: { ...values }, qty: !rows.length ? (editing ? originalStock : Number(form.querySelector('[name="opening_stock"]')?.value || 0)) : 0, active: true, buy_price: null, sale_price: null }); error.textContent = ''; render();
    })); content.append(entry);
    rows.forEach((row, index) => {
      const box = el('article'); box.className = 'inv-option-row'; const header = el('header');
      const image = row.preview || row.image_url; if (image && !row.removePhoto) { const img = el('img'); img.src = image; img.alt = row.name; header.append(img); }
      header.append(el('strong', row.name));
      const active = field('عرض الخيار', '', () => {}, 'checkbox'); active.input.checked = row.active; active.input.addEventListener('change', () => { row.active = active.input.checked; }); header.append(active.wrapper, help('إيقاف العرض يمنع اختياره بالمعاملات الجديدة، ويحافظ على الفواتير والمرتجعات القديمة.'));
      if (!row.id) header.append(button('إزالة', () => { if (row.preview) URL.revokeObjectURL(row.preview); rows.splice(index, 1); render(); }));
      const photo = field('صورة ' + row.name, '', () => {}, 'file'); photo.input.accept = 'image/png,image/jpeg,image/webp,image/gif';
      photo.input.addEventListener('change', () => { const file = photo.input.files[0]; if (!file) return; if (file.size > 8 * 1024 * 1024) { error.textContent = 'الصورة لا تتجاوز 8 ميغابايت.'; return; } if (row.preview) URL.revokeObjectURL(row.preview); row.file = file; row.preview = URL.createObjectURL(file); row.removePhoto = false; render(); });
      header.append(photo.wrapper, help('الصورة اختيارية. بدون صورة خاصة يستخدم صورة المنتج الأساسية في المتجر والسلة.'));
      if (image) header.append(button('إزالة الصورة', () => { row.file = null; row.removePhoto = true; if (row.preview) URL.revokeObjectURL(row.preview); row.preview = ''; render(); }));
      box.append(header); const fields = el('div'); fields.className = 'inv-option-fields';
      [['buy_price', 'سعر الشراء'], ['sale_price', 'سعر البيع'], ['governorate_sale_price', 'سعر المحافظات']].forEach(([key, label]) => {
        const f = field(label + ' ' + row.name, row[key], (value) => { row[key] = value === '' ? null : Number(value); }, 'number'); f.input.placeholder = 'سعر المنتج الأساسي'; fields.append(f.wrapper);
      });
      const qty = field('مخزون ' + row.name, row.qty, (value) => { row.qty = Number(value); }, 'number'); qty.input.disabled = !!row.id || (editing && original.length > 0 && !row.source_id); fields.append(qty.wrapper);
      if (!row.id && original.length > 0) {
        const label = el('label', 'توزيع من مخزون موجود'); const select = el('select'); select.setAttribute('aria-label', 'مصدر مخزون ' + row.name); const empty = el('option', 'يبدأ بصفر — أضف الكمية بالمشتريات'); empty.value = ''; select.append(empty);
        original.filter((source) => source.id && source.qty > 0).forEach((source) => { const option = el('option', `${source.name} — ${source.qty} قطعة`); option.value = String(source.id); select.append(option); }); select.value = String(row.source_id || ''); select.addEventListener('change', () => { row.source_id = select.value ? Number(select.value) : undefined; row.qty = 0; render(); }); label.append(select); fields.append(label);
      }
      fields.append(help('السعر الفارغ يستخدم سعر المنتج. مخزون الخيار المحفوظ يتغير بالمشتريات وتعديل المخزون. توزيع رصيد قديم لا يزيد المخزون الإجمالي.')); box.append(fields); content.append(box);
    });
  }
  enabled.addEventListener('change', render); render();
  form.addEventListener('submit', (event) => {
    if (!enabled.checked) return;
    if (!rows.length) { event.preventDefault(); error.textContent = 'أضف خياراً واحداً على الأقل أو أوقف الميزة.'; return; }
    payload.value = JSON.stringify({ axes, rows: rows.map(({ file, preview, removePhoto, ...row }) => row), expected_stock: originalStock });
    payload.disabled = false;
    if (!editing) {
      form.querySelectorAll('[name="color_name[]"], [name="color_qty[]"], [name="color_buy_price[]"], [name="color_sale_price[]"]').forEach((input) => { input.disabled = true; });
      const toggle = document.getElementById('hasColorsCheck'); if (toggle) toggle.checked = true;
      rows.forEach((row) => [['color_name[]', row.name], ['color_qty[]', row.qty]].forEach(([name, value]) => { const input = el('input'); input.type = 'hidden'; input.name = name; input.value = String(value); form.append(input); }));
    }
  });
  form.addEventListener('formdata', (event) => {
    if (!enabled.checked) return;
    const actions = [];
    rows.forEach((row, index) => { if (row.file) { const fieldName = `color_image_${index}`; event.formData.append(fieldName, row.file); actions.push({ name: row.name, field: fieldName }); } else if (row.removePhoto) actions.push({ name: row.name, remove: true }); });
    if (actions.length) event.formData.set('color_images', JSON.stringify(actions));
  });
})();
