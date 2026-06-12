"""
pipeline.py
===========
Orchestra tutto cio' che avviene DOPO lo Stop della registrazione:

    file audio  ->  trascrizione per canale  ->  fusione cronologica
                ->  salvataggio trascrizione  ->  riepilogo AI  ->  salvataggio

Principio di ROBUSTEZZA (richiesto): salviamo le cose nell'ordine giusto e
proteggiamo ogni fase. Se la trascrizione fallisce, l'audio resta. Se il
riepilogo fallisce, la trascrizione resta. Non perdiamo MAI il lavoro gia' fatto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import Config
from summarizer import crea_riepilogatore
from transcriber import SegmentoTrascrizione, crea_transcriber

# Etichette dei due parlanti.
ETICHETTA_IO = "Io"
ETICHETTA_PARTECIPANTI = "Partecipanti"

# Funzione opzionale per riportare l'avanzamento alla GUI (frazione, messaggio).
CallbackProgresso = Callable[[float, str], None]


@dataclass
class RisultatoPipeline:
    """Riepilogo di cosa e' stato prodotto, da mostrare alla fine."""
    cartella: Path
    file_trascrizione: Path | None = None
    file_riepilogo: Path | None = None
    errore_trascrizione: str | None = None
    errore_riepilogo: str | None = None


def _formatta_tempo(secondi: float) -> str:
    """Trasforma 75.0 -> '01:15' (minuti:secondi), comodo nei timestamp."""
    secondi = max(0, int(secondi))
    return f"{secondi // 60:02d}:{secondi % 60:02d}"


def fondi_segmenti(
    seg_io: list[SegmentoTrascrizione],
    seg_part: list[SegmentoTrascrizione],
) -> list[SegmentoTrascrizione]:
    """
    Unisce i segmenti dei due canali in UNA lista ordinata nel tempo.
    Cosi' la trascrizione finale legge l'andamento reale della conversazione,
    alternando "Io" e "Partecipanti".
    """
    tutti = list(seg_io) + list(seg_part)
    tutti.sort(key=lambda s: s.inizio)
    return tutti


def crea_cartella_riunione(cartella_base: Path) -> Path:
    """
    Crea (se non esiste) la cartella della singola riunione, con data e ora:
    es. output/2026-06-12_15-30/
    """
    nome = datetime.now().strftime("%Y-%m-%d_%H-%M")
    cartella = Path(cartella_base) / nome
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def _blocco_segmenti(segmenti: list[SegmentoTrascrizione]) -> list[str]:
    """Trasforma una lista di segmenti in righe Markdown con timestamp e parlante."""
    if not segmenti:
        return ["_(Nessun parlato riconosciuto.)_", ""]
    righe: list[str] = []
    for s in segmenti:
        righe.append(f"**[{_formatta_tempo(s.inizio)}] {s.parlante}:** {s.testo}")
        righe.append("")  # riga vuota per leggibilita'
    return righe


def _scrivi_trascrizione_md(percorso: Path, segmenti: list[SegmentoTrascrizione]) -> None:
    """
    Scrive la trascrizione in Markdown in TRE sezioni:
      1) Conversazione (ordine cronologico reale) -> Io e Partecipanti intrecciati
         nell'ordine in cui si e' parlato davvero (la parte piu' utile).
      2) Solo Partecipanti -> tutto cio' che hanno detto gli altri, di seguito.
      3) Solo Io           -> tutto cio' che ho detto io, di seguito.

    'segmenti' arriva gia' ordinato cronologicamente.
    """
    solo_part = [s for s in segmenti if s.parlante == ETICHETTA_PARTECIPANTI]
    solo_io = [s for s in segmenti if s.parlante == ETICHETTA_IO]

    righe: list[str] = ["# Trascrizione della riunione", ""]

    righe.append("## Conversazione (ordine cronologico reale)")
    righe.append("")
    righe.extend(_blocco_segmenti(segmenti))

    righe.append("---")
    righe.append("")
    righe.append("## Solo Partecipanti")
    righe.append("")
    righe.extend(_blocco_segmenti(solo_part))

    righe.append("---")
    righe.append("")
    righe.append("## Solo Io")
    righe.append("")
    righe.extend(_blocco_segmenti(solo_io))

    percorso.write_text("\n".join(righe), encoding="utf-8")


def segmenti_in_testo(segmenti: list[SegmentoTrascrizione]) -> str:
    """Versione 'piatta' della trascrizione, da mandare a Claude per il riepilogo."""
    return "\n".join(f"[{_formatta_tempo(s.inizio)}] {s.parlante}: {s.testo}" for s in segmenti)


def esegui_pipeline(
    config: Config,
    cartella_riunione: Path,
    file_microfono: Path,
    file_sistema: Path,
    progresso: CallbackProgresso | None = None,
) -> RisultatoPipeline:
    """
    Esegue tutte le fasi dopo lo Stop. Riceve:
      - config: la configurazione (modelli, chiave API, ecc.)
      - cartella_riunione: dove salvare i risultati (gia' creata)
      - file_microfono / file_sistema: i due WAV registrati

    Restituisce un RisultatoPipeline con i percorsi prodotti ed eventuali
    errori (senza mai sollevare eccezioni che farebbero perdere l'audio).
    """
    risultato = RisultatoPipeline(cartella=cartella_riunione)

    def avanza(frazione: float, messaggio: str) -> None:
        if progresso:
            progresso(frazione, messaggio)

    # ----------------------------- FASE 1: TRASCRIZIONE -----------------------
    segmenti_fusi: list[SegmentoTrascrizione] = []
    try:
        avanza(0.05, "Carico il modello di trascrizione...")
        transcriber = crea_transcriber(
            backend=config.trascrizione.backend,
            modello=config.trascrizione.modello,
            compute_type=config.trascrizione.compute_type,
            lingua=config.trascrizione.lingua,
        )

        # Canale microfono -> "Io". Mappiamo l'avanzamento in 0.10 - 0.50.
        def prog_io(frac: float, msg: str) -> None:
            avanza(0.10 + 0.40 * frac, msg)

        seg_io = transcriber.trascrivi(file_microfono, ETICHETTA_IO, progresso=prog_io)

        # Canale sistema -> "Partecipanti". Avanzamento in 0.50 - 0.85.
        def prog_part(frac: float, msg: str) -> None:
            avanza(0.50 + 0.35 * frac, msg)

        seg_part = transcriber.trascrivi(file_sistema, ETICHETTA_PARTECIPANTI, progresso=prog_part)

        # Fusione cronologica dei due canali.
        avanza(0.86, "Unisco i due canali in ordine cronologico...")
        segmenti_fusi = fondi_segmenti(seg_io, seg_part)

        # Salviamo SUBITO la trascrizione (prima del riepilogo): se il
        # riepilogo fallira', la trascrizione e' comunque al sicuro.
        file_trascr = cartella_riunione / "trascrizione.md"
        _scrivi_trascrizione_md(file_trascr, segmenti_fusi)
        risultato.file_trascrizione = file_trascr
        avanza(0.88, "Trascrizione salvata.")

    except Exception as e:
        # La trascrizione e' fallita: l'audio grezzo resta comunque su disco.
        risultato.errore_trascrizione = str(e)
        return risultato  # senza trascrizione non ha senso fare il riepilogo

    # ----------------------------- FASE 2: RIEPILOGO --------------------------
    # Se il riepilogo AI e' disattivato ("nessuno"), ci fermiamo qui: la
    # trascrizione e' gia' salvata. Nessun errore, e' una scelta voluta.
    if config.riepilogo.backend in ("nessuno", "none", ""):
        avanza(1.0, "Fatto! Trascrizione salvata (riepilogo AI disattivato).")
        return risultato

    # Se la chiave API del backend scelto manca, saltiamo il riepilogo ma
    # teniamo la trascrizione (gia' salvata).
    if not config.chiave_riepilogo_presente():
        nome_chiave = (
            "DEEPSEEK_API_KEY" if config.riepilogo.backend == "deepseek" else "ANTHROPIC_API_KEY"
        )
        risultato.errore_riepilogo = (
            f"Chiave API mancante ({nome_chiave}): riepilogo saltato. "
            "La trascrizione e' stata salvata correttamente. "
            f"Aggiungi la chiave nel file '.env' per ottenere anche il riepilogo."
        )
        return risultato

    try:
        avanza(0.90, f"Genero il riepilogo con {config.riepilogo.backend}...")
        riepilogatore = crea_riepilogatore(
            backend=config.riepilogo.backend,
            deepseek_api_key=config.deepseek_api_key,
            modello_deepseek=config.riepilogo.modello_deepseek,
            anthropic_api_key=config.anthropic_api_key,
            modello_claude=config.riepilogo.modello_claude,
            caratteri_per_blocco=config.riepilogo.caratteri_per_blocco,
        )
        testo_trascr = segmenti_in_testo(segmenti_fusi)

        def prog_riep(frac: float, msg: str) -> None:
            avanza(0.90 + 0.10 * frac, msg)

        riepilogo = riepilogatore.riepiloga(testo_trascr, progresso=prog_riep)

        file_riep = cartella_riunione / "riepilogo.md"
        file_riep.write_text(riepilogo, encoding="utf-8")
        risultato.file_riepilogo = file_riep
        avanza(1.0, "Fatto! Riepilogo salvato.")

    except Exception as e:
        # Il riepilogo e' fallito (es. ErroreRiepilogo, rete, ecc.), ma la
        # trascrizione resta salvata: non perdiamo nulla.
        risultato.errore_riepilogo = str(e)

    return risultato
