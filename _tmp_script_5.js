
    window.FinoraTopbar = {
      run(action) {
        if (action === "search" && typeof openSearch === "function") { openSearch(); return; }
        if (action === "profit" && typeof openProfit === "function") { openProfit(); return; }
        if (action === "expense" && typeof openAddExpense === "function") { openAddExpense(); return; }
        window.location.href = "/?quick=" + encodeURIComponent(action);
      },
    };
  