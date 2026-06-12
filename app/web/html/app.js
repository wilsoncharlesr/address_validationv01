// Address verification form: search -> pick one of the top 3 -> submit to nad_sub.

const $ = (id) => document.getElementById(id);

const queryInput = $("query");
const searchBtn = $("searchBtn");
const submitBtn = $("submitBtn");
const resultsBox = $("results");
const resultList = $("resultList");
const message = $("message");
const selectionHint = $("selectionHint");

let lastQuery = "";
let selected = null;

function showMessage(text, kind = "info") {
  message.innerHTML = `<div class="banner ${kind}">${text}</div>`;
}
function clearMessage() {
  message.innerHTML = "";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function cityLine(r) {
  const parts = [r.city, r.state].filter(Boolean).join(", ");
  return [parts, r.zip].filter(Boolean).join(" ");
}

async function search() {
  const q = queryInput.value.trim();
  if (!q) {
    showMessage("Enter an address to search.", "error");
    return;
  }
  lastQuery = q;
  selected = null;
  submitBtn.disabled = true;
  resultsBox.classList.add("hidden");
  searchBtn.disabled = true;
  searchBtn.innerHTML = '<span class="spinner"></span>';
  clearMessage();

  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
    });
    if (!res.ok) {
      let msg = `Search failed (HTTP ${res.status})`;
      try {
        const { error } = await res.json();
        if (error) msg = error;
      } catch { /* non-JSON error body — keep the generic message */ }
      throw new Error(msg);
    }
    const matches = await res.json();
    renderResults(matches);
  } catch (err) {
    showMessage(escapeHtml(err.message), "error");
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = "Search";
  }
}

function renderResults(matches) {
  if (!matches || matches.length === 0) {
    resultsBox.classList.add("hidden");
    showMessage("No close matches found. Try adding the city, state or ZIP.", "info");
    return;
  }

  resultList.innerHTML = "";
  matches.forEach((r, i) => {
    const pct = Math.round((r.score || 0) * 100);
    const unit = r.unit ? ` <span class="muted">(${escapeHtml(r.unit)})</span>` : "";
    const row = document.createElement("div");
    row.className = "result";
    row.innerHTML = `
      <input type="radio" name="match" value="${i}" />
      <div>
        <div class="addr">${escapeHtml(r.address)}${unit}</div>
        <div class="meta">${escapeHtml(cityLine(r))}${r.county ? " &middot; " + escapeHtml(r.county) + " County" : ""}</div>
      </div>
      <div class="score">match<b>${pct}%</b></div>`;
    row.addEventListener("click", () => choose(i, r, row));
    resultList.appendChild(row);
  });

  resultsBox.classList.remove("hidden");
  submitBtn.disabled = true;
  selectionHint.textContent = "Select a match to enable submit.";
}

function choose(index, record, rowEl) {
  selected = record;
  document.querySelectorAll(".result").forEach((el) => el.classList.remove("selected"));
  rowEl.classList.add("selected");
  rowEl.querySelector('input[type="radio"]').checked = true;
  submitBtn.disabled = false;
  selectionHint.textContent = "";
}

async function submit() {
  if (!selected) return;
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="spinner"></span>';

  try {
    const payload = { ...selected, query: lastQuery };
    const res = await fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Submit failed (HTTP ${res.status})`);
    const data = await res.json();
    resultsBox.classList.add("hidden");
    showMessage(
      `Saved to <b>nad_sub</b> (record #${data.id}): ${escapeHtml(selected.address)}, ` +
      `${escapeHtml(cityLine(selected))}. ` +
      `<a href="stats.html">View statistics &rarr;</a>`,
      "success"
    );
    queryInput.value = "";
    selected = null;
  } catch (err) {
    showMessage(escapeHtml(err.message), "error");
    submitBtn.disabled = false;
  } finally {
    submitBtn.textContent = "Submit selected address";
  }
}

searchBtn.addEventListener("click", search);
submitBtn.addEventListener("click", submit);
queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") search();
});
