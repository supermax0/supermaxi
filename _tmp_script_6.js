
    (function () {
      const sel = document.getElementById("globalBranchSelect");
      if (!sel) return;
      sel.addEventListener("change", async function () {
        const val = sel.value;
        const payload = val === "all" ? { view_all: true } : { branch_id: parseInt(val, 10) };
        const res = await fetch("/api/branch/switch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.ok) location.reload();
        else alert(data.error || "فشل تبديل الفرع");
      });
    })();
  