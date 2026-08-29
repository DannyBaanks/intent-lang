const source = document.querySelector("#source");
const language = document.querySelector("#language");
const resolveButton = document.querySelector("#resolve");
const output = document.querySelector("#output");
const trace = document.querySelector("#trace");
const state = document.querySelector("#result-state");
const count = document.querySelector("#char-count");
const roundtrip = document.querySelector("#roundtrip-label");
const copyButton = document.querySelector("#copy");
const machineStatus = document.querySelector("#machine-status");

let lastIR = "";

function stamp() {
  return new Date().toLocaleTimeString("es-ES", { hour12: false });
}

function addTrace(message, className = "trace-muted") {
  const line = document.createElement("div");
  line.innerHTML = `<span class="trace-time">${stamp()}</span><span class="${className}">${message}</span>`;
  trace.appendChild(line);
  trace.scrollTop = trace.scrollHeight;
}

function setState(label, className) {
  state.textContent = label;
  state.className = `state-badge ${className}`;
}

function renderValue(value) {
  if (typeof value === "string") return `<span class="ir-value">&quot;${escapeHTML(value)}&quot;</span>`;
  if (value === null) return `<span class="ir-value">null</span>`;
  return `<span class="ir-value">${escapeHTML(JSON.stringify(value))}</span>`;
}

function renderIR(intent) {
  const entries = Object.entries(intent);
  return entries.map(([key, value]) => `<div><span class="ir-key">${escapeHTML(key)}</span>: ${renderValue(value)}</div>`).join("");
}

function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

async function resolveIntent() {
  const text = source.value.trim();
  if (!text) {
    source.focus();
    setState("SIN ENTRADA", "warn");
    return;
  }

  resolveButton.disabled = true;
  resolveButton.querySelector("span").textContent = "Resolviendo...";
  setState("PROCESANDO", "");
  addTrace(`resolve(${language.value})`, "trace-muted");

  try {
    const response = await fetch("api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang: language.value }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No se pudo resolver");

    machineStatus.innerHTML = "<i></i> LOCAL / STRICT";

    lastIR = JSON.stringify(result.intent, null, 2);
    output.innerHTML = `<div class="ir-block">${renderIR(result.intent)}</div>`;
    copyButton.disabled = false;
    const ok = result.intent.status === "RESOLVED";
    setState(ok ? "RESOLVED" : result.intent.status || "RESULTADO", ok ? "pass" : "warn");
    roundtrip.textContent = `round-trip: ${result.round_trip}`;
    roundtrip.className = ok ? "roundtrip-ok" : "roundtrip-bad";
    addTrace(ok ? "Intent IR RESOLVED" : `Intent IR ${result.intent.status}`, ok ? "trace-good" : "trace-warn");
    addTrace("sin ejecución de capabilities", "trace-muted");
  } catch (error) {
    const demo = staticDemo(text, language.value);
    if (demo) {
      machineStatus.innerHTML = "<i></i> STATIC / DEMO";
      lastIR = JSON.stringify(demo.intent, null, 2);
      output.innerHTML = `<div class="ir-block">${renderIR(demo.intent)}</div>`;
      copyButton.disabled = false;
      setState("DEMO", "warn");
      roundtrip.textContent = `round-trip: ${demo.round_trip}`;
      roundtrip.className = "roundtrip-ok";
      addTrace("Pages: backend Python no disponible", "trace-warn");
      addTrace("ejemplo local, sin resolución de red", "trace-muted");
    } else {
      output.innerHTML = `<div class="trace-bad">ERROR: ${escapeHTML(error.message)}<br><br>En GitHub Pages solo están disponibles los ejemplos locales.</div>`;
      setState("SIN BACKEND", "fail");
      roundtrip.textContent = "round-trip: —";
      addTrace("backend local no disponible", "trace-bad");
    }
  } finally {
    resolveButton.disabled = false;
    resolveButton.querySelector("span").textContent = "Resolver intención";
  }
}

function staticDemo(text, lang) {
  const examples = {
    "es|agrégale cuerpo": {
      verb: { ili: "i22623", lemma: "agregar" },
      operand: { ili: "i70091", lemma: "cuerpo" },
      scope: null, status: "RESOLVED",
      provenance: { language: "es", lexical_source: "omw-es:1.4", resolution: "demo", mode: "strict" },
      primitive: "ADD", candidates: [], schema: "intent/1",
    },
    "en|add body": {
      verb: { ili: "i22623", lemma: "add" },
      operand: { ili: "i70091", lemma: "body" },
      scope: null, status: "RESOLVED",
      provenance: { language: "en", lexical_source: "omw-en:1.4", resolution: "demo", mode: "strict" },
      primitive: "ADD", candidates: [], schema: "intent/1",
    },
  };
  const intent = examples[`${lang}|${text.toLowerCase()}`];
  return intent ? { intent, round_trip: `Entendí: ${intent.primitive} (${intent.operand.lemma}). ¿Correcto?` } : null;
}

source.addEventListener("input", () => {
  count.textContent = `${source.value.length} caracteres`;
});

source.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    resolveIntent();
  }
});

document.querySelector("#clear").addEventListener("click", () => {
  source.value = "";
  count.textContent = "0 caracteres";
  output.innerHTML = `<div class="empty-state"><span class="empty-glyph">[ _ ]</span><p>El resultado aparecerá aquí.</p><small>La salida muestra el IR y el round-trip.</small></div>`;
  setState("EN ESPERA", "idle");
  roundtrip.textContent = "round-trip: —";
  roundtrip.className = "";
  copyButton.disabled = true;
});

document.querySelector("#swap").addEventListener("click", () => {
  const examples = {
    es: "agrégale cuerpo",
    en: "add body",
    zh: "添加身体",
    ja: "本体を追加",
    ar: "أضف الجسم",
    fi: "lisää runko",
    he: "הוסף גוף",
    tr: "gövde ekle",
  };
  source.value = examples[language.value] || examples.es;
  source.dispatchEvent(new Event("input"));
  source.focus();
});

copyButton.addEventListener("click", async () => {
  if (!lastIR) return;
  await navigator.clipboard.writeText(lastIR);
  copyButton.textContent = "Copiado";
  window.setTimeout(() => { copyButton.textContent = "Copiar IR"; }, 1200);
});

resolveButton.addEventListener("click", resolveIntent);
