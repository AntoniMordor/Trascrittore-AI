"""
summarizer.py
=============
Prende la trascrizione (testo) e produce un RIEPILOGO strutturato in italiano
usando un modello AI. Sono disponibili DUE backend intercambiabili:

  - "deepseek" -> API DeepSeek (modello piu' forte: "deepseek-reasoner")
  - "claude"   -> API Anthropic / Claude

Si sceglie quale usare dal file config.yaml (voce "riepilogo.backend"), senza
toccare il codice.

Il riepilogo segue questo schema:
  (a) sintesi generale
  (b) punti chiave
  (c) decisioni prese
  (d) action item (azioni da fare) con eventuale responsabile
  (e) domande / temi aperti

Riunioni lunghe: se la trascrizione e' troppo grande per stare in una sola
chiamata, la spezziamo in blocchi, riepiloghiamo ciascun blocco ("map") e poi
uniamo i mini-riepiloghi in uno finale ("reduce"). Questa strategia si chiama
"map-reduce" e serve a non superare i limiti di contesto del modello.

Architettura: c'e' una classe base astratta `Riepilogatore` con TUTTA la logica
condivisa (prompt, map-reduce). I due backend (DeepSeek e Claude) devono solo
implementare il metodo `_chiama`, cioe' "come" parlare con la propria API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class ErroreRiepilogo(Exception):
    """Errore 'amichevole' da mostrare all'utente quando il riepilogo fallisce."""


# Funzione opzionale per riportare l'avanzamento alla GUI.
CallbackProgresso = Callable[[float, str], None]


# Istruzioni di sistema: definiscono il "ruolo" e il comportamento del modello.
_ISTRUZIONI_SISTEMA = (
    "Sei un assistente esperto nel sintetizzare riunioni di lavoro in italiano. "
    "Produci riepiloghi chiari, concreti e ben organizzati, senza inventare "
    "informazioni non presenti nella trascrizione. Nella trascrizione, "
    "'Io' indica l'utente che ha registrato, 'Partecipanti' indica gli altri."
)

# Schema del riepilogo finale richiesto.
_SCHEMA_RIEPILOGO = """\
Struttura la risposta in Markdown con ESATTAMENTE queste sezioni:

## Sintesi generale
(2-4 frasi che riassumono di cosa si e' parlato)

## Punti chiave
- (elenco puntato dei temi/argomenti principali)

## Decisioni prese
- (decisioni concrete; se non ce ne sono, scrivi "Nessuna decisione esplicita")

## Action item
- (azioni da fare; indica tra parentesi il responsabile se deducibile, es. "(Io)" o "(Partecipanti)"; se nessuna, scrivi "Nessuna azione individuata")

## Domande / temi aperti
- (questioni rimaste in sospeso; se nessuna, scrivi "Nessuna")
"""


class Riepilogatore(ABC):
    """
    Classe base: contiene la logica condivisa (prompt + map-reduce).
    I backend concreti implementano solo `_chiama`.
    """

    def __init__(self, caratteri_per_blocco: int = 12000) -> None:
        self.caratteri_per_blocco = max(2000, int(caratteri_per_blocco))

    @abstractmethod
    def _chiama(self, contenuto_utente: str, max_tokens: int) -> str:
        """
        Manda un messaggio al modello (con le istruzioni di sistema) e
        restituisce SOLO il testo della risposta. Da implementare nei backend.
        """
        raise NotImplementedError

    # ------------------------------------------------------------- map-reduce
    @staticmethod
    def _spezza_in_blocchi(testo: str, max_caratteri: int) -> list[str]:
        """
        Divide il testo in blocchi <= max_caratteri, tagliando alla fine di una
        riga (per non spezzare le frasi a meta').
        """
        righe = testo.splitlines(keepends=True)
        blocchi: list[str] = []
        corrente = ""
        for riga in righe:
            if len(corrente) + len(riga) > max_caratteri and corrente:
                blocchi.append(corrente)
                corrente = ""
            corrente += riga
        if corrente.strip():
            blocchi.append(corrente)
        return blocchi

    def riepiloga(
        self,
        trascrizione: str,
        progresso: CallbackProgresso | None = None,
    ) -> str:
        """
        Restituisce il riepilogo finale in Markdown.

        Se la trascrizione e' corta -> una sola chiamata.
        Se e' lunga -> map-reduce (riepiloga i blocchi, poi unisce).
        """
        trascrizione = (trascrizione or "").strip()
        if not trascrizione:
            return "_(Trascrizione vuota: nessun contenuto da riepilogare.)_"

        # Caso semplice: entra tutto in un blocco.
        if len(trascrizione) <= self.caratteri_per_blocco:
            if progresso:
                progresso(0.3, "Genero il riepilogo...")
            prompt = (
                "Ecco la trascrizione integrale di una riunione.\n\n"
                f"{trascrizione}\n\n"
                f"{_SCHEMA_RIEPILOGO}"
            )
            risultato = self._chiama(prompt, max_tokens=2000)
            if progresso:
                progresso(1.0, "Riepilogo completato.")
            return risultato

        # Caso lungo: MAP -> riepilogo parziale di ogni blocco.
        blocchi = self._spezza_in_blocchi(trascrizione, self.caratteri_per_blocco)
        riepiloghi_parziali: list[str] = []
        for i, blocco in enumerate(blocchi, start=1):
            if progresso:
                progresso(i / (len(blocchi) + 1), f"Riepilogo parziale {i}/{len(blocchi)}...")
            prompt = (
                f"Questa e' la PARTE {i} di {len(blocchi)} della trascrizione di "
                "una riunione. Riassumi in modo conciso SOLO questa parte, "
                "elencando punti chiave, eventuali decisioni e azioni emerse.\n\n"
                f"{blocco}"
            )
            riepiloghi_parziali.append(self._chiama(prompt, max_tokens=1200))

        # REDUCE -> uniamo i riepiloghi parziali in quello finale strutturato.
        if progresso:
            progresso(len(blocchi) / (len(blocchi) + 1), "Compongo il riepilogo finale...")
        unione = "\n\n".join(
            f"### Riepilogo parte {i}\n{r}" for i, r in enumerate(riepiloghi_parziali, start=1)
        )
        prompt_finale = (
            "Di seguito trovi i riepiloghi parziali delle varie parti di una "
            "stessa riunione. Uniscili in UN UNICO riepilogo coerente, senza "
            "ripetizioni.\n\n"
            f"{unione}\n\n"
            f"{_SCHEMA_RIEPILOGO}"
        )
        finale = self._chiama(prompt_finale, max_tokens=2000)
        if progresso:
            progresso(1.0, "Riepilogo completato.")
        return finale


class RiepilogatoreDeepSeek(Riepilogatore):
    """
    Backend DeepSeek. L'API di DeepSeek e' compatibile con lo standard OpenAI,
    quindi usiamo l'SDK 'openai' puntandolo al server di DeepSeek.
    Modello consigliato (piu' potente): "deepseek-reasoner".
    """

    BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key: str, modello: str = "deepseek-reasoner", caratteri_per_blocco: int = 12000) -> None:
        super().__init__(caratteri_per_blocco)
        if not api_key:
            raise ErroreRiepilogo(
                "Chiave API di DeepSeek mancante. Crea/aggiorna il file '.env' "
                "con la riga:\n  DEEPSEEK_API_KEY=la-tua-chiave\n"
                "(la ottieni su https://platform.deepseek.com)."
            )
        self.modello = modello

        # Import qui dentro per non rallentare l'avvio della GUI.
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def _chiama(self, contenuto_utente: str, max_tokens: int) -> str:
        try:
            risposta = self._client.chat.completions.create(
                model=self.modello,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": _ISTRUZIONI_SISTEMA},
                    {"role": "user", "content": contenuto_utente},
                ],
            )
        except Exception as e:
            raise ErroreRiepilogo(
                "Errore durante la chiamata all'API di DeepSeek.\n"
                f"Dettaglio tecnico: {e}\n"
                "Controlla la connessione a Internet e che la chiave API in "
                "'.env' (DEEPSEEK_API_KEY) sia valida e con credito disponibile."
            ) from e

        return (risposta.choices[0].message.content or "").strip()


class RiepilogatoreClaude(Riepilogatore):
    """
    Backend Claude (Anthropic), tramite l'SDK ufficiale 'anthropic'.
    """

    def __init__(self, api_key: str, modello: str = "claude-sonnet-4-6", caratteri_per_blocco: int = 12000) -> None:
        super().__init__(caratteri_per_blocco)
        if not api_key:
            raise ErroreRiepilogo(
                "Chiave API di Anthropic mancante. Crea/aggiorna il file '.env' "
                "con la riga:\n  ANTHROPIC_API_KEY=la-tua-chiave"
            )
        self.modello = modello

        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

    def _chiama(self, contenuto_utente: str, max_tokens: int) -> str:
        try:
            risposta = self._client.messages.create(
                model=self.modello,
                max_tokens=max_tokens,
                system=_ISTRUZIONI_SISTEMA,
                messages=[{"role": "user", "content": contenuto_utente}],
            )
        except Exception as e:
            raise ErroreRiepilogo(
                "Errore durante la chiamata all'API di Claude.\n"
                f"Dettaglio tecnico: {e}\n"
                "Controlla la connessione a Internet e che la chiave API in "
                "'.env' (ANTHROPIC_API_KEY) sia valida e con credito disponibile."
            ) from e

        parti = [b.text for b in risposta.content if getattr(b, "type", None) == "text"]
        return "\n".join(parti).strip()


def crea_riepilogatore(
    backend: str,
    deepseek_api_key: str | None,
    modello_deepseek: str,
    anthropic_api_key: str | None,
    modello_claude: str,
    caratteri_per_blocco: int,
) -> Riepilogatore:
    """
    "Fabbrica" che restituisce il riepilogatore giusto in base al backend scelto
    nella configurazione.
    """
    if backend == "deepseek":
        return RiepilogatoreDeepSeek(
            api_key=deepseek_api_key or "",
            modello=modello_deepseek,
            caratteri_per_blocco=caratteri_per_blocco,
        )
    if backend == "claude":
        return RiepilogatoreClaude(
            api_key=anthropic_api_key or "",
            modello=modello_claude,
            caratteri_per_blocco=caratteri_per_blocco,
        )
    raise ErroreRiepilogo(
        f"Backend di riepilogo non riconosciuto: '{backend}'. "
        "Valori supportati: 'deepseek', 'claude'."
    )
