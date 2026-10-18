/* Finora Clinics — A4 medical prescription print template */
(() => {
  const FALLBACK_LOGO = "/static/finora-logo.svg";
  const MIN_MED_ROWS = 6;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function dash(value, esc) {
    const text = String(value ?? "").trim();
    return text ? esc(text) : "—";
  }

  function hasArabic(text) {
    return /[\u0600-\u06FF]/.test(String(text || ""));
  }

  function clinicNames(clinicName) {
    const name = String(clinicName || "").trim() || "Finora Clinics";
    if (hasArabic(name)) {
      return { primary: name, secondary: /فينورا|finora/i.test(name) ? "Finora Clinics" : "" };
    }
    const arabic = /finora/i.test(name) ? "عيادات فينورا الطبية" : "";
    return { primary: name, secondary: arabic };
  }

  function pad(num, size) {
    return String(num ?? "").padStart(size, "0");
  }

  function formatDate(iso) {
    if (!iso) return "—";
    const match = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) return `${match[1]}/${match[2]}/${match[3]}`;
    try {
      const d = new Date(iso);
      if (!Number.isNaN(d.getTime())) {
        return `${d.getFullYear()}/${pad(d.getMonth() + 1, 2)}/${pad(d.getDate(), 2)}`;
      }
    } catch {
      /* fall through */
    }
    return String(iso);
  }

  function prescriptionNumber(visitId, visitDate) {
    const day = String(visitDate || "").replace(/-/g, "").slice(0, 8) || new Date().toISOString().slice(0, 10).replace(/-/g, "");
    return `PR-${day}-${pad(visitId || 1, 3)}`;
  }

  const ICONS = {
    phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.6 10.8a15 15 0 006.6 6.6l2.2-2.2a1 1 0 011-.24 11 11 0 003.5.56 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1 11 11 0 00.56 3.5 1 1 0 01-.24 1z"/></svg>',
    mail: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 6h16a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V8a2 2 0 012-2zm0 2v.2l8 5 8-5V8H4z"/></svg>',
    pin: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a7 7 0 017 7c0 5.25-7 13-7 13S5 14.25 5 9a7 7 0 017-7zm0 9.5A2.5 2.5 0 1012 6a2.5 2.5 0 000 5.5z"/></svg>',
    web: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 100 20 10 10 0 000-20zm7.4 9h-3.2a15 15 0 00-1.4-6 8 8 0 014.6 6zM12 4c.8 1.3 1.5 3.1 1.9 5H10c.4-1.9 1.1-3.7 2-5zm-4.8 7H4.6a8 8 0 014.6-6 15 15 0 00-1.4 6zm0 2c.3 2 .9 3.8 1.4 6a8 8 0 01-4.6-6h3.2zm2.8 0h3.8c-.4 1.9-1.1 3.7-1.9 5-.8-1.3-1.5-3.1-1.9-5zm5.8 0h3.2a8 8 0 01-4.6 6c.5-1.8 1.1-3.7 1.4-6z"/></svg>',
    pulse: '<svg viewBox="0 0 48 18" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" d="M1 10h8l4-7 5 14 4-7h21"/></svg>',
    pill: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M15.5 3.5a5 5 0 017 7l-9 9a5 5 0 01-7-7zm-1.4 1.4l-9 9a3 3 0 104.2 4.2l9-9a3 3 0 10-4.2-4.2z"/></svg>',
    file: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zm0 2.5L18.5 9H14z"/></svg>',
    cal: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 2h2v2h6V2h2v2h3a2 2 0 012 2v14a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2h3zm13 8H4v10h16z"/></svg>',
    clip: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 4h10a2 2 0 012 2v15l-4.5-2-4.5 2V6H8a1 1 0 100 2h1v2H8a3 3 0 010-6z"/></svg>',
    steth: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M5 3h3v7a3 3 0 106 0V3h3v7a6 6 0 01-5 5.9V18a4 4 0 108 0v-1.1A3.5 3.5 0 1118 20.4V18a6 6 0 01-7-5.9A6 6 0 015 10z"/></svg>',
    pen: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 17.2V21h3.8l11-11.1-3.8-3.8zm14.7-8.9l2.1-2.1a1 1 0 000-1.4l-2.5-2.5a1 1 0 00-1.4 0l-2.1 2.1z"/></svg>',
    heart: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 21s-7-4.4-9.5-8.6C.4 9.1 2.2 5 6.2 5c2.2 0 3.6 1.3 4.8 3 1.2-1.7 2.6-3 4.8-3 4 0 5.8 4.1 3.7 7.4C19 16.6 12 21 12 21z"/></svg>',
  };

  function contactRow(icon, value, dir) {
    if (!String(value || "").trim()) return "";
    return `<li${dir ? ` dir="${dir}"` : ""}><span class="rx-badge">${ICONS[icon]}</span><span>${value}</span></li>`;
  }

  const DEFAULT_INSTRUCTIONS = [
    "التزم بالجرعات والمواعيد المحددة من الطبيب المعالج.",
    "أكمل مدة العلاج كاملة حتى لو تحسنت الأعراض.",
    "لا توقف الدواء أو تغيّر الجرعة دون استشارة طبية.",
    "احفظ الأدوية بعيداً عن متناول الأطفال وفي مكان بارد وجاف.",
  ];

  function sheetStyles() {
    return `
      @page { size: A4 portrait; margin: 7mm; }
      * { box-sizing: border-box; }
      html, body { margin: 0; padding: 0; background: #dce6ee; }
      body {
        font-family: "IBM Plex Sans Arabic", "Noto Naskh Arabic", Tahoma, Arial, sans-serif;
        color: #07233f;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
      .rx-sheet {
        width: 210mm;
        min-height: 297mm;
        margin: 0 auto;
        background:
          linear-gradient(#2bb8ae, #2bb8ae) top/100% 5px no-repeat,
          linear-gradient(#083154, #083154) top/100% 9px no-repeat,
          #fff;
        padding: 14px 13mm 0;
        position: relative;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }
      .rx-mark {
        position: absolute; inset: auto 18mm 92px auto; width: 168px; height: 168px;
        opacity: .045; pointer-events: none; font-family: Georgia, "Times New Roman", serif;
        font-size: 140px; font-weight: 700; color: #083154; line-height: 1;
        transform: rotate(-12deg);
      }
      .rx-head {
        display: grid;
        grid-template-columns: 1.08fr .62fr 1.18fr;
        gap: 12px;
        align-items: start;
        padding: 8px 0 14px;
        border-bottom: 1px solid #cfe4ee;
        position: relative;
      }
      .rx-head:after {
        content: ""; position: absolute; right: 0; bottom: -3px; width: 86px; height: 3px;
        background: #2bb8ae; border-radius: 99px;
      }
      .rx-brand { display: flex; flex-direction: column; gap: 10px; }
      .rx-brand-row { display: flex; align-items: center; gap: 11px; direction: ltr; }
      .rx-brand-row > div { direction: rtl; text-align: right; min-width: 0; }
      .rx-logo {
        width: 58px; height: 58px; object-fit: contain; flex-shrink: 0;
        border-radius: 14px; background: #fff; padding: 4px;
        border: 1px solid #d7e8f1; box-shadow: 0 6px 16px rgba(8,49,84,.08);
      }
      .rx-clinic-name {
        margin: 0; font-size: 21px; font-weight: 800; color: #083154; line-height: 1.12;
        font-family: Outfit, "IBM Plex Sans Arabic", sans-serif; letter-spacing: .01em;
      }
      .rx-clinic-ar { margin: 3px 0 0; font-size: 13px; font-weight: 700; color: #0f766e; }
      .rx-slogan { margin: 4px 0 0; font-size: 10px; color: #6b8396; letter-spacing: .03em; }
      .rx-contacts { list-style: none; margin: 2px 0 0; padding: 0; display: grid; gap: 5px; }
      .rx-contacts li {
        display: flex; align-items: center; gap: 8px; font-size: 11px; color: #1d3d5c; font-weight: 600;
      }
      .rx-badge {
        width: 18px; height: 18px; border-radius: 50%; flex-shrink: 0;
        display: grid; place-items: center; background: #e7f7f5; color: #0b5c6b;
      }
      .rx-badge svg { width: 11px; height: 11px; display: block; }
      .rx-ico { width: 14px; height: 14px; color: #083154; display: inline-flex; flex-shrink: 0; }
      .rx-ico svg { width: 14px; height: 14px; display: block; }
      .rx-qr { text-align: center; padding-top: 6px; }
      .rx-qr img, .rx-qr-ph {
        width: 92px; height: 92px; object-fit: contain; background: #fff;
        border: 1px solid #d4e4ee; border-radius: 12px; padding: 6px;
        box-shadow: 0 8px 18px rgba(8,49,84,.06);
        margin: 0 auto; display: block;
      }
      .rx-qr-ph { border-style: dashed; background: repeating-conic-gradient(#eef3f7 0 25%, #fff 0 50%) 0 0/10px 10px; }
      .rx-qr p { margin: 7px 0 0; font-size: 10px; color: #5b7388; font-weight: 700; line-height: 1.4; }
      .rx-meta { text-align: right; direction: rtl; }
      .rx-meta-tag {
        display: flex; align-items: center; justify-content: flex-start; gap: 8px;
        color: #0f766e; font-size: 11px; font-weight: 800; margin-bottom: 10px;
      }
      .rx-meta-tag .rx-ico { color: #2bb8ae; width: 42px; height: 16px; }
      .rx-meta-tag .rx-ico svg { width: 42px; height: 16px; }
      .rx-title {
        display: flex; align-items: center; justify-content: flex-start; gap: 10px;
        background: linear-gradient(180deg, #f4fafd, #e7f3fb);
        border: 1px solid #d3e7f3; border-radius: 14px; padding: 10px 12px;
        font-weight: 800; color: #083154; font-size: 16px;
      }
      .rx-title small { display: block; font-size: 10px; font-weight: 600; color: #6b8396; margin-top: 1px; }
      .rx-title-ico {
        width: 32px; height: 32px; border-radius: 10px; background: #083154; color: #fff;
        display: grid; place-items: center; flex-shrink: 0;
      }
      .rx-title-ico svg { width: 16px; height: 16px; }
      .rx-ids { margin-top: 10px; display: grid; gap: 6px; justify-items: start; }
      .rx-ids div {
        display: inline-flex; align-items: center; gap: 7px; font-size: 11.5px; color: #3b556c;
        background: #f5fafc; border: 1px solid #e1eef5; border-radius: 999px; padding: 4px 10px;
      }
      .rx-ids b { color: #083154; font-family: Outfit, "IBM Plex Sans Arabic", sans-serif; }
      .rx-ids .rx-ico { color: #0f766e; }
      .rx-body { flex: 1; display: flex; flex-direction: column; min-height: 0; }
      .rx-meds { margin: 16px 0 0; flex: 1; }
      .rx-meds h2, .rx-box h3, .rx-sign h3 {
        margin: 0 0 10px; font-size: 14px; display: flex; align-items: center; gap: 8px; color: #083154;
      }
      .rx-meds h2 small, .rx-box h3 small { color: #7b91a3; font-weight: 600; font-size: 11px; }
      .rx-sec-ico {
        width: 22px; height: 22px; border-radius: 7px; background: #e7f7f5; color: #0f766e;
        display: grid; place-items: center;
      }
      .rx-sec-ico svg { width: 12px; height: 12px; display: block; }
      .rx-table-wrap {
        border: 1px solid #c9dce8; border-radius: 12px; overflow: hidden;
        box-shadow: 0 8px 20px rgba(8,49,84,.04);
      }
      .rx-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
      .rx-table th, .rx-table td {
        padding: 9px 8px; text-align: center; font-size: 12px; vertical-align: middle;
      }
      .rx-table th {
        background: #083154; color: #fff; font-weight: 700; font-size: 11px; line-height: 1.3;
      }
      .rx-table th small { display: block; font-weight: 500; opacity: .72; font-size: 9px; }
      .rx-table td { border-bottom: 1px solid #e6eef4; color: #12324c; height: 34px; }
      .rx-table tbody tr:nth-child(even) td { background: #f4f9fc; }
      .rx-table tbody tr:last-child td { border-bottom: 0; }
      .rx-table td.rx-name { text-align: right; font-weight: 700; padding-right: 12px; }
      .rx-num {
        display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%;
        background: #e7f7f5; color: #0f766e; font-size: 11px; font-weight: 800;
      }
      .rx-notes-row {
        display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 0 0;
      }
      .rx-box {
        border: 1px solid #d3e4ef; border-radius: 14px; padding: 12px 14px; background: #fff;
        min-height: 118px; position: relative;
      }
      .rx-box--tint { background: #f3f9fd; }
      .rx-box--accent { border-right: 4px solid #2bb8ae; }
      .rx-box ul { margin: 0; padding: 0 18px 0 0; }
      .rx-box li { font-size: 11.5px; line-height: 1.65; color: #1e3f5a; margin-bottom: 4px; }
      .rx-box p { margin: 0; font-size: 12.5px; line-height: 1.75; color: #1e3f5a; min-height: 58px; }
      .rx-sign-row {
        display: flex; justify-content: space-between; align-items: flex-end; gap: 20px;
        margin: 22px 0 8px;
      }
      .rx-together {
        display: flex; align-items: center; gap: 9px; color: #0f766e; font-size: 12.5px; font-weight: 800;
      }
      .rx-heart {
        width: 28px; height: 28px; border-radius: 50%; background: #fff1f3; color: #e11d48;
        display: grid; place-items: center;
      }
      .rx-heart svg { width: 14px; height: 14px; display: block; }
      .rx-together small { display: block; font-weight: 600; color: #7b91a3; font-size: 10px; margin-top: 2px; }
      .rx-sign { text-align: center; min-width: 210px; }
      .rx-sign h3 { justify-content: center; margin-bottom: 4px; font-size: 12.5px; }
      .rx-sign-line {
        height: 46px; border-bottom: 1.6px solid #8aa6bb; margin: 0 auto 8px; width: 170px;
      }
      .rx-sign strong { display: block; font-size: 13px; color: #083154; }
      .rx-sign span { display: block; font-size: 10.5px; color: #6b8396; margin-top: 2px; }
      .rx-foot {
        position: relative; margin-top: auto; min-height: 62px;
        display: flex; align-items: flex-end; justify-content: flex-start;
        padding: 18px 2px 10px;
      }
      .rx-wave { position: absolute; inset: auto -13mm -1px -13mm; height: 68px; width: calc(100% + 26mm); display: block; }
      .rx-foot-brand {
        position: relative; display: flex; align-items: center; gap: 8px;
        color: #fff; font-weight: 800; font-size: 12.5px; z-index: 1;
        padding: 0 10px 4px;
        font-family: Outfit, "IBM Plex Sans Arabic", sans-serif;
      }
      .rx-foot-brand img {
        width: 30px; height: 30px; border-radius: 9px; background: #fff; padding: 3px;
        box-shadow: 0 4px 10px rgba(0,0,0,.12);
      }
      .rx-printbar { display: none; }
      @media screen {
        body { padding: 18px 0 32px; }
        .rx-sheet { box-shadow: 0 22px 60px rgba(8, 40, 70, .18); }
        .rx-printbar {
          display: flex; justify-content: center; gap: 8px; margin: 0 0 14px;
        }
        .rx-printbar button {
          appearance: none; border: 0; border-radius: 11px; padding: 10px 18px;
          background: #083154; color: #fff; font-weight: 700; cursor: pointer;
          font-family: inherit; box-shadow: 0 8px 18px rgba(8,49,84,.22);
        }
      }
      @media print {
        html, body { background: #fff !important; }
        .rx-sheet { box-shadow: none; width: auto; min-height: 277mm; padding: 8px 2mm 0; }
        .rx-printbar { display: none !important; }
        .rx-wave { inset: auto -8mm -2px -8mm; width: calc(100% + 16mm); }
      }
    `;
  }

  function logoMarkup(logoUrl, clinicName, esc) {
    const src = String(logoUrl || "").trim() || FALLBACK_LOGO;
    return `<img class="rx-logo" src="${esc(src)}" alt="${esc(clinicName)}" onerror="this.onerror=null;this.src='${FALLBACK_LOGO}'">`;
  }

  function medicineRows(items, esc) {
    const filled = (Array.isArray(items) ? items : []).map((item, index) => `
      <tr>
        <td><span class="rx-num">${index + 1}</span></td>
        <td class="rx-name">${dash(item.medicine_name, esc)}</td>
        <td>${dash(item.dosage, esc)}</td>
        <td>${dash(item.frequency, esc)}</td>
        <td>${dash(item.duration, esc)}</td>
        <td>${dash(item.instructions, esc)}</td>
      </tr>`);
    const start = filled.length;
    const blanks = Math.max(0, MIN_MED_ROWS - start);
    for (let i = 0; i < blanks; i += 1) {
      filled.push(`
      <tr>
        <td><span class="rx-num">${start + i + 1}</span></td>
        <td class="rx-name"></td><td></td><td></td><td></td><td></td>
      </tr>`);
    }
    return filled.join("");
  }

  function buildHtml(payload, escFn) {
    const esc = typeof escFn === "function" ? escFn : escapeHtml;
    const clinicName = payload.clinicName || "Finora Clinics";
    const names = clinicNames(clinicName);
    const logo = logoMarkup(payload.logoUrl, names.primary, esc);
    const phone = payload.phone || "";
    const email = payload.email || "";
    const location = payload.location || "";
    const website = payload.website || "";
    const qrSrc = payload.qrImage || "";
    const rxNo = payload.prescriptionNumber || prescriptionNumber(payload.visitId, payload.visitDate);
    const visitDate = formatDate(payload.visitDate);
    const notes = String(payload.notes || "").trim();
    const doctorNotes = String(payload.doctorNotes || notes || "").trim();
    const extra = Array.isArray(payload.instructions) && payload.instructions.length
      ? payload.instructions
      : DEFAULT_INSTRUCTIONS;
    const doctorName = payload.doctorName || "—";
    const doctorTitle = payload.doctorTitle || payload.doctorSpecialty || "طبيب";
    const doctorLicense = payload.doctorLicense || "";

    return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <title>${esc(`وصفة طبية — ${payload.patientName || clinicName}`)}</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600;700;800&family=Outfit:wght@600;700;800&display=swap">
  <style>${sheetStyles()}</style>
</head>
<body>
  <div class="rx-printbar"><button type="button" onclick="window.print()">طباعة</button></div>
  <article class="rx-sheet">
    <div class="rx-mark" aria-hidden="true">Rx</div>
    <header class="rx-head">
      <div class="rx-meta">
        <div class="rx-meta-tag">
          <span>رعايتكم … أولويتنا / Your Health … Our Priority</span>
          <span class="rx-ico">${ICONS.pulse}</span>
        </div>
        <div class="rx-title">
          <span>وصفة طبية<small>Medical Prescription</small></span>
          <span class="rx-title-ico">${ICONS.pill}</span>
        </div>
        <div class="rx-ids">
          <div><span class="rx-ico">${ICONS.file}</span> رقم الوصفة: <b>${esc(rxNo)}</b></div>
          <div><span class="rx-ico">${ICONS.cal}</span> التاريخ: <b>${esc(visitDate)}</b></div>
        </div>
      </div>
      <div class="rx-qr">
        ${qrSrc ? `<img src="${esc(qrSrc)}" alt="QR">` : `<div class="rx-qr-ph" aria-hidden="true"></div>`}
        <p>للمزيد من المعلومات<br>امسح رمز QR</p>
      </div>
      <div class="rx-brand">
        <div class="rx-brand-row">
          ${logo}
          <div>
            <h1 class="rx-clinic-name">${esc(names.primary)}</h1>
            ${names.secondary ? `<p class="rx-clinic-ar">${esc(names.secondary)}</p>` : ""}
            <p class="rx-slogan">Better Care — Healthier Tomorrow</p>
          </div>
        </div>
        <ul class="rx-contacts">
          ${contactRow("phone", esc(phone), "ltr")}
          ${contactRow("mail", esc(email), "ltr")}
          ${contactRow("pin", esc(location))}
          ${contactRow("web", esc(website), "ltr")}
        </ul>
      </div>
    </header>

    <div class="rx-body">
      <section class="rx-meds">
        <h2><span class="rx-sec-ico">${ICONS.pill}</span> الأدوية الموصوفة <small>Prescribed Medications</small></h2>
        <div class="rx-table-wrap">
          <table class="rx-table">
            <thead>
              <tr>
                <th style="width:7%">#</th>
                <th>اسم الدواء <small>Medication</small></th>
                <th style="width:14%">الجرعة <small>Dose</small></th>
                <th style="width:16%">التكرار <small>Frequency</small></th>
                <th style="width:13%">المدة <small>Duration</small></th>
                <th style="width:16%">ملاحظات <small>Notes</small></th>
              </tr>
            </thead>
            <tbody>${medicineRows(payload.items, esc)}</tbody>
          </table>
        </div>
      </section>

      <section class="rx-notes-row">
        <div class="rx-box rx-box--accent">
          <h3><span class="rx-sec-ico">${ICONS.clip}</span> تعليمات إضافية <small>Additional Instructions</small></h3>
          <ul>${extra.map((line) => `<li>${esc(line)}</li>`).join("")}</ul>
        </div>
        <div class="rx-box rx-box--tint">
          <h3><span class="rx-sec-ico">${ICONS.steth}</span> ملاحظات الطبيب <small>Physician Notes</small></h3>
          <p>${doctorNotes ? esc(doctorNotes) : ""}</p>
        </div>
      </section>

      <section class="rx-sign-row">
        <div class="rx-sign">
          <h3><span class="rx-sec-ico">${ICONS.pen}</span> توقيع الطبيب</h3>
          <div class="rx-sign-line"></div>
          <strong>${esc(doctorName)}</strong>
          <span>${esc(doctorTitle)}${doctorLicense ? ` · رخصة ${esc(doctorLicense)}` : ""}</span>
        </div>
        <div class="rx-together">
          <span class="rx-heart">${ICONS.heart}</span>
          <div>معاً نحو مجتمع أكثر صحة<small>Together for a Healthier Community</small></div>
        </div>
      </section>
    </div>

    <footer class="rx-foot">
      <svg class="rx-wave" viewBox="0 0 800 90" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 90h800V38c-90 28-170 8-250-6-110-18-170 18-270 8C170 30 90 58 0 42z" fill="#7ee0d6"/>
        <path d="M0 90h800V52c-120 26-210-4-320-8-130-6-190 22-300 10C90 46 40 62 0 58z" fill="#2bb8ae"/>
        <path d="M0 90h800V68c-140 18-240-6-360-4-140 2-200 16-300 4C70 62 30 74 0 72z" fill="#1aa39a"/>
      </svg>
      <div class="rx-foot-brand">${logo}<span>${esc(names.primary)}</span></div>
    </footer>
  </article>
</body>
</html>`;
  }

  function printWhenReady(win) {
    const images = [...(win.document.images || [])];
    const pending = images.map((img) => {
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {
        img.onload = resolve;
        img.onerror = resolve;
      });
    });
    Promise.all(pending).then(() => {
      setTimeout(() => {
        try {
          win.focus();
          win.print();
        } catch {
          /* ignore */
        }
      }, 280);
    });
  }

  function printSheet(payload, escFn) {
    const html = buildHtml(payload, escFn);
    const win = window.open("", "_blank", "width=920,height=1200");
    if (!win) return false;
    win.document.write(html);
    win.document.close();
    printWhenReady(win);
    return true;
  }

  window.ClinicsPrintPrescription = {
    buildHtml,
    print: printSheet,
    FALLBACK_LOGO,
  };
})();
