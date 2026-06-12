# Trascrittore AI — Registrazione e riepilogo riunioni

App desktop per **Windows** che registra una riunione (su Teams, Meet, Zoom,
browser… qualsiasi piattaforma), la **trascrive in italiano** distinguendo
**"Io"** dai **"Partecipanti"**, e genera un **riepilogo AI** strutturato con
Claude.

Tutto parte da un clic su **Avvia** e finisce con un clic su **Stop**. Il
prodotto finale sono due file di testo nella cartella della riunione:
- `trascrizione.md` — la trascrizione integrale con orari e parlante;
- `riepilogo.md` — il riepilogo AI (sintesi, punti chiave, decisioni, azioni).

---

## Come funziona (in breve)

L'app apre **due flussi audio contemporaneamente**:
1. il **microfono** → diventa l'etichetta **"Io"**;
2. l'**audio di sistema** (ciò che si sente da casse/cuffie, tramite *WASAPI
   loopback*) → diventa **"Partecipanti"**.

Tenendo i due canali separati otteniamo la distinzione tra te e gli altri
**senza** usare modelli pesanti. L'audio viene scritto **su disco a blocchi**
durante la registrazione (mai tutto in RAM), così funziona anche per riunioni
lunghe su un PC con 16 GB e senza GPU.

---

## 🔒 Privacy

- La **trascrizione è in locale** (modello Whisper sul tuo PC): l'audio **non
  esce** dal computer.
- Il **riepilogo** invece usa l'**API di Claude (Anthropic)**: per generarlo,
  il *testo* della trascrizione viene inviato ai server di Anthropic. L'audio
  no, solo il testo. Se non vuoi inviare nulla all'esterno, non configurare la
  chiave API: otterrai comunque la trascrizione completa, senza il riepilogo.
- ⚠️ In futuro, se sostituirai il backend di trascrizione con uno **cloud**,
  l'**audio** verrebbe inviato a terzi: valutalo con attenzione.

---

## ⚖️ Avviso legale

Registrare una riunione può richiedere il **consenso dei partecipanti**, e le
regole cambiano per paese e contesto aziendale. L'app mostra un promemoria
all'avvio: assicurati di avere il diritto/consenso di registrare.

---

## Requisiti

- **Windows 10 / 11**
- **Python 3.13** (durante l'installazione spunta *"Add Python to PATH"*)
- Un **microfono** e un **dispositivo di uscita audio** (casse/cuffie) attivi
- Connessione a Internet **solo** per il riepilogo AI (la trascrizione è offline)

---

## Installazione (passo-passo)

Apri **PowerShell** nella cartella del progetto ed esegui i comandi uno alla
volta.

### 1) Crea un ambiente virtuale (consigliato)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Se PowerShell blocca lo script di attivazione, esegui una volta:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
> e riprova.

### 2) Installa le dipendenze

```powershell
pip install -r requirements.txt
```

> La prima volta che trascrivi, `faster-whisper` **scaricherà il modello**
> (qualche centinaio di MB per `large-v3-turbo`): serve Internet solo allora,
> poi resta in cache sul PC.

### 3) Configura la chiave API di Claude (per il riepilogo)

1. Copia il file `.env.example` e rinominalo in `.env`.
2. Apri `.env` e incolla la tua chiave Anthropic:

   ```
   ANTHROPIC_API_KEY=sk-ant-la-tua-chiave
   ```

> La chiave si ottiene dal tuo account su https://console.anthropic.com.
> Il file `.env` **non** va condiviso e **non** finisce su Git (è già escluso
> in `.gitignore`).

---

## Avvio dell'app

```powershell
python main.py
```

1. Leggi l'avviso legale e premi **OK**.
2. Clic su **● Avvia registrazione** → parte la cattura (vedi il timer `● REC`).
3. Svolgi la riunione (nessun limite di durata).
4. Clic su **■ Stop** → l'app trascrive e riepiloga (barra di avanzamento).
5. Alla fine si apre automaticamente la **cartella dei risultati**.

---

## Dove finiscono i risultati

Per ogni riunione viene creata una cartella con data e ora, ad esempio:

```
output/2026-06-12_15-30/
├── audio_microfono.wav   (la tua voce, "Io")
├── audio_sistema.wav     (gli altri, "Partecipanti")
├── trascrizione.md       (trascrizione integrale con orari e parlante)
└── riepilogo.md          (riepilogo AI strutturato)
```

> **Le registrazioni non vengono mai cancellate automaticamente.** Se vuoi
> liberare spazio, elimina tu le vecchie cartelle dentro `output/`.

---

## Configurazione (`config.yaml`)

Puoi modificare senza toccare il codice:

| Voce | Cosa controlla | Valori utili |
|------|----------------|--------------|
| `cartella_output` | dove salvare le riunioni | es. `"output"` |
| `trascrizione.modello` | qualità/velocità Whisper | `medium` (veloce), `large-v3-turbo` (default), `large-v3` (preciso) |
| `trascrizione.compute_type` | leggerezza su CPU | `int8` (default), `int8_float16`, `float32` |
| `trascrizione.lingua` | lingua della riunione | `it` |
| `riepilogo.backend` | servizio per il riepilogo AI | `nessuno` (solo trascrizione), `deepseek`, `claude` |
| `riepilogo.modello_deepseek` | modello DeepSeek | `deepseek-reasoner` (potente), `deepseek-chat` (veloce) |
| `riepilogo.modello_claude` | modello Claude | `claude-sonnet-4-6` |
| `riepilogo.caratteri_per_blocco` | soglia per il map-reduce | es. `12000` |

> **Riepilogo AI (opzionale e a pagamento).** Di default `backend: nessuno`: l'app
> fa solo la trascrizione (gratis e offline). Per attivare il riepilogo, metti
> `deepseek` o `claude`, inserisci la chiave corrispondente nel file `.env`
> (`DEEPSEEK_API_KEY` o `ANTHROPIC_API_KEY`) e assicurati che l'account abbia
> credito. DeepSeek richiede una piccola ricarica su https://platform.deepseek.com.

> Su CPU senza GPU, se la trascrizione è troppo lenta passa il modello a
> `medium`: è molto più rapido, con una precisione solo leggermente inferiore.

---

## Struttura del progetto

```
audio_capture.py   Cattura microfono + audio di sistema (loopback), scrive i WAV
transcriber.py     Interfaccia Transcriber + implementazione FasterWhisper
summarizer.py      Riepilogo AI con Claude (con strategia map-reduce)
pipeline.py        Orchestrazione: trascrivi -> fondi Io/Partecipanti -> riepiloga -> salva
gui.py             Finestra PySide6 (Avvia/Stop, timer, avanzamento)
main.py            Punto di ingresso
config.py          Caricamento di config.yaml e .env
config.yaml        Impostazioni modificabili
.env               La tua chiave API (da creare; non condividere)
```

---

## Problemi comuni

- **"Impossibile trovare il dispositivo di LOOPBACK"**
  Assicurati di avere un'uscita audio (casse/cuffie) attiva e impostata come
  predefinita in *Impostazioni Windows → Sistema → Audio*. Alcune cuffie
  Bluetooth in modalità "headset/mani libere" non espongono il loopback: usa
  cuffie via jack/USB o imposta il profilo Bluetooth su "stereo".

- **"Nessun microfono di default trovato"**
  Collega/abilita un microfono e impostalo come predefinito in Windows.

- **Il riepilogo non viene generato**
  Probabilmente manca la chiave API in `.env`, oppure non c'è connessione o
  credito. La **trascrizione viene comunque salvata**: aggiungi la chiave e
  riprova in seguito.

- **La trascrizione è lenta**
  È normale su CPU. Usa il modello `medium` in `config.yaml` per velocizzare.
```
