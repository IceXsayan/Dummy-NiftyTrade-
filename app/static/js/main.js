// NiftyTrade Frontend Script - Theme & Live Market SSE Engine
(function() {
  // 1. Theme Management
  const themeToggleBtn = document.getElementById("themeToggle");
  const storedTheme = localStorage.getItem("niftytrade_theme") || "dark";
  document.documentElement.setAttribute("data-theme", storedTheme);

  if (themeToggleBtn) {
    updateThemeIcon(storedTheme);
    themeToggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const nextTheme = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", nextTheme);
      localStorage.setItem("niftytrade_theme", nextTheme);
      updateThemeIcon(nextTheme);
    });
  }

  function updateThemeIcon(theme) {
    if (!themeToggleBtn) return;
    themeToggleBtn.innerHTML = theme === "dark" ? "☀️" : "🌙";
    themeToggleBtn.setAttribute("title", `Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`);
  }

  // 2. Live Market Prices Engine (SSE + Polling fallback)
  let sseSource = null;
  let pollingInterval = null;
  const previousPrices = {};

  function initLiveStream() {
    if (sseSource && sseSource.readyState !== EventSource.CLOSED) {
      return;
    }

    if (window.EventSource) {
      try {
        sseSource = new EventSource("/api/live-quotes");
        sseSource.onmessage = function(event) {
          try {
            const data = JSON.parse(event.data);
            handleMarketTick(data);
          } catch (e) {
            console.error("SSE parse error", e);
          }
        };
        sseSource.onerror = function() {
          console.warn("SSE disconnected, falling back to polling");
          try { sseSource.close(); } catch (e) {}
          sseSource = null;
          startPolling();
        };
      } catch (e) {
        startPolling();
      }
    } else {
      startPolling();
    }
  }

  // Ensure SSE connection is cleanly closed when leaving the page to avoid socket pool exhaustion
  window.closeLiveStream = function() {
    if (sseSource) {
      try { sseSource.close(); } catch (e) {}
      sseSource = null;
    }
    if (pollingInterval) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
  };

  window.addEventListener("beforeunload", window.closeLiveStream);
  window.addEventListener("pagehide", window.closeLiveStream);

  function startPolling() {
    if (pollingInterval) return;
    pollingInterval = setInterval(async () => {
      try {
        const res = await fetch("/api/quotes-poll");
        if (res.ok) {
          const data = await res.json();
          handleMarketTick(data);
        }
      } catch (err) {
        console.warn("Polling error", err);
      }
    }, 5000);
  }

  function handleMarketTick(data) {
    // 1. Update Market Indices
    if (data.indices) {
      for (const [idxName, idxInfo] of Object.entries(data.indices)) {
        const valElem = document.querySelector(`[data-index-val="${idxName}"]`);
        const chgElem = document.querySelector(`[data-index-chg="${idxName}"]`);
        if (valElem) {
          valElem.textContent = Number(idxInfo.current).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (chgElem) {
          const isUp = idxInfo.change >= 0;
          chgElem.className = `index-change ${isUp ? 'text-up bg-up' : 'text-down bg-down'}`;
          chgElem.textContent = `${isUp ? '+' : ''}${idxInfo.change.toFixed(2)} (${isUp ? '+' : ''}${idxInfo.change_pct.toFixed(2)}%)`;
        }
      }
    }

    // 2. Update Stock Ticks
    if (data.ticks && Array.isArray(data.ticks)) {
      data.ticks.forEach(tick => {
        const symbol = tick.symbol;
        const prev = previousPrices[symbol];
        const current = tick.price;

        // Elements matching this symbol
        const priceElems = document.querySelectorAll(`[data-symbol-price="${symbol}"]`);
        const chgElems = document.querySelectorAll(`[data-symbol-chg="${symbol}"]`);
        const chgPctElems = document.querySelectorAll(`[data-symbol-chg-pct="${symbol}"]`);
        const highElems = document.querySelectorAll(`[data-symbol-high="${symbol}"]`);
        const lowElems = document.querySelectorAll(`[data-symbol-low="${symbol}"]`);
        const volElems = document.querySelectorAll(`[data-symbol-vol="${symbol}"]`);

        priceElems.forEach(el => {
          el.textContent = `₹${current.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
          if (prev !== undefined && prev !== current) {
            el.classList.remove("flash-up", "flash-down");
            void el.offsetWidth; // trigger reflow
            el.classList.add(current > prev ? "flash-up" : "flash-down");
          }
        });

        chgElems.forEach(el => {
          const isUp = tick.change >= 0;
          el.className = isUp ? 'text-up' : 'text-down';
          el.textContent = `${isUp ? '+' : ''}₹${tick.change.toFixed(2)}`;
        });

        chgPctElems.forEach(el => {
          const isUp = tick.change_pct >= 0;
          el.className = isUp ? 'text-up' : 'text-down';
          el.textContent = `${isUp ? '+' : ''}${tick.change_pct.toFixed(2)}%`;
        });

        highElems.forEach(el => {
          if (tick.high) el.textContent = `₹${tick.high.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
        });

        lowElems.forEach(el => {
          if (tick.low) el.textContent = `₹${tick.low.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
        });

        volElems.forEach(el => {
          if (tick.volume) el.textContent = tick.volume.toLocaleString("en-IN");
        });

        previousPrices[symbol] = current;

        // If order modal is open for this symbol and order type is MARKET, update LTP and recalculate live
        if (window.currentOrderContext && window.currentOrderContext.symbol === symbol) {
          window.currentOrderContext.ltp = current;
          const displayPrice = document.getElementById("modalDisplayPrice");
          if (displayPrice) {
            displayPrice.textContent = `₹${current.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
          }
          const orderTypeSelect = document.getElementById("modalOrderTypeSelect");
          if (orderTypeSelect && orderTypeSelect.value === "MARKET") {
            if (typeof calculateOrderEstimatedTotal === "function") {
              calculateOrderEstimatedTotal();
            }
          }
        }
      });
    }
  }

  // Start live tick listener
  window.addEventListener("DOMContentLoaded", () => {
    initLiveStream();
  });
})();

// Toast Notification System
function showToast(message, type = "info", duration = 4500) {
  let container = document.getElementById("toastContainer");
  if (!container) {
    container = document.createElement("div");
    container.id = "toastContainer";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  
  const icon = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";
  toast.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <span style="font-weight: 700; font-size: 1.1rem;">${icon}</span>
      <span>${message}</span>
    </div>
    <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(40px) scale(0.95)";
    setTimeout(() => {
      if (toast.parentElement) toast.remove();
    }, 300);
  }, duration);
}

// Global Modal State & Helpers for Buy/Sell order placement
window.currentOrderContext = {
  symbol: "",
  name: "",
  ltp: 0,
  availableFunds: 0,
  usedMargin: 0,
  holdingQty: 0,
  intradayQty: 0,
  marketOpen: true
};
let currentOrderContext = window.currentOrderContext;

function syncFundsFromDOM() {
  const modal = document.getElementById("orderModal");
  if (modal) {
    const fundsAttr = modal.getAttribute("data-user-funds");
    if (fundsAttr && !isNaN(parseFloat(fundsAttr))) {
      currentOrderContext.availableFunds = parseFloat(fundsAttr);
      const fundsElem = document.getElementById("modalAvailableFunds");
      if (fundsElem) {
        fundsElem.textContent = `₹${formatINR(currentOrderContext.availableFunds)}`;
      }
    }
  }
}

// Initial sync on load
window.addEventListener("DOMContentLoaded", () => {
  syncFundsFromDOM();
});

function formatINR(val) {
  return Number(val || 0).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function showModalAlert(msg) {
  const alertBox = document.getElementById("modalValidationAlert");
  const alertMsg = document.getElementById("modalValidationMessage");
  if (alertBox && alertMsg) {
    alertMsg.textContent = msg;
    alertBox.style.display = "block";
  }
}

function hideModalAlert() {
  const alertBox = document.getElementById("modalValidationAlert");
  if (alertBox) {
    alertBox.style.display = "none";
  }
}

async function openOrderModal(symbol, nameOrAction, currentPrice, defaultAction = "BUY") {
  const modal = document.getElementById("orderModal");
  if (!modal) return;

  hideModalAlert();
  syncFundsFromDOM();

  let initialAction = "BUY";
  let stockName = "";
  let initialPrice = null;

  if (nameOrAction === "BUY" || nameOrAction === "SELL") {
    initialAction = nameOrAction;
  } else {
    stockName = nameOrAction || "";
    initialPrice = typeof currentPrice === "number" ? currentPrice : parseFloat(currentPrice);
    if (defaultAction === "BUY" || defaultAction === "SELL") {
      initialAction = defaultAction;
    }
  }

  const submitBtn = document.getElementById("orderModalSubmitBtn");
  if (submitBtn) {
    submitBtn.disabled = false;
    submitBtn.textContent = initialAction === "BUY" ? "Place BUY Order" : "Place SELL Order";
  }

  currentOrderContext.symbol = symbol.toUpperCase();
  currentOrderContext.name = stockName;
  currentOrderContext.ltp = 0;
  currentOrderContext.holdingQty = 0;

  // If initialPrice was not explicitly provided, try reading it directly from the page DOM
  if (!initialPrice || isNaN(initialPrice) || initialPrice <= 0) {
    const pagePriceElem = document.querySelector(`[data-symbol-price="${currentOrderContext.symbol}"]`);
    if (pagePriceElem) {
      const parsedPagePrice = parseFloat(pagePriceElem.textContent.replace(/[^0-9.]/g, ""));
      if (!isNaN(parsedPagePrice) && parsedPagePrice > 0) {
        initialPrice = parsedPagePrice;
      }
    }
  }

  if (initialPrice && !isNaN(initialPrice)) {
    currentOrderContext.ltp = initialPrice;
  }

  // Reset order inputs to a clean default state
  const orderTypeSelect = document.getElementById("modalOrderTypeSelect");
  const priceContainer = document.getElementById("modalPriceContainer");
  const priceInput = document.getElementById("modalPriceInput");
  const qtyInput = document.getElementById("modalQtyInput");

  if (orderTypeSelect) orderTypeSelect.value = "MARKET";
  if (priceContainer) priceContainer.style.display = "none";
  if (priceInput) {
    priceInput.required = false;
    priceInput.value = currentOrderContext.ltp > 0 ? currentOrderContext.ltp.toFixed(2) : "";
  }
  if (qtyInput && (!qtyInput.value || parseInt(qtyInput.value) <= 0)) {
    qtyInput.value = "1";
  }

  // Populate immediate UI values
  const symbolHidden = document.getElementById("modalSymbol");
  if (symbolHidden) symbolHidden.value = currentOrderContext.symbol;
  document.getElementById("modalDisplaySymbol").textContent = currentOrderContext.symbol;
  document.getElementById("modalDisplayName").textContent = stockName;
  if (currentOrderContext.ltp > 0) {
    document.getElementById("modalDisplayPrice").textContent = `₹${formatINR(currentOrderContext.ltp)}`;
  } else {
    document.getElementById("modalDisplayPrice").textContent = "Loading...";
  }

  setOrderAction(initialAction);
  modal.classList.add("active");

  // Fetch live context from helper endpoint with timeout protection
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    const res = await fetch(`/api/ui/order-context?symbol=${encodeURIComponent(currentOrderContext.symbol)}`, {
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (res.ok) {
      const data = await res.json();
      currentOrderContext.symbol = data.symbol;
      currentOrderContext.name = data.name;
      currentOrderContext.ltp = data.ltp;
      currentOrderContext.availableFunds = data.available_funds;
      currentOrderContext.usedMargin = data.used_margin;
      currentOrderContext.holdingQty = data.holding_qty;
      currentOrderContext.intradayQty = data.intraday_qty;
      currentOrderContext.marketOpen = data.market_open;

      // Update UI displays
      document.getElementById("modalDisplayPrice").textContent = `₹${formatINR(data.ltp)}`;
      document.getElementById("modalDisplayName").textContent = data.name;
      document.getElementById("modalAvailableFunds").textContent = `₹${formatINR(data.available_funds)}`;
      document.getElementById("modalHoldingQty").textContent = `${data.holding_qty} shares`;
      document.getElementById("modalIntradayQty").textContent = `${data.intraday_qty} shares`;

      const badge = document.getElementById("modalMarketBadge");
      if (badge) {
        if (data.market_open) {
          badge.textContent = "MARKET OPEN";
          badge.className = "badge badge-success";
          badge.style.color = "var(--green)";
        } else {
          badge.textContent = "AMO (CLOSED)";
          badge.className = "badge badge-warning";
          badge.style.color = "var(--warning)";
        }
      }

      if (priceInput && (!priceInput.value || parseFloat(priceInput.value) <= 0)) {
        priceInput.value = data.ltp.toFixed(2);
      }
    }
  } catch (err) {
    console.warn("Live order context fetch bypassed:", err);
  }

  calculateOrderEstimatedTotal();
}

function closeOrderModal() {
  const modal = document.getElementById("orderModal");
  if (modal) {
    modal.classList.remove("active");
  }
}

function setOrderAction(action) {
  const sideInput = document.getElementById("modalTransactionType");
  const buyBtn = document.getElementById("orderModalBuyBtn");
  const sellBtn = document.getElementById("orderModalSellBtn");
  const submitBtn = document.getElementById("orderModalSubmitBtn");
  const holdingRow = document.getElementById("modalHoldingRow");

  if (!sideInput || !buyBtn || !sellBtn || !submitBtn) return;

  sideInput.value = action;
  if (action === "BUY") {
    buyBtn.classList.add("btn-buy");
    buyBtn.classList.remove("btn-outline");
    sellBtn.classList.remove("btn-sell");
    sellBtn.classList.add("btn-outline");
    submitBtn.className = "btn btn-buy";
    submitBtn.textContent = "Place BUY Order";
    if (holdingRow) holdingRow.style.display = "none";
  } else {
    sellBtn.classList.add("btn-sell");
    sellBtn.classList.remove("btn-outline");
    buyBtn.classList.remove("btn-buy");
    buyBtn.classList.add("btn-outline");
    submitBtn.className = "btn btn-sell";
    submitBtn.textContent = "Place SELL Order";
    if (holdingRow) holdingRow.style.display = "flex";
  }

  calculateOrderEstimatedTotal();
}

function onOrderTypeChange(type) {
  const priceContainer = document.getElementById("modalPriceContainer");
  const priceInput = document.getElementById("modalPriceInput");
  if (!priceContainer || !priceInput) return;

  if (type === "LIMIT") {
    priceContainer.style.display = "block";
    priceInput.required = true;
    if (!priceInput.value && currentOrderContext.ltp > 0) {
      priceInput.value = currentOrderContext.ltp.toFixed(2);
    }
  } else {
    priceContainer.style.display = "none";
    priceInput.required = false;
  }
  calculateOrderEstimatedTotal();
}

function calculateOrderEstimatedTotal() {
  const qtyInput = document.getElementById("modalQtyInput");
  const priceInput = document.getElementById("modalPriceInput");
  const orderTypeSelect = document.getElementById("modalOrderTypeSelect");
  const productTypeSelect = document.getElementById("modalProductTypeSelect");
  const actionInput = document.getElementById("modalTransactionType");
  const submitBtn = document.getElementById("orderModalSubmitBtn");
  const amountLabel = document.getElementById("modalAmountLabel");
  const estTotalElem = document.getElementById("modalEstimatedTotal");
  const remainingRow = document.getElementById("modalRemainingRow");
  const remainingLabel = document.getElementById("modalRemainingLabel");
  const fundsRemainingElem = document.getElementById("modalFundsRemaining");

  if (!qtyInput || !estTotalElem || !submitBtn) return;

  const action = actionInput ? actionInput.value : "BUY";
  const orderType = orderTypeSelect ? orderTypeSelect.value : "MARKET";
  const productType = productTypeSelect ? productTypeSelect.value : "CNC";
  const qty = parseInt(qtyInput.value) || 0;

  let price = 0;
  if (orderType === "LIMIT" && priceInput) {
    price = parseFloat(priceInput.value) || 0;
  } else {
    price = currentOrderContext.ltp || 0;
    if (price <= 0) {
      const rawPriceText = document.getElementById("modalDisplayPrice")?.textContent || "0";
      price = parseFloat(rawPriceText.replace(/[^0-9.]/g, "")) || 0;
    }
  }

  hideModalAlert();

  if (price <= 0) {
    amountLabel.textContent = "Estimated Total:";
    estTotalElem.textContent = "Loading price...";
    fundsRemainingElem.textContent = `₹${formatINR(currentOrderContext.availableFunds)}`;
    submitBtn.disabled = false;
    return;
  }

  const isIntraday = productType === "MIS";
  const totalValue = qty * price;
  const marginOrTotal = isIntraday ? totalValue * 0.2 : totalValue;

  let isValid = true;
  let validationMessage = "";

  if (qty <= 0) {
    isValid = false;
    validationMessage = "Quantity must be greater than zero.";
  } else if (orderType === "LIMIT" && price <= 0) {
    isValid = false;
    validationMessage = "Please specify a valid limit price.";
  }

  if (action === "BUY") {
    amountLabel.textContent = isIntraday ? "Margin Required (20%):" : "Required Amount:";
    estTotalElem.textContent = `₹${formatINR(marginOrTotal)}`;

    const remainingFunds = currentOrderContext.availableFunds - marginOrTotal;
    remainingLabel.textContent = "Cash Remaining:";
    fundsRemainingElem.textContent = `₹${formatINR(remainingFunds)}`;

    if (marginOrTotal > currentOrderContext.availableFunds) {
      isValid = false;
      validationMessage = `Insufficient funds. Required ₹${formatINR(marginOrTotal)}, available ₹${formatINR(currentOrderContext.availableFunds)}.`;
      fundsRemainingElem.style.color = "var(--red)";
    } else {
      fundsRemainingElem.style.color = "var(--text-primary)";
    }
  } else {
    // SELL
    amountLabel.textContent = "Estimated Proceeds:";
    estTotalElem.textContent = `₹${formatINR(totalValue)}`;

    const projectedCash = currentOrderContext.availableFunds + totalValue;
    remainingLabel.textContent = "Cash After Trade:";
    fundsRemainingElem.textContent = `₹${formatINR(projectedCash)}`;
    fundsRemainingElem.style.color = "var(--green)";

    if (productType === "CNC" && qty > currentOrderContext.holdingQty) {
      isValid = false;
      validationMessage = `Insufficient holdings. You own ${currentOrderContext.holdingQty} shares, cannot sell ${qty}.`;
    }
  }

  if (!isValid && validationMessage) {
    showModalAlert(validationMessage);
    submitBtn.disabled = true;
  } else {
    submitBtn.disabled = false;
  }
}

async function handleOrderSubmit(event) {
  if (event) {
    if (typeof event.preventDefault === "function") event.preventDefault();
    if (typeof event.stopPropagation === "function") event.stopPropagation();
  }

  const submitBtn = document.getElementById("orderModalSubmitBtn");
  const symbolHidden = document.getElementById("modalSymbol");
  let symbol = symbolHidden ? symbolHidden.value.trim() : "";
  if (!symbol && currentOrderContext && currentOrderContext.symbol) {
    symbol = currentOrderContext.symbol;
    if (symbolHidden) symbolHidden.value = symbol;
  }

  const transactionType = document.getElementById("modalTransactionType")?.value || "BUY";
  const orderType = document.getElementById("modalOrderTypeSelect")?.value || "MARKET";
  const productType = document.getElementById("modalProductTypeSelect")?.value || "CNC";
  const qtyInput = document.getElementById("modalQtyInput");
  const qty = parseInt(qtyInput?.value) || 0;
  const priceInput = document.getElementById("modalPriceInput");
  const price = orderType === "LIMIT" ? (parseFloat(priceInput?.value) || 0) : null;

  if (!symbol) {
    showModalAlert("Please select an instrument.");
    return;
  }

  if (qty <= 0) {
    showModalAlert("Quantity must be greater than zero.");
    return;
  }

  if (orderType === "LIMIT" && (!price || price <= 0)) {
    showModalAlert("Please enter a valid Limit Price.");
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
  }
  const origBtnText = submitBtn ? submitBtn.textContent : "Place Order";
  if (submitBtn) {
    submitBtn.textContent = "Placing Order...";
  }

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);

    const res = await fetch("/order/place", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      signal: controller.signal,
      body: JSON.stringify({
        symbol: symbol,
        transaction_type: transactionType,
        order_type: orderType,
        product_type: productType,
        quantity: qty,
        price: price
      })
    });
    clearTimeout(timeoutId);

    const data = await res.json();
    if (res.ok && data.status === "success") {
      showToast(data.message, "success");
      closeOrderModal();
      // Gracefully release live SSE connection before reloading
      if (typeof window.closeLiveStream === "function") {
        window.closeLiveStream();
      }
      setTimeout(() => {
        window.location.reload();
      }, 500);
    } else {
      const errMsg = (data && data.message) ? data.message : "Order rejected by server.";
      showToast(errMsg, "error");
      showModalAlert(errMsg);
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = origBtnText;
      }
    }
  } catch (err) {
    console.error("Order submit network error:", err);
    const msg = err.name === "AbortError" 
      ? "Order request timed out. Please check your connection and retry." 
      : "Network error submitting order. Please try again.";
    showToast(msg, "error");
    showModalAlert(msg);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = origBtnText;
    }
  }
}

// Close modal on Escape key press
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeOrderModal();
  }
});
