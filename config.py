"""
config.py
=========
Carica la configurazione dell'applicazione da due fonti:

  1) "config.yaml"  -> impostazioni non segrete (modelli, cartella di output...).
  2) ".env"         -> segreti (la chiave API di Anthropic).

Espone una semplice classe `Config` con tutti i valori gia' pronti all'uso,
in modo che il resto del programma non debba sapere "da dove" arrivano.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


# Cartella in cui si trova questo file: ci serve per trovare config.yaml e .env
# anche se l'app viene lanciata da un'altra cartella.
RADICE_PROGETTO = Path(__file__).resolve().parent


@dataclass
class ConfigTrascrizione:
    """Impostazioni per la trascrizione (Whisper)."""
    backend: str = "faster_whisper"
    modello: str = "large-v3-turbo"
    compute_type: str = "int8"
    lingua: str = "it"


@dataclass
class ConfigRiepilogo:
    """Impostazioni per il riepilogo AI (Claude o DeepSeek)."""
    backend: str = "deepseek"
    modello_deepseek: str = "deepseek-reasoner"
    modello_claude: str = "claude-sonnet-4-6"
    caratteri_per_blocco: int = 12000


@dataclass
class Config:
    """
    Contenitore di tutta la configurazione dell'app.

    Usa `Config.carica()` per costruirlo leggendo config.yaml e .env.
    """
    cartella_output: Path = field(default_factory=lambda: RADICE_PROGETTO / "output")
    trascrizione: ConfigTrascrizione = field(default_factory=ConfigTrascrizione)
    riepilogo: ConfigRiepilogo = field(default_factory=ConfigRiepilogo)

    # Le chiavi API NON hanno un valore di default: se mancano, lo gestiamo a parte.
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None

    @staticmethod
    def carica(percorso_yaml: Path | None = None) -> "Config":
        """
        Legge config.yaml e .env e restituisce un oggetto Config pronto.

        Se config.yaml non esiste, usa i valori di default (cosi' l'app parte
        comunque). La chiave API viene letta dal file .env.
        """
        # 1) Carica le variabili del file .env nell'ambiente del processo.
        load_dotenv(RADICE_PROGETTO / ".env")

        # 2) Legge config.yaml (se presente).
        percorso_yaml = percorso_yaml or (RADICE_PROGETTO / "config.yaml")
        dati: dict = {}
        if percorso_yaml.exists():
            with open(percorso_yaml, "r", encoding="utf-8") as f:
                dati = yaml.safe_load(f) or {}

        # 3) Costruisce le sotto-configurazioni, sezione per sezione.
        sez_trascr = dati.get("trascrizione", {}) or {}
        trascrizione = ConfigTrascrizione(
            backend=sez_trascr.get("backend", "faster_whisper"),
            modello=sez_trascr.get("modello", "large-v3-turbo"),
            compute_type=sez_trascr.get("compute_type", "int8"),
            lingua=sez_trascr.get("lingua", "it"),
        )

        sez_riep = dati.get("riepilogo", {}) or {}
        riepilogo = ConfigRiepilogo(
            backend=sez_riep.get("backend", "deepseek"),
            modello_deepseek=sez_riep.get("modello_deepseek", "deepseek-reasoner"),
            modello_claude=sez_riep.get("modello_claude", "claude-sonnet-4-6"),
            caratteri_per_blocco=int(sez_riep.get("caratteri_per_blocco", 12000)),
        )

        # La cartella di output puo' essere relativa (alla radice del progetto)
        # oppure assoluta.
        cartella = dati.get("cartella_output", "output")
        cartella_path = Path(cartella)
        if not cartella_path.is_absolute():
            cartella_path = RADICE_PROGETTO / cartella_path

        return Config(
            cartella_output=cartella_path,
            trascrizione=trascrizione,
            riepilogo=riepilogo,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        )

    def chiave_riepilogo_presente(self) -> bool:
        """
        True se la chiave API del backend di riepilogo scelto e' presente e
        non e' il testo segnaposto di esempio.
        """
        if self.riepilogo.backend == "deepseek":
            chiave = self.deepseek_api_key
            return bool(chiave) and not chiave.startswith("sk-incolla")
        # default: claude
        chiave = self.anthropic_api_key
        return bool(chiave) and not chiave.startswith("sk-ant-incolla")
