# Trascrittore AI — Registrazione, trascrizione e riepilogo di riunioni

App **desktop per Windows** che registra una riunione su **qualsiasi piattaforma**
(Microsoft Teams, Google Meet, Zoom, browser…), la **trascrive in italiano**
distinguendo **"Io"** (la tua voce) dai **"Partecipanti"** (gli altri), e — se
vuoi — genera un **riepilogo AI** strutturato.

Tutto parte da un clic su **Avvia** e finisce con un clic su **Stop**. Il
risultato è una cartella per riunione con l'audio e i file di testo pronti.

---

## Indice

1. [Cosa fa](#cosa-fa)
2. [Come funziona (spiegazione)](#come-funziona-spiegazione)
3. [Requisiti](#requisiti)
4. [Installazione passo-passo](#installazione-passo-passo)
5. [Come si usa](#come-si-usa)
6. [Dove finiscono i risultati](#dove-finiscono-i-risultati)
7. [Trascrizione: Locale vs Cloud (Groq)](#trascrizione-locale-vs-cloud-groq)
8. [Riepilogo AI (opzionale)](#riepilogo-ai-opzionale)
9. [Configurazione (config.yaml)](#configurazione-configyaml)
10. [Privacy e sicurezza](#privacy-e-sicurezza)
11. [Avviso legale](#avviso-legale)
12. [Struttura del progetto](#struttura-del-progetto)
13. [Installare/aggiornare su un altro PC](#installareaggiornare-su-un-altro-pc)
14. [Problemi comuni](#problemi-comuni)

---

## Cosa fa

- 🎙️ **Registra due sorgenti audio insieme**: il tuo **microfono** e l'**audio
  di sistema** (ciò che esce da casse/cuffie, cioè le voci degli altri in call).
- ⏱️ **Nessun limite di durata**: registri finché non premi Stop.
- 📝 **Trascrive in italiano** distinguendo `Io:` da `Partecipanti:`, in una
  **conversazione cronologica reale** (le frasi dei due si alternano nell'ordine
  in cui sono state dette).
- ⚡ **Due motori di trascrizione a scelta**, selezionabili **dalla finestra**:
  - **Groq (cloud)** — velocissimo (1 ora in ~2-5 min);
  - **Locale** — privato e offline (più lento su CPU).
- 🤖 **Riepilogo AI opzionale** (DeepSeek o Claude): sintesi, punti chiave,
  decisioni, azioni da fare, domande aperte.
- 💾 Salva tutto in una cartella per riunione: audio + trascrizione + riepilogo.

---

## Come funziona (spiegazione)

### Il "trucco" dei due canali separati

L'app apre **due flussi audio contemporaneamente e indipendenti**:

1. il **microfono** → diventa l'etichetta **"Io"**;
2. l'**audio di sistema** (tramite *WASAPI loopback*, una funzione di Windows che
   cattura "ciò che il PC sta riproducendo") → diventa **"Partecipanti"**.

Tenendo i due canali su **due file separati** otteniamo la distinzione "Io vs
Partecipanti" **senza** usare modelli pesanti di riconoscimento del parlante. E
poiché i due registratori lavorano in parallelo, **anche quando parlate tutti
insieme nessuna voce viene persa**: ognuno registra la propria sorgente per
intero.

> 💡 **Usa le cuffie con microfono.** Così il microfono sente solo te (niente
> "rimbombo" delle voci altrui dalle casse), e il loopback cattura comunque
> l'audio degli altri in modo pulito. Separazione perfetta.

### Dalla registrazione al testo

Quando premi **Stop**, l'app:
1. **finalizza l'audio** su disco (così non si perde nulla);
2. **trascrive** ogni canale, con i tempi di **ogni parola**;
3. spezza il parlato in **frasi brevi** e le **intreccia per orario**, ottenendo
   la conversazione reale `Io` / `Partecipanti`;
4. (se attivo) genera il **riepilogo AI**;
5. salva tutto e **apre la cartella** dei risultati.

### Attento alla memoria (16 GB, no GPU)

L'audio viene scritto **su disco a blocchi** durante la registrazione (mai tutta
la riunione in RAM), e la trascrizione lavora a segmenti. Così funziona anche per
riunioni lunghe su un PC modesto.

---

## Requisiti

- **Windows 10 / 11**
- **Python 3.13** (in fase d'installazione spunta *"Add Python to PATH"*)
- **Git** (per clonare il progetto)
- Un **microfono** e un **dispositivo di uscita audio** (cuffie/casse) attivi
- **Connessione a Internet** se usi la trascrizione **Groq** (default) o il
  riepilogo AI. La trascrizione **Locale** funziona invece offline.

---

## Installazione passo-passo

Apri **PowerShell** e segui i passaggi (i comandi vanno dati uno alla volta).

### 1) Scarica il progetto

```powershell
git clone https://github.com/AntoniMordor/Trascrittore-AI.git
cd Trascrittore-AI
```

> In alternativa: pagina GitHub → pulsante verde **Code → Download ZIP**, estrai
> e apri PowerShell dentro la cartella.

### 2) Crea l'ambiente virtuale (consigliato)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Se PowerShell blocca l'attivazione, esegui **una volta**:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`
> e riprova.

### 3) Installa le dipendenze

```powershell
pip install -r requirements.txt
```

### 4) Configura le chiavi API (file `.env`)

Copia `.env.example` in `.env` e inserisci **solo le chiavi che ti servono**:

```
# Per la trascrizione CLOUD veloce (backend "groq", attivo di default)
GROQ_API_KEY=gsk-la-tua-chiave         # gratis su https://console.groq.com

# Per il RIEPILOGO AI opzionale (solo se lo attivi)
DEEPSEEK_API_KEY=sk-la-tua-chiave      # https://platform.deepseek.com
ANTHROPIC_API_KEY=sk-ant-la-tua-chiave # https://console.anthropic.com
```

> - Di **default** l'app trascrive con **Groq**, quindi ti serve `GROQ_API_KEY`.
>   Se preferisci stare **100% offline**, scegli **"Locale"** nella finestra (o
>   metti `backend: faster_whisper` in `config.yaml`): in quel caso nessuna
>   chiave è necessaria per trascrivere.
> - Il file `.env` contiene **segreti**: non va condiviso e **non finisce su Git**
>   (è già in `.gitignore`).

---

## Come si usa

Avvia l'app:

```powershell
python main.py
```

1. Leggi l'**avviso legale** e premi **OK**.
2. Nel menù **"Trascrizione:"** scegli il motore:
   - **☁ Groq (cloud, veloce)** — predefinito;
   - **🖥 Locale (privato, lento)**.
3. Clic su **● Avvia registrazione** → parte la cattura (vedi il timer `● REC`).
4. Svolgi la riunione (nessun limite di durata).
5. Clic su **■ Stop** → parte l'elaborazione (barra di avanzamento).
6. Alla fine si apre automaticamente la **cartella dei risultati**.

> Il menù del motore si blocca durante registrazione/elaborazione e si riattiva
> alla fine: puoi cambiarlo per la riunione successiva senza toccare nessun file.

---

## Dove finiscono i risultati

Per ogni riunione viene creata una cartella con data e ora, ad esempio:

```
output/2026-06-13_15-30/
├── audio_microfono.wav   (la tua voce, "Io")
├── audio_sistema.wav     (gli altri, "Partecipanti")
├── trascrizione.md       (la trascrizione)
└── riepilogo.md          (solo se il riepilogo AI è attivo)
```

Il file **`trascrizione.md`** contiene tre sezioni:
1. **Conversazione (ordine cronologico reale)** — `Io` e `Partecipanti`
   intrecciati nell'ordine in cui si è parlato (la parte più utile);
2. **Solo Partecipanti** — tutto ciò che hanno detto gli altri, di seguito;
3. **Solo Io** — tutto ciò che hai detto tu, di seguito.

> **Le registrazioni non vengono mai cancellate automaticamente.** Per liberare
> spazio, elimina tu le vecchie cartelle dentro `output/`.

---

## Trascrizione: Locale vs Cloud (Groq)

Scegli il motore **dal menù nella finestra** (oppure col valore predefinito
`trascrizione.backend` in `config.yaml`).

### ☁️ Groq — Cloud su GPU (predefinito)

**PRO**
- ⚡ **Velocissimo**: 1 ora di riunione in **~2-5 minuti** (dipende anche dalla
  tua velocità di upload).
- Qualità pari o superiore (`whisper-large-v3`).
- Piano **gratuito** su https://console.groq.com.

**CONTRO**
- 🌐 **L'audio viene inviato ai server di Groq**: NON è più tutto locale. Da
  valutare per riunioni riservate/aziendali.
- Richiede **Internet** e la chiave `GROQ_API_KEY`.
- Il piano gratuito ha **limiti d'uso**.

### 🖥️ faster_whisper — Locale

**PRO**
- 🔒 **Privacy totale**: l'audio non lascia mai il PC.
- 💸 **Gratis** e **offline**, senza limiti.

**CONTRO**
- 🐢 **Lento su CPU**: ~35-45 min per 1 ora (su un i5 moderno), ~18-22 min per
  30 minuti.
- Scarica un modello da ~1,6 GB la prima volta (poi resta in cache).

### 💰 Groq è gratuito?

Sì, sul **piano free**, con alcune precisazioni:
- ✅ **Nessun costo a sorpresa**: non paghi finché non aggiungi *tu* un metodo di
  pagamento e passi a un piano superiore.
- ⚠️ Ci sono **limiti d'uso** (rate limit): se li superi, Groq **blocca
  temporaneamente** le richieste invece di addebitarti.
- ⚠️ Limiti/prezzi possono cambiare: controlla su https://console.groq.com
  (*Settings → Limits* / *Billing*).

**Se raggiungi un limite non perdi nulla**: l'audio è già salvato, l'app mostra
un messaggio chiaro e puoi riprovare più tardi o passare a **Locale**.

---

## Riepilogo AI (opzionale)

Oltre alla trascrizione, l'app può generare un **riepilogo strutturato**
(sintesi, punti chiave, decisioni, action item, domande aperte) tramite AI.

È **disattivato di default** (`riepilogo.backend: nessuno`): così l'app fa solo
la trascrizione, senza costi. Per attivarlo:

1. Scegli il servizio in `config.yaml` → `riepilogo.backend`:
   - `deepseek` (modello forte: `deepseek-reasoner`), oppure
   - `claude` (modello: `claude-sonnet-4-6`).
2. Inserisci la chiave corrispondente nel file `.env` (`DEEPSEEK_API_KEY` o
   `ANTHROPIC_API_KEY`) e assicurati che l'account abbia **credito**.
3. Riavvia: alla fine di ogni riunione otterrai anche `riepilogo.md`.

> Entrambi i servizi sono **a pagamento** (a consumo). DeepSeek richiede una
> piccola ricarica su https://platform.deepseek.com. Per riunioni lunghe il testo
> viene riepilogato "a tappe" (map-reduce) per non superare i limiti del modello.
> Al servizio AI viene inviato il **testo** della trascrizione, non l'audio.

---

## Configurazione (`config.yaml`)

Puoi modificare questi valori senza toccare il codice:

| Voce | Cosa controlla | Valori utili |
|------|----------------|--------------|
| `cartella_output` | dove salvare le riunioni | es. `"output"` |
| `trascrizione.backend` | dove trascrivere | `groq` (cloud, default), `faster_whisper` (locale) |
| `trascrizione.modello_groq` | modello Groq (solo cloud) | `whisper-large-v3` (default), `whisper-large-v3-turbo` |
| `trascrizione.modello` | modello locale | `medium` (veloce), `large-v3-turbo` (default), `large-v3` (preciso) |
| `trascrizione.compute_type` | leggerezza su CPU (locale) | `int8` (default), `int8_float16`, `float32` |
| `trascrizione.lingua` | lingua della riunione | `it` |
| `trascrizione.beam_size` | velocità vs qualità (locale) | `1` (veloce, default), `5` (qualità max) |
| `trascrizione.cpu_threads` | core CPU usati (locale) | `0` (automatico, default) o un numero |
| `riepilogo.backend` | servizio del riepilogo AI | `nessuno` (default), `deepseek`, `claude` |
| `riepilogo.modello_deepseek` | modello DeepSeek | `deepseek-reasoner` (potente), `deepseek-chat` (veloce) |
| `riepilogo.modello_claude` | modello Claude | `claude-sonnet-4-6` |
| `riepilogo.caratteri_per_blocco` | soglia del map-reduce | es. `12000` |

> Il **menù nella finestra** scavalca `trascrizione.backend` solo per la sessione
> in corso; il valore in `config.yaml` resta quello predefinito all'avvio.

---

## Privacy e sicurezza

- 🔒 La trascrizione **Locale** è 100% offline: l'audio non lascia il PC.
- 🌐 La trascrizione **Groq** (default) **invia l'audio** ai server di Groq.
  Per riunioni riservate, scegli **Locale**.
- 🔑 Le chiavi API stanno solo nel file **`.env`**, che è escluso da Git e non
  viene mai pubblicato. Non condividerlo.
- 🤖 Il **riepilogo AI** invia il *testo* (non l'audio) al servizio scelto.

---

## Avviso legale

Registrare una riunione può richiedere il **consenso dei partecipanti**, e le
regole cambiano per paese e contesto aziendale. L'app mostra un promemoria
all'avvio: assicurati di avere il diritto e/o il consenso di registrare.

---

## Struttura del progetto

```
audio_capture.py     Cattura microfono + audio di sistema (loopback), scrive i WAV
transcriber.py       Interfaccia Transcriber + backend FasterWhisper (locale) e Groq (cloud)
summarizer.py        Riepilogo AI (DeepSeek o Claude) con strategia map-reduce
pipeline.py          Orchestrazione: trascrivi -> intreccia Io/Partecipanti -> riepiloga -> salva
gui.py               Finestra PySide6 (menù motore, Avvia/Stop, timer, avanzamento)
main.py              Punto di ingresso (avvia la finestra)
config.py            Caricamento di config.yaml e .env
config.yaml          Impostazioni modificabili
diagnostica_audio.py Script di verifica dei dispositivi audio (microfono + loopback)
.env.example         Modello per il file .env (chiavi API)
requirements.txt     Dipendenze Python
```

> **Architettura a plugin**: `transcriber.py` e `summarizer.py` definiscono
> interfacce comuni, così aggiungere nuovi backend (altri servizi cloud) non
> richiede di riscrivere il resto del programma.

---

## Installare/aggiornare su un altro PC

**Prima installazione** su un nuovo PC: ripeti la sezione
[Installazione](#installazione-passo-passo) (clone, ambiente virtuale,
dipendenze, `.env`). Il file `.env` **non** si scarica da Git: ricrealo a mano e
reincolla le tue chiavi.

**Aggiornare** all'ultima versione (se hai già clonato):

```powershell
git pull
```

**Pubblicare** modifiche tue (se lavori al codice):

```powershell
git add -A
git commit -m "descrizione della modifica"
git push
```

---

## Problemi comuni

- **"Impossibile trovare il dispositivo di LOOPBACK"**
  Assicurati di avere un'uscita audio (cuffie/casse) attiva e impostata come
  predefinita in *Impostazioni Windows → Sistema → Audio*. Alcune cuffie
  Bluetooth in modalità "headset/mani libere" non espongono il loopback: usa
  cuffie via jack/USB o imposta il profilo Bluetooth su "stereo".
  Puoi verificare i dispositivi con: `python diagnostica_audio.py`.

- **"Nessun microfono di default trovato"**
  Collega/abilita un microfono e impostalo come predefinito in Windows.

- **Errore Groq "limite raggiunto" o chiave non valida**
  Controlla `GROQ_API_KEY` nel `.env` e i limiti su https://console.groq.com.
  In alternativa scegli **Locale** dal menù: trascrive offline senza limiti.

- **La trascrizione locale è lenta**
  È normale su CPU senza GPU. Usa **Groq** dal menù, oppure metti il modello
  `medium` in `config.yaml`. La prima volta scarica anche il modello (~1,6 GB).

- **Il riepilogo non viene generato**
  Verifica `riepilogo.backend` in `config.yaml`, la chiave nel `.env` e il
  credito dell'account. La **trascrizione viene comunque salvata**.
