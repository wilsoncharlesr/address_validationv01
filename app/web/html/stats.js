// Statistics page: per-county and per-state counts for the nad and nad_sub databases.

const $ = (id) => document.getElementById(id);
const message = $("message");

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmt(n) {
  return Number(n).toLocaleString("en-US");
}

function renderBuckets(el, buckets) {
  if (!buckets || buckets.length === 0) {
    el.innerHTML = '<div class="empty">No data yet.</div>';
    return;
  }
  const max = Math.max(...buckets.map((b) => b.count));
  el.innerHTML = buckets
    .map((b) => {
      const w = max > 0 ? Math.max(2, (b.count / max) * 100) : 0;
      return `
        <div class="bar-row">
          <div class="name" title="${escapeHtml(b.name)}">${escapeHtml(b.name)}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div>
          <div class="count">${fmt(b.count)}</div>
        </div>`;
    })
    .join("");
}

function setTotal(el, total) {
  el.innerHTML = `${fmt(total)}<small> addresses</small>`;
}

async function load() {
  message.innerHTML = "";
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) throw new Error(`Failed to load statistics (HTTP ${res.status})`);
    const data = await res.json();

    setTotal($("nadTotal"), data.nad.total);
    renderBuckets($("nadByState"), data.nad.byState);
    renderBuckets($("nadByCounty"), data.nad.byCounty);

    setTotal($("subTotal"), data.nadSub.total);
    renderBuckets($("subByState"), data.nadSub.byState);
    renderBuckets($("subByCounty"), data.nadSub.byCounty);
  } catch (err) {
    message.innerHTML = `<div class="banner error">${escapeHtml(err.message)}</div>`;
  }
}

$("refreshBtn").addEventListener("click", load);
load();
