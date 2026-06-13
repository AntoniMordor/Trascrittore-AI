"""
transcriber.py
==============
Si occupa di trasformare un file audio (WAV) in TESTO con i tempi (timestamp).

Due cose importanti:

  1) "Transcriber" e' una INTERFACCIA (una classe astratta). Definisce solo
     COSA deve fare un trascrittore, non COME. Cosi' domani potrai scrivere un
     backend cloud (es. AssemblyAI o Deepgram) che rispetta la stessa
     interfaccia, e il resto del programma non cambiera' di una riga.

  2) "FasterWhisperTranscriber" e' l'implementazione LOCALE (offline, gratis)
     basata su faster-whisper. Gira su CPU con quantizzazione int8 e converte
     internamente l'audio a 16 kHz mono (non dobbiamo farlo noi a mano).
"""

from __future__ import annotations

import os

# Disattiviamo il backend di download "Xet" di HuggingFace PRIMA di importare
# faster-whisper. Su Windows, in alcune reti, Xet si blocca a 0 byte mentre
# scarica il file grosso del modello. Disattivandolo si torna al download
# HTTPS classico, piu' affidabile. (setdefault: non sovrascrive se l'hai gia'
# impostato tu manualmente.)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class SegmentoTrascrizione:
    """
    Un pezzo di trascrizione con i suoi tempi.

    Attributi:
        inizio: secondo di inizio (dall'inizio dell'audio).
        fine:   secondo di fine.
        testo:  il testo riconosciuto.
        parlante: chi parla, "Io" oppure "Partecipanti".
    """
    inizio: float
    fine: float
    testo: str
    parlante: str = ""


# Tipo di una funzione opzionale per riportare l'avanzamento (0.0 - 1.0)
# e un messaggio. Usata dalla GUI per la barra di stato.
CallbackProgresso = Callable[[float, str], None]


class Transcriber(ABC):
    """
    Interfaccia comune a tutti i trascrittori (locali o cloud).

    Chi la implementa deve fornire il metodo `trascrivi`.
    """

    @abstractmethod
    def trascrivi(
        self,
        percorso_audio: Path,
        parlante: str,
        progresso: CallbackProgresso | None = None,
    ) -> list[SegmentoTrascrizione]:
        """
        Trascrive UN file audio e restituisce la lista dei segmenti, gia'
        etichettati con il nome del `parlante` indicato.
        """
        raise NotImplementedError


class FasterWhisperTranscriber(Transcriber):
    """
    Implementazione locale con faster-whisper.

    Il modello viene caricato una sola volta (la prima volta che serve) e poi
    riusato: caricarlo e' l'operazione piu' lenta, quindi evitiamo di rifarlo.
    """

    def __init__(
        self,
        modello: str = "large-v3-turbo",
        compute_type: str = "int8",
        lingua: str = "it",
        beam_size: int = 1,
        cpu_threads: int = 0,
    ) -> None:
        self.nome_modello = modello
        self.compute_type = compute_type
        self.lingua = lingua
        self.beam_size = max(1, int(beam_size))
        # cpu_threads = 0 -> automatico: usiamo tutti i core logici del PC.
        self.cpu_threads = int(cpu_threads) if cpu_threads and cpu_threads > 0 else (os.cpu_count() or 0)
        self._modello = None  # caricato "pigramente" alla prima trascrizione

    def _assicura_modello(self) -> None:
        """Carica il modello Whisper se non e' gia' in memoria."""
        if self._modello is not None:
            return
        # Import qui dentro: cosi' avviare la GUI resta veloce e l'import pesante
        # avviene solo quando serve davvero trascrivere.
        from faster_whisper import WhisperModel

        # device="cpu" perche' assumiamo nessuna GPU dedicata.
        # cpu_threads: piu' core usiamo, piu' veloce e' la trascrizione.
        self._modello = WhisperModel(
            self.nome_modello,
            device="cpu",
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )

    def trascrivi(
        self,
        percorso_audio: Path,
        parlante: str,
        progresso: CallbackProgresso | None = None,
    ) -> list[SegmentoTrascrizione]:
        percorso_audio = Path(percorso_audio)

        # Se il file non esiste o e' vuoto, restituiamo lista vuota (robustezza:
        # magari un canale non ha registrato nulla).
        if not percorso_audio.exists() or percorso_audio.stat().st_size == 0:
            return []

        self._assicura_modello()
        assert self._modello is not None

        if progresso:
            progresso(0.0, f"Trascrivo il canale '{parlante}'...")

        # faster-whisper:
        #  - language=it          -> lingua forzata a italiano
        #  - vad_filter=True      -> salta i silenzi (utile per riunioni lunghe)
        #  - word_timestamps=True -> tempo di OGNI parola: ci serve per spezzare
        #                            il parlato in frasi brevi con orario preciso,
        #                            cosi' l'unione dei due canali risulta una
        #                            conversazione realmente intrecciata.
        #  - il file viene letto a segmenti: NON carica tutto in RAM.
        segmenti_iter, info = self._modello.transcribe(
            str(percorso_audio),
            language=self.lingua,
            vad_filter=True,
            beam_size=self.beam_size,
            word_timestamps=True,
        )

        # Durata totale stimata: ci serve solo per la barra di avanzamento.
        durata_totale = float(getattr(info, "duration", 0.0)) or 0.0

        risultati: list[SegmentoTrascrizione] = []
        for seg in segmenti_iter:
            # Spezziamo il segmento in frasi brevi usando i tempi delle parole.
            risultati.extend(_spezza_in_frasi(seg, parlante))
            # Aggiorna l'avanzamento in base a quanto audio abbiamo coperto.
            if progresso and durata_totale > 0:
                frazione = min(seg.end / durata_totale, 1.0)
                progresso(frazione, f"Trascrivo il canale '{parlante}'...")

        if progresso:
            progresso(1.0, f"Canale '{parlante}' completato.")

        return risultati


class GroqTranscriber(Transcriber):
    """
    Implementazione CLOUD tramite Groq (GPU): trascrive molto piu' velocemente
    del locale (1 ora di riunione in ~1-2 minuti), ma INVIA l'audio ai server di
    Groq (vedi avvertenze privacy nel README).

    L'API di Groq e' compatibile con lo standard OpenAI, quindi riusiamo l'SDK
    'openai' puntandolo al server di Groq.

    Gestione riunioni lunghe: Groq ha un limite sulla dimensione del file. Per
    questo convertiamo l'audio a 16 kHz mono e lo dividiamo in BLOCCHI da pochi
    minuti, trascriviamo ogni blocco e ricuciamo i tempi (offset). Cosi' funziona
    con riunioni di qualsiasi durata.
    """

    BASE_URL = "https://api.groq.com/openai/v1"
    SECONDI_PER_BLOCCO = 480  # 8 minuti -> ~15 MB a 16 kHz mono (sotto i limiti Groq)

    def __init__(self, api_key: str, modello: str = "whisper-large-v3", lingua: str = "it") -> None:
        if not api_key:
            raise RuntimeError(
                "Chiave API di Groq mancante. Crea/aggiorna il file '.env' con la "
                "riga:\n  GROQ_API_KEY=la-tua-chiave\n"
                "(la ottieni gratis su https://console.groq.com)."
            )
        self.modello = modello
        self.lingua = lingua

        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def trascrivi(
        self,
        percorso_audio: Path,
        parlante: str,
        progresso: CallbackProgresso | None = None,
    ) -> list[SegmentoTrascrizione]:
        import tempfile
        import wave

        import numpy as np

        percorso_audio = Path(percorso_audio)
        if not percorso_audio.exists() or percorso_audio.stat().st_size == 0:
            return []

        if progresso:
            progresso(0.0, f"Preparo l'audio del canale '{parlante}' per Groq...")

        # Decodifica + ricampiona a 16 kHz mono (faster-whisper espone questa
        # utilita', che usa PyAV internamente). Restituisce un array float32.
        from faster_whisper.audio import decode_audio

        audio = decode_audio(str(percorso_audio), sampling_rate=16000)

        campioni_per_blocco = self.SECONDI_PER_BLOCCO * 16000
        n_blocchi = max(1, math.ceil(len(audio) / campioni_per_blocco))
        risultati: list[SegmentoTrascrizione] = []

        for i in range(n_blocchi):
            inizio_camp = i * campioni_per_blocco
            blocco = audio[inizio_camp: inizio_camp + campioni_per_blocco]
            if blocco.size == 0:
                continue
            offset = inizio_camp / 16000.0  # secondi da cui parte questo blocco

            # Scriviamo il blocco in un WAV temporaneo 16 kHz mono 16-bit.
            pcm16 = (np.clip(blocco, -1.0, 1.0) * 32767.0).astype("<i2")
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            try:
                with wave.open(tmp.name, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(pcm16.tobytes())

                # Chiamata a Groq con timestamp parola-per-parola.
                try:
                    with open(tmp.name, "rb") as f:
                        risposta = self._client.audio.transcriptions.create(
                            file=f,
                            model=self.modello,
                            language=self.lingua,
                            response_format="verbose_json",
                            timestamp_granularities=["word"],
                        )
                except Exception as e:
                    raise RuntimeError(
                        f"Errore Groq durante la trascrizione (canale '{parlante}'): {e}\n"
                        "Controlla la chiave GROQ_API_KEY, la connessione a Internet "
                        "e i limiti del piano gratuito."
                    ) from e

                parole = getattr(risposta, "words", None) or []
                tuple_parole: list[tuple[str, float, float]] = []
                for p in parole:
                    testo = p.get("word") if isinstance(p, dict) else getattr(p, "word", "")
                    ini = p.get("start") if isinstance(p, dict) else getattr(p, "start", 0.0)
                    fin = p.get("end") if isinstance(p, dict) else getattr(p, "end", 0.0)
                    tuple_parole.append((testo, float(ini) + offset, float(fin) + offset))

                if tuple_parole:
                    # Le parole di Groq NON includono lo spazio -> separatore " ".
                    risultati.extend(_frasi_da_parole(tuple_parole, parlante, separatore=" "))
                else:
                    # Nessun timestamp parola: ripieghiamo sul testo intero del blocco.
                    testo = (getattr(risposta, "text", "") or "").strip()
                    if not _e_spazzatura(testo):
                        durata_blocco = len(blocco) / 16000.0
                        risultati.append(
                            SegmentoTrascrizione(offset, offset + durata_blocco, testo, parlante)
                        )
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

            if progresso:
                progresso((i + 1) / n_blocchi, f"Trascrivo '{parlante}' (cloud Groq) {i + 1}/{n_blocchi}...")

        if progresso:
            progresso(1.0, f"Canale '{parlante}' completato (Groq).")

        return risultati


def _e_spazzatura(testo: str) -> bool:
    """True se il testo e' vuoto o fatto solo di punteggiatura/simboli/rumore."""
    return not any(carattere.isalnum() for carattere in testo)


def _frasi_da_parole(
    parole: list[tuple[str, float, float]],
    parlante: str,
    separatore: str,
) -> list[SegmentoTrascrizione]:
    """
    Data una lista di parole (testo, inizio, fine), le raggruppa in FRASI BREVI.
    Si apre una nuova frase quando:
      - c'e' una pausa evidente tra due parole (> SOGLIA_PAUSA secondi), oppure
      - la parola precedente chiude una frase (finisce con . ? ! ...).
    Cosi' l'unione dei due canali (microfono e sistema) risulta una
    conversazione realmente intrecciata nel tempo, e non due blocchi separati.

    'separatore' e' la stringa con cui unire le parole: "" per faster-whisper
    (le sue parole includono gia' lo spazio iniziale), " " per Groq.
    """
    SOGLIA_PAUSA = 0.8  # secondi di silenzio tra parole per "andare a capo"

    frasi: list[SegmentoTrascrizione] = []
    buffer: list[tuple[str, float, float]] = []

    def _chiudi_frase() -> None:
        if not buffer:
            return
        testo = separatore.join(t for t, _, _ in buffer).strip()
        if not _e_spazzatura(testo):
            frasi.append(
                SegmentoTrascrizione(
                    inizio=float(buffer[0][1]),
                    fine=float(buffer[-1][2]),
                    testo=testo,
                    parlante=parlante,
                )
            )

    for testo_parola, inizio, fine in parole:
        if buffer:
            pausa = float(inizio) - float(buffer[-1][2])
            chiude_frase = buffer[-1][0].strip().endswith((".", "?", "!", "…"))
            if pausa > SOGLIA_PAUSA or chiude_frase:
                _chiudi_frase()
                buffer = []
        buffer.append((testo_parola, inizio, fine))
    _chiudi_frase()

    return frasi


def _spezza_in_frasi(segmento, parlante: str) -> list[SegmentoTrascrizione]:
    """
    Versione per faster-whisper: estrae le parole (con i loro tempi) da un
    segmento e le passa a _frasi_da_parole. Se mancano i tempi parola-per-parola,
    usa il segmento intero come unica frase (sicurezza).
    """
    parole = getattr(segmento, "words", None)
    if not parole:
        testo = (segmento.text or "").strip()
        if _e_spazzatura(testo):
            return []
        return [SegmentoTrascrizione(float(segmento.start), float(segmento.end), testo, parlante)]

    # Le parole di faster-whisper includono gia' lo spazio iniziale -> separatore "".
    tuple_parole = [(p.word, float(p.start), float(p.end)) for p in parole]
    return _frasi_da_parole(tuple_parole, parlante, separatore="")


def crea_transcriber(
    backend: str,
    modello: str,
    compute_type: str,
    lingua: str,
    beam_size: int = 1,
    cpu_threads: int = 0,
    groq_api_key: str | None = None,
    modello_groq: str = "whisper-large-v3",
) -> Transcriber:
    """
    "Fabbrica" che restituisce il trascrittore giusto in base al backend scelto
    nella configurazione:
      - "faster_whisper" -> locale, offline, gratis (lento su CPU)
      - "groq"           -> cloud su GPU, velocissimo (invia l'audio a Groq)
    """
    if backend == "faster_whisper":
        return FasterWhisperTranscriber(
            modello=modello,
            compute_type=compute_type,
            lingua=lingua,
            beam_size=beam_size,
            cpu_threads=cpu_threads,
        )
    if backend == "groq":
        return GroqTranscriber(
            api_key=groq_api_key or "",
            modello=modello_groq,
            lingua=lingua,
        )

    raise ValueError(
        f"Backend di trascrizione non riconosciuto: '{backend}'. "
        "Valori supportati: 'faster_whisper', 'groq'."
    )
