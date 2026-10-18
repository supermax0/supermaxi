/**
 * Finora Clinics — Public TV Display (presentation only)
 * No admin controls. Settings live in /clinics/settings.
 */
(() => {
  const POLL_MS = 3000;

  function ticketCode(t) {
    if (!t) return "";
    if (t.ticket_code) return t.ticket_code;
    if (t.queue_number != null && t.queue_number !== "") {
      return `A-${String(t.queue_number).padStart(3, "0")}`;
    }
    return "";
  }

  function fmtClock() {
    try {
      return new Date().toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function fmtDate(iso) {
    try {
      const d = iso ? new Date(`${String(iso).slice(0, 10)}T12:00:00`) : new Date();
      return d.toLocaleDateString("ar-IQ", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return iso || "";
    }
  }

  function displaySettings(data) {
    const s = data?.display_settings || {};
    return {
      sound: s.sound_enabled !== false,
      voice: !!s.voice_enabled,
      volume: Math.max(0, Math.min(100, Number(s.volume) || 70)),
      showShortName: !!s.show_short_name,
    };
  }

  function playChime(volume) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(523.25, ctx.currentTime + 0.45);
      gain.gain.value = Math.max(0, Math.min(1, (volume || 70) / 100)) * 0.2;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.5);
      setTimeout(() => ctx.close().catch(() => null), 700);
    } catch {
      /* ignore */
    }
  }

  function speakCall(text, volume) {
    try {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ar-SA";
      u.rate = 0.92;
      u.volume = Math.max(0, Math.min(1, (volume || 70) / 100));
      window.speechSynthesis.speak(u);
    } catch {
      /* ignore */
    }
  }

  function maybeAnnounce(ctx, data) {
    const call = data.last_call;
    if (!call?.call_id) return;
    if (String(call.call_id) === String(ctx.state.lastAnnounced)) return;
    ctx.state.lastAnnounced = call.call_id;
    const settings = displaySettings(data);
    if (settings.sound) playChime(settings.volume);
    if (settings.voice) {
      const num = call.queue_number || ticketCode(call).replace(/\D/g, "");
      const room = call.room_name ? `غرفة ${call.room_name}` : "";
      const doc = call.doctor_name ? `الدكتور ${call.doctor_name}` : "";
      speakCall(`الدور رقم ${num}، يرجى التوجه إلى ${room || doc || "العيادة"}`, settings.volume);
    }
    ctx.state.pulseCall = true;
    clearTimeout(ctx.state.pulseTimer);
    ctx.state.pulseTimer = setTimeout(() => {
      ctx.state.pulseCall = false;
      ctx.root.querySelectorAll(".is-calling").forEach((el) => el.classList.remove("is-calling"));
    }, 4200);
  }

  function useMultiLayout(data) {
    const active = (data.by_doctor || []).filter((d) => d.current || (d.waiting_count || 0) > 0);
    return active.length > 1;
  }

  function emptyNowHtml() {
    return `
      <section class="cx-tv-now cx-tv-now--empty" aria-live="polite">
        <div class="cx-tv-empty">
          <div class="cx-tv-empty__mark"><i class="fa fa-stethoscope"></i></div>
          <h2>بانتظار النداء التالي</h2>
          <p>يرجى متابعة الشاشة — سيتم عرض رقم الدور هنا فور الاستدعاء</p>
        </div>
      </section>`;
  }

  function singleNowHtml(ctx, data) {
    const current = (data.current || [])[0];
    if (!current) return emptyNowHtml();
    const code = ticketCode(current);
    const settings = displaySettings(data);
    const short =
      settings.showShortName && current.short_name ? ctx.esc(current.short_name) : "";
    const room = current.room_name ? ctx.esc(current.room_name) : "";
    const doc = current.doctor_name ? ctx.esc(current.doctor_name) : "";
    return `
      <section class="cx-tv-now ${ctx.state.pulseCall ? "is-calling" : ""}" aria-live="assertive">
        <p class="cx-tv-now__label">الآن يرجى التوجه إلى</p>
        <div class="cx-tv-now__ticket">${ctx.esc(code)}</div>
        ${short ? `<p class="cx-tv-now__short">${short}</p>` : ""}
        <div class="cx-tv-now__meta">
          ${doc ? `<span class="cx-tv-pill"><i class="fa fa-user-doctor"></i>${doc}</span>` : ""}
          ${room ? `<span class="cx-tv-pill"><i class="fa fa-door-open"></i>${room}</span>` : ""}
        </div>
      </section>`;
  }

  function multiNowHtml(ctx, data) {
    const docs = (data.by_doctor || []).filter((d) => d.current || (d.waiting_count || 0) > 0);
    const list = docs.length ? docs : data.by_doctor || [];
    if (!list.length) return emptyNowHtml();
    const anyCurrent = list.some((d) => d.current);
    if (!anyCurrent) return emptyNowHtml();
    return `
      <section class="cx-tv-grid" aria-live="assertive">
        ${list
          .map((d) => {
            const cur = d.current;
            const code = cur ? ticketCode(cur) : "—";
            const room = cur?.room_name ? ctx.esc(cur.room_name) : "";
            const calling =
              ctx.state.pulseCall &&
              data.last_call &&
              cur &&
              String(cur.appointment_id) === String(data.last_call.appointment_id);
            return `
            <article class="cx-tv-doc ${cur ? "has-call" : ""} ${calling ? "is-calling" : ""}" style="--doc-color:${ctx.esc(d.color || "#2dd4bf")}">
              <header class="cx-tv-doc__head">
                <strong>${ctx.esc(d.doctor_name || "")}</strong>
              </header>
              <div class="cx-tv-doc__ticket">${ctx.esc(code)}</div>
              ${room ? `<div class="cx-tv-doc__room">${room}</div>` : cur ? `<div class="cx-tv-doc__room">يُرجى الدخول</div>` : `<div class="cx-tv-doc__room cx-tv-doc__room--idle">بانتظار الدور</div>`}
            </article>`;
          })
          .join("")}
      </section>`;
  }

  function upcomingHtml(ctx, data) {
    const upcoming = (data.upcoming || []).slice(0, 6);
    return `
      <section class="cx-tv-upcoming">
        <h2>الأدوار القادمة</h2>
        <div class="cx-tv-upcoming__row">
          ${
            upcoming.length
              ? upcoming
                  .map(
                    (t) => `
            <div class="cx-tv-chip">
              <strong>${ctx.esc(ticketCode(t))}</strong>
              <span>${ctx.esc(t.doctor_name || "")}</span>
              ${t.room_name ? `<em>${ctx.esc(t.room_name)}</em>` : ""}
            </div>`
                  )
                  .join("")
              : `<div class="cx-tv-upcoming__none">لا أدوار في الانتظار حالياً</div>`
          }
        </div>
      </section>`;
  }

  function buildHtml(ctx) {
    const data = ctx.data || {};
    const multi = useMultiLayout(data);
    return `
      <div class="cx-tv-frame" role="presentation">
        <div class="cx-tv" id="cxTvRoot">
          <header class="cx-tv-header">
            <div class="cx-tv-brand">
              <strong>Finora Clinics</strong>
              <span>${ctx.esc(data.clinic_name || "")}</span>
            </div>
            <div class="cx-tv-clock">
              <b id="cxTvClock">${ctx.esc(fmtClock())}</b>
              <span>${ctx.esc(fmtDate(data.date || ctx.state.day))}</span>
            </div>
          </header>
          <main class="cx-tv-main">
            ${multi ? multiNowHtml(ctx, data) : singleNowHtml(ctx, data)}
            ${upcomingHtml(ctx, data)}
          </main>
          <footer class="cx-tv-footer">
            <p>${ctx.esc(data.footer_message || "يرجى متابعة رقم الدور على الشاشة.")}</p>
          </footer>
        </div>
      </div>`;
  }

  function applyChrome() {
    document.documentElement.classList.add("cx-display-mode");
    document.body.classList.add("cx-display-mode");
    const app = document.querySelector(".cx-app");
    if (app) app.classList.add("cx-app--display");
    const notice = document.getElementById("cxNotice");
    if (notice) notice.hidden = true;
  }

  function paint(ctx) {
    ctx.root.innerHTML = buildHtml(ctx);
  }

  function tickClock() {
    const el = document.getElementById("cxTvClock");
    if (el) el.textContent = fmtClock();
  }

  async function refresh(ctx) {
    const data = await ctx.api(`/clinics/api/public-queue?date=${encodeURIComponent(ctx.state.day)}`);
    const changed = !ctx.state.pulse || (data.pulse_version && data.pulse_version !== ctx.state.pulse);
    const prevPulse = ctx.state.pulse;
    ctx.state.pulse = data.pulse_version || "";
    ctx.data = data;
    if (prevPulse && changed) maybeAnnounce(ctx, data);
    if (changed || !ctx.root.querySelector(".cx-tv")) paint(ctx);
    else if (ctx.state.pulseCall) {
      ctx.root.querySelector(".cx-tv-now")?.classList.add("is-calling");
    }
  }

  async function render(state, root, helpers) {
    clearTimeout(window.__cxDisplayTimer);
    clearInterval(window.__cxTvClock);
    applyChrome();

    const ctx = {
      state: {
        day: state.day,
        pulse: "",
        lastAnnounced: "",
        pulseCall: false,
        pulseTimer: null,
      },
      data: null,
      root,
      api: helpers.api,
      esc: helpers.esc,
    };

    root.innerHTML = `
      <div class="cx-tv-frame">
        <div class="cx-tv"><div class="cx-tv-loading">جاري تجهيز شاشة الانتظار…</div></div>
      </div>`;

    try {
      await refresh(ctx);
    } catch (err) {
      root.innerHTML = `
        <div class="cx-tv-frame">
          <div class="cx-tv"><div class="cx-tv-loading">${helpers.esc(err.message || String(err))}</div></div>
        </div>`;
    }

    window.__cxTvClock = setInterval(tickClock, 1000);

    const poll = async () => {
      try {
        if (!document.body.classList.contains("cx-display-mode")) return;
        await refresh(ctx);
      } catch {
        /* keep polling */
      } finally {
        window.__cxDisplayTimer = setTimeout(poll, POLL_MS);
      }
    };
    window.__cxDisplayTimer = setTimeout(poll, POLL_MS);
  }

  window.ClinicsDisplay = { render };
})();
