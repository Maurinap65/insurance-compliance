import streamlit as st
import streamlit.components.v1 as components
import os, re, json, glob, math, base64
import requests
from datetime import datetime
from dotenv import load_dotenv
from fpdf import FPDF

st.set_page_config(page_title="NEXORA Insurance & Financial Compliance", page_icon="🛡️", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;}\nfooter {visibility: hidden;}\nheader {visibility: hidden;}\ndiv[data-testid*='BorderWrapper'], div[class*='BorderWrapper'], div[data-testid*='BorderWrapper'] * { border-color: #e879f9 !important; border-radius: 14px; border-width: 2px !important; }\n</style>", unsafe_allow_html=True)

load_dotenv()
def _sec(name):
    v = os.environ.get(name, "")
    if v: return v
    try: return str(st.secrets[name])
    except Exception: return ""
ANTHROPIC_API_KEY = _sec("ANTHROPIC_API_KEY")

SKILL_PROMPT = '''Sei un Senior Compliance Officer specializzato in normativa italiana per i settori assicurativo (IVASS) e bancario/finanziario (Banca d'Italia, MIFID II, AGCM).

Il tuo compito è analizzare copy pubblicitari, materiali promozionali e testi commerciali, verificandone la conformità rispetto alle regole di compliance del settore.

REGOLE FONDAMENTALI (STRETTAMENTE VINCOLANTI):

1. TEMPERATURA = 0.0
   Non devi essere creativo. La tua funzione è puramente di verifica fattuale e normativa. Non suggerisci alternative creative, non riscrivi il testo, non proponi variazioni di tono.

2. CITAZIONE OBBLIGATORIA
   Ogni anomalia segnalata DEVE essere collegata a un riferimento normativo specifico presente nella knowledge base. Se non trovi il riferimento nella knowledge base, devi dichiararlo esplicitamente: "Riferimento normativo non trovato nella knowledge base caricata".

3. ZERO ALLUCINAZIONI
   Se non trovi una regola specifica nella knowledge base, NON inventarla. Rispondi: "Informazione non presente nei documenti caricati. Verifica manuale richiesta."

4. MAI RISCIVERE DA SOLO
   Non proponi mai una riscrittura completa del copy. Puoi suggerire correzioni puntuali solo se strettamente necessarie e supportate da riferimento normativo. La decisione finale è sempre umana.

5. HUMAN-IN-THE-LOOP
   Alla fine di ogni analisi, devi sempre includere il flag: "Validazione umana richiesta prima dell'uso".

6. RICONOSCIMENTO CONTESTO
   Identifica automaticamente se il materiale riguarda:
   - Prodotti assicurativi (Ramo Vita, Ramo Danni, IBIP)
   - Prodotti bancari (mutui, prestiti, conti correnti, investimenti)
   - Prodotti finanziari (fondi, ETF, strumenti di investimento MIFID II)
   Adatta le regole di verifica al contesto specifico.

FORMATO DI OUTPUT — DUE SEZIONI OBBLIGATORIE:

La tua risposta deve contenere SEMPRE due sezioni distinte, in questo ordine:

SEZIONE 1 — REPORT PER IL CLIENTE

Genera un report in formato markdown, professionale e leggibile, con questa struttura:

# Report di Compliance
**Data analisi:** [DATA CORRENTE]
**Tipo materiale:** [advertising / promotional / informational]
**Settore:** [assicurativo / bancario / finanziario / misto]
**Stato complessivo:** [COMPLIANT / NEEDS_REVISION / CRITICAL_FAIL]

## Riepilogo Esecutivo
[2-3 frasi in linguaggio chiaro]

## Violazioni Critiche
[Per ciascuna: Posizione / Problema / Norma violata / Azione richiesta]

## Avvertenze
[Stesso formato, gravità minore]

## Note Informative
[Osservazioni non critiche utili al revisore]

## Elementi Mancanti
[Lista elementi obbligatori assenti con riferimento normativo]

## Azioni Raccomandate
[Lista numerata per priorità]

## Nota per il Revisore Umano
[Contenuto di compliance_reviewer_notes. La validazione finale è umana.]

*Report generato automaticamente dal sistema di Compliance QA. Validazione umana richiesta prima dell'uso.*

SEZIONE 2 — JSON TECNICO

{
  "document_type_detected": "advertising" | "promotional" | "informational" | "unknown",
  "sector_detected": "assicurativo" | "bancario" | "finanziario" | "misto",
  "overall_compliance_status": "COMPLIANT" | "NEEDS_REVISION" | "CRITICAL_FAIL",
  "violations": [
    {
      "severity": "CRITICAL" | "WARNING" | "INFO",
      "location": "es. Paragrafo 2, riga 5",
      "issue": "Descrizione precisa del problema",
      "regulatory_reference": "es. Regolamento IVASS n. 41/2018, Art. 31, comma 2",
      "suggested_correction": "Azione correttiva specifica supportata da riferimento",
      "source_doc": "Nome file + pagina/paragrafo della fonte"
    }
  ],
  "missing_disclaimers": ["es. Manca avviso: prima della sottoscrizione leggere il set informativo"],
  "compliance_reviewer_notes": "Riassunto in italiano per il revisore umano."
}

ISTRUZIONI OPERATIVE:
- Analizza il testo paragrafo per paragrafo.
- Per ogni claim verifica se esiste una regola nella knowledge base che lo vieta, limita o obbliga.
- Se mancano disclaimer obbligatori, inseriscili in missing_disclaimers.
- Se il testo è conforme, overall_compliance_status COMPLIANT con violations vuoto.
- Se non sei sicuro, severity WARNING e segnalalo in compliance_reviewer_notes.

NORMATIVA DI RIFERIMENTO PRIMARIA (verificare sempre nella knowledge base):
- Regolamento IVASS n. 41/2018 (distribuzione prodotti assicurativi)
- Regolamento IVASS n. 45/2020 (governo e controllo prodotti POG)
- Circolare Banca d'Italia n. 285/2013 (trasparenza operazioni bancarie)
- Regolamento Delegato (UE) 2017/565 (MIFID II)
- Codice del Consumo + Pratiche commerciali scorrette AGCM

CONTESTO AGGIUNTIVO (RECUPERATO DALLA KNOWLEDGE BASE):
{retrieved_knowledge_chunks}'''

CLAUDE_MODELS = ["claude-sonnet-4-5", "claude-sonnet-4-20250514", "claude-3-7-sonnet-latest"]

def parse_json_loose(text):
    try: return json.loads(text)
    except Exception:
        a = text.find("{"); b = text.rfind("}")
        if a != -1 and b > a:
            try: return json.loads(text[a:b+1])
            except Exception: pass
        raise ValueError("JSON non valido o troncato")

def ask_claude(system_text, user_text, image_b64=None, mime="image/png", on_delta=None, stream=True, max_tokens=16000):
    content = []
    if image_b64:
        mt = mime if mime in ("image/png", "image/jpeg", "image/gif", "image/webp") else "image/png"
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": image_b64}})
    content.append({"type": "text", "text": user_text})
    last = None
    errs = []
    for model in CLAUDE_MODELS:
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": max_tokens, "system": system_text,
                      "messages": [{"role": "user", "content": content}], "stream": stream},
                timeout=600, stream=stream)
            if r.status_code != 200:
                t = r.text.lower()
                if r.status_code in (400, 404) and ("model" in t or "not found" in t):
                    last = Exception("modello non disponibile: " + model); errs.append(model + " => model-not-found"); continue
                last = Exception("HTTP " + str(r.status_code) + ": " + r.text[:300]); errs.append(model + " => HTTP " + str(r.status_code) + " " + r.text[:150]); continue
            if not stream:
                return r.json()["content"][0]["text"], model
            acc = ""
            for line in r.iter_lines():
                if not line: continue
                s = line.decode("utf-8", "replace")
                if not s.startswith("data:"): continue
                d = s[5:].strip()
                if d == "[DONE]": break
                try: j = json.loads(d)
                except Exception: continue
                if j.get("type") == "content_block_delta":
                    txt = j.get("delta", {}).get("text", "")
                    if txt:
                        acc += txt
                        if on_delta: on_delta(acc)
            if not acc: raise Exception("risposta vuota da " + model)
            return acc, model
        except Exception as e:
            last = e
            errs.append(model + " => EXC " + repr(e)[:150])
    st.error("🛑 ERRORE MOTORE: " + repr(last) + " || DETTAGLI: " + " | ".join(errs))
    st.stop()

@st.cache_resource
def load_kb():
    chunks = []
    for f in sorted(glob.glob("kb/*.txt")):
        name = os.path.basename(f)
        text = open(f, encoding="utf-8", errors="replace").read()
        text = re.sub(r"\n{3,}", "\n\n", text)
        buf = ""
        for p in text.split("\n\n"):
            p = p.strip()
            if len(p) < 40:
                if buf: buf += "\n" + p
                continue
            if len(buf) + len(p) > 1800:
                if buf: chunks.append((name, buf))
                buf = p
            else:
                buf = buf + "\n\n" + p if buf else p
        if buf: chunks.append((name, buf))
    return chunks

def tok(s): return re.findall(r"[a-zà-öø-ÿ0-9]{3,}", s.lower())

def retrieve(chunks, query, top=20):
    q = tok(query)
    if not q: return []
    docs = [tok(c[1]) for c in chunks]
    df = {}
    for d in docs:
        for t in set(d): df[t] = df.get(t, 0) + 1
    N = max(1, len(chunks))
    scored = []
    for (name, text), d in zip(chunks, docs):
        s = 0.0
        for t in set(q):
            c = d.count(t)
            if c: s += c * math.log((N + 1) / (1 + df.get(t, 0)))
        scored.append((s, name, text))
    scored.sort(key=lambda x: -x[0])
    return [(n, t) for s, n, t in scored[:top] if s > 0]

def clean(s):
    s = s.replace("—", "-").replace("–", "-").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    s = re.sub(r"[✅⚠❌🔴🟡🟢📎ℹ📋🔍📄⏳]", "", s)
    return s.encode("latin-1", "ignore").decode("latin-1")

def paint_boxes():
    html = """<script>
    (function(){
      var d = window.parent.document;
      function paint(){
        ['nxbox1','nxbox2'].forEach(function(id){
          var mk = d.getElementById(id);
          if(!mk) return;
          var el = mk.parentElement;
          while(el && el !== d.body){
            var cs = window.parent.getComputedStyle(el);
            if(parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle === 'solid'){
              el.style.borderColor = '#e879f9';
              el.style.borderWidth = '2px';
              el.style.borderRadius = '14px';
              break;
            }
            el = el.parentElement;
          }
        });
      }
      if(window.__nxpaint) clearInterval(window.__nxpaint);
      window.__nxpaint = setInterval(paint, 800);
      paint();
    })();
    </script>"""
    components.html(html, height=0, width=0)

def set_topbar(msg):
    if msg:
        m = msg.replace("'", "").replace('"', "")
        html = "<script>var d=window.parent.document;var el=d.getElementById('nx-topbar');if(!el){el=d.createElement('div');el.id='nx-topbar';d.body.appendChild(el);}el.style.cssText='position:fixed;top:14px;right:14px;z-index:999999;background:#0b1220;border:1px solid #e879f9;color:#e879f9;padding:8px 16px;border-radius:999px;font:600 13px system-ui,sans-serif;box-shadow:0 6px 18px rgba(0,0,0,.55)';el.textContent='" + m + "';</script>"
    else:
        html = "<script>var d=window.parent.document;var el=d.getElementById('nx-topbar');if(el){el.remove();}</script>"
    components.html(html, height=0, width=0)

def autoscroll(on):
    if on:
        html = """<script>
        function nxScrollAll(){
          var d = window.parent.document;
          var t = [d.scrollingElement, d.documentElement, d.body,
                   d.querySelector("section.main"),
                   d.querySelector("[data-testid='stMain']"),
                   d.querySelector("[data-testid='stAppViewContainer']")];
          t.forEach(function(x){ if(x){ x.scrollTop = x.scrollHeight; } });
        }
        if(window.parent.__nxscroll){ clearInterval(window.parent.__nxscroll); }
        window.parent.__nxscroll = setInterval(nxScrollAll, 500);
        nxScrollAll();
        </script>"""
    else:
        html = """<script>if(window.parent.__nxscroll){ clearInterval(window.parent.__nxscroll); window.parent.__nxscroll = null; }</script>"""
    components.html(html, height=0, width=0)

def scroll_to_report():
    html = """<script>
    setTimeout(function(){
      var d = window.parent.document;
      var el = d.getElementById("nxbox2");
      if(el){ el.scrollIntoView({behavior:"smooth", block:"start"}); }
      else {
        var b = d.querySelector("[data-testid='stDownloadButton']");
        if(b){ b.scrollIntoView({behavior:"smooth", block:"center"}); }
      }
    }, 600);
    </script>"""
    components.html(html, height=0, width=0)

def build_pdf(md, model):
    pdf = FPDF()
    pdf.add_page()
    if os.path.exists("logo.png"):
        try: pdf.image("logo.png", x=140, y=8, w=60)
        except Exception: pass
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, clean("REPORT DI COMPLIANCE - Insurance & Financial"))
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 6, clean("Data: " + datetime.now().strftime("%d/%m/%Y %H:%M") + " - Motore: " + model))
    pdf.set_x(pdf.l_margin)
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 9)
    for line in md.split("\n"):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, clean(line))
        if pdf.get_y() > 270:
            pdf.add_page(); pdf.set_font("Helvetica", "", 9)
    return bytes(pdf.output())

_hc1, _hc2 = st.columns([3, 1])
with _hc1:
    st.title("🛡️ NEXORA Insurance & Financial Compliance")
    st.caption("Verifica di conformità IVASS · Banca d'Italia · MiFID II · AGCM — Validazione umana richiesta prima dell'uso")
with _hc2:
    _lp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    if os.path.exists(_lp):
        import base64 as _b64
        _lb = _b64.b64encode(open(_lp, "rb").read()).decode()
        st.markdown('<div style="background:#ffffff;padding:10px 14px;border-radius:14px;display:inline-block"><img src="data:image/png;base64,' + _lb + '" style="width:320px;height:auto"></div>', unsafe_allow_html=True)
    else:
        st.caption("logo.png mancante")

tab1, tab2 = st.tabs(["🔍 Check Materiale", "💬 Q&A Normativo"])

with tab1:
    with st.container():
        st.markdown("### Carica il materiale da verificare")
        ad_text = st.text_area("Testo del materiale (copy, pagina web, volantino)...", height=200)
        ad_image = st.file_uploader("Oppure immagine/screenshot (PNG/JPG)", type=["png", "jpg", "jpeg"])
        prod_file = st.file_uploader("📄 Documento di prodotto (Set Informativo / DIP / KID, facoltativo)", type=["pdf", "txt"])
        colA, colB = st.columns(2)
        with colA: analyze = st.button("🔍 Analizza conformità", type="primary")
        with colB:
            if st.button("🧹 Svuota tutto"):
                st.session_state.pop("ass_result", None)
                st.rerun()

    prod_text = ""
    if prod_file:
        try:
            if prod_file.name.lower().endswith(".txt"):
                prod_text = prod_file.read().decode("utf-8", "replace")
            else:
                from pypdf import PdfReader
                import io as _io
                prod_text = "\n".join(p.extract_text() or "" for p in PdfReader(_io.BytesIO(prod_file.read())).pages)
        except Exception as _e:
            st.caption("⚠️ Impossibile leggere il documento: " + str(_e))

    if analyze and not ANTHROPIC_API_KEY:
        st.error("Chiave Anthropic non configurata.")
    elif analyze and (ad_text.strip() or ad_image):
        with st.status("🔎 Analisi di conformità in corso...", expanded=True) as status:
            autoscroll(True)
            set_topbar("🛡️ Analisi in corso...")
            st.write("📚 Recupero regole dalla Knowledge Base...")
            chunks = load_kb()
            results = retrieve(chunks, ad_text or "polizza investimento finanziamento rendimento", 20)
            st.write(f"✅ {len(results)} chunk recuperati")
            context = "\n\n---\n\n".join([f"[{n}]\n{t}" for n, t in results])
            system = SKILL_PROMPT.replace("{retrieved_knowledge_chunks}", context) + "\n\nIMPORTANTE: termina SEMPRE la risposta con la SEZIONE 2 contenente SOLO un oggetto JSON valido, senza recinzioni markdown."
            if prod_text:
                system += "\n\nDOCUMENTO DI PRODOTTO CARICATO (Set Informativo/DIP/KID):\n" + prod_text[:60000] + "\n\nISTRUZIONI PRODOTTO: verifica che ogni claim economico/di rendimento/di garanzia sia coerente con il documento di prodotto; segnala le incoerenze come violazioni citando la sezione del documento."
            st.write("🧠 Analisi approfondita in corso...")
            image_b64 = base64.b64encode(ad_image.read()).decode() if ad_image else None
            mime = ad_image.type if ad_image else "image/png"
            live = st.empty()
            try:
                raw, model = ask_claude(system, "MATERIALE DA ANALIZZARE:\n" + ad_text, image_b64, mime, on_delta=lambda s: live.text("⏳ Report in generazione...\n" + s[-500:]))
            except Exception:
                raw, model = ask_claude(system, "MATERIALE DA ANALIZZARE:\n" + ad_text, image_b64, mime, stream=False)
            modello = "NEXORA Deep Engine"
            m2 = raw.find("SEZIONE 2")
            md = raw[:m2] if m2 != -1 else raw
            js = raw[m2:] if m2 != -1 else raw
            try: rep = parse_json_loose(js)
            except Exception: rep = {}
            if not rep.get("overall_compliance_status"):
                up = raw.upper()
                rep["overall_compliance_status"] = "CRITICAL_FAIL" if ("CRITICAL" in up or "NON CONFORME" in up or "VIOLAZIONI GRAVI" in up) else "NEEDS_REVISION"
            if not rep.get("sector_detected"):
                low = raw.lower()
                ass = "assicurativ" in low; ban = "bancar" in low; fin = "finanziari" in low
                rep["sector_detected"] = "misto" if (ass and (ban or fin)) else ("assicurativo" if ass else ("finanziario" if fin else ("bancario" if ban else "n.d.")))
            md = re.sub(r"═+", "", md).replace("SEZIONE 1 - REPORT PER IL CLIENTE", "").strip()
            st.session_state["ass_result"] = {"md": md, "rep": rep, "model": modello}
            autoscroll(False)
        st.rerun()

    if st.session_state.get("ass_result"):
        set_topbar(None)
        r = st.session_state["ass_result"]
        rep = r["rep"]
        stato = rep.get("overall_compliance_status", "NEEDS_REVISION")
        badge = {"COMPLIANT": "🟢", "NEEDS_REVISION": "🟡", "CRITICAL_FAIL": "🔴"}.get(stato, "🟡")
        with st.container(border=True):
            st.markdown(f"## {badge} Stato complessivo: {stato}")
            st.caption(f"Settore rilevato: {rep.get('sector_detected','n.d.')} · Motore: {r['model']}")
            st.markdown(r["md"])
            pdf = build_pdf(r["md"], r["model"])
            st.download_button("📄 Scarica report PDF", pdf, file_name="report_compliance_ass_" + datetime.now().strftime("%Y%m%d_%H%M") + ".pdf", type="primary")

with tab2:
    st.markdown("### 💬 Q&A Normativo Assicurativo/Finanziario")
    q = st.text_input("Fai una domanda (es. 'Posso pubblicizzare un rendimento garantito?')")
    if q:
        chunks = load_kb()
        res = retrieve(chunks, q, 6)
        ctx = "\n\n---\n\n".join([f"[{n}]\n{t}" for n, t in res])
        sysq = "Sei un esperto di compliance assicurativa/bancaria/finanziaria italiana. Rispondi in italiano, citando SEMPRE documento e articolo pertinenti dalla knowledge base. Se non trovi la regola rispondi: 'Informazione non presente nei documenti caricati. Verifica manuale richiesta.' Chiudi con: 'Validazione umana richiesta prima dell'uso.'\n\nKNOWLEDGE BASE:\n" + ctx
        try:
            raw, _ = ask_claude(sysq, q, stream=False, max_tokens=2000)
            st.markdown(raw)
        except Exception as e:
            st.error("Errore: " + str(e))
