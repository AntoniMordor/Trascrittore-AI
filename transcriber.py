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
    ) -> None:
        self.nome_modello = modello
        self.compute_type = compute_type
        self.lingua = lingua
        self._modello = None  # caricato "pigramente" alla prima trascrizione

    def _assicura_modello(self) -> None:
        """Carica il modello Whisper se non e' gia' in memoria."""
        if self._modello is not None:
            return
        # Import qui dentro: cosi' avviare la GUI resta veloce e l'import pesante
        # avviene solo quando serve davvero trascrivere.
        from faster_whisper import WhisperModel

        # device="cpu" perche' assumiamo nessuna GPU dedicata.
        self._modello = WhisperModel(
            self.nome_modello,
            device="cpu",
            compute_type=self.compute_type,
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
        #  - language=it       -> lingua forzata a italiano
        #  - vad_filter=True   -> salta i silenzi (utile per riunioni lunghe e
        #                         per non "inventare" testo nei silenzi)
        #  - il file viene letto a segmenti: NON carica tutto in RAM.
        segmenti_iter, info = self._modello.transcribe(
            str(percorso_audio),
            language=self.lingua,
            vad_filter=True,
            beam_size=5,
        )

        # Durata totale stimata: ci serve solo per la barra di avanzamento.
        durata_totale = float(getattr(info, "duration", 0.0)) or 0.0

        risultati: list[SegmentoTrascrizione] = []
        for seg in segmenti_iter:
            testo = (seg.text or "").strip()
            # Scartiamo i segmenti vuoti o fatti SOLO di punteggiatura/simboli
            # (es. un "." isolato): di solito sono rumore o piccole
            # "allucinazioni" di Whisper sui silenzi, non vero parlato.
            if not any(carattere.isalnum() for carattere in testo):
                continue
            risultati.append(
                SegmentoTrascrizione(
                    inizio=float(seg.start),
                    fine=float(seg.end),
                    testo=testo,
                    parlante=parlante,
                )
            )
            # Aggiorna l'avanzamento in base a quanto audio abbiamo coperto.
            if progresso and durata_totale > 0:
                frazione = min(seg.end / durata_totale, 1.0)
                progresso(frazione, f"Trascrivo il canale '{parlante}'...")

        if progresso:
            progresso(1.0, f"Canale '{parlante}' completato.")

        return risultati


def crea_transcriber(
    backend: str,
    modello: str,
    compute_type: str,
    lingua: str,
) -> Transcriber:
    """
    "Fabbrica" che restituisce il trascrittore giusto in base al backend scelto
    nella configurazione. Oggi conosce solo "faster_whisper"; domani potrai
    aggiungere qui i backend cloud.
    """
    if backend == "faster_whisper":
        return FasterWhisperTranscriber(modello=modello, compute_type=compute_type, lingua=lingua)

    raise ValueError(
        f"Backend di trascrizione non riconosciuto: '{backend}'. "
        "Valori supportati al momento: 'faster_whisper'."
    )
