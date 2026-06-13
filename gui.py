"""
gui.py
======
Finestra desktop minimale (PySide6 / Qt) che lega tutto insieme:

  - un grande pulsante AVVIA / STOP
  - un indicatore "● REC" con un timer (tempo trascorso)
  - una barra di avanzamento + barra di stato (registrazione -> trascrizione
    -> riepilogo)
  - all'avvio mostra l'avviso legale sul consenso alla registrazione
  - alla fine apre la cartella con i risultati

Punto importante per la REATTIVITA':
  La registrazione audio gira gia' in callback su thread interni di PyAudio.
  L'elaborazione finale (trascrizione + riepilogo), che e' lenta, viene eseguita
  in un THREAD separato (QThread) cosi' la finestra non si "congela".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_capture import ErroreAudio, RegistratoreAudio
from config import Config
from pipeline import RisultatoPipeline, crea_cartella_riunione, esegui_pipeline


class WorkerElaborazione(QThread):
    """
    Thread che esegue la pipeline pesante (trascrizione + riepilogo) senza
    bloccare la finestra. Comunica con la GUI tramite "segnali" Qt.
    """

    # Segnali: (frazione 0-1, messaggio) per la barra; e il risultato finale.
    progresso = Signal(float, str)
    finito = Signal(object)  # emette un RisultatoPipeline

    def __init__(self, config: Config, cartella: Path, file_mic: Path, file_sys: Path) -> None:
        super().__init__()
        self._config = config
        self._cartella = cartella
        self._file_mic = file_mic
        self._file_sys = file_sys

    def run(self) -> None:
        def cb(frac: float, msg: str) -> None:
            # Inoltra l'avanzamento alla GUI in modo thread-safe (via segnale).
            self.progresso.emit(frac, msg)

        risultato = esegui_pipeline(
            self._config,
            self._cartella,
            self._file_mic,
            self._file_sys,
            progresso=cb,
        )
        self.finito.emit(risultato)


class FinestraPrincipale(QWidget):
    """La finestra unica dell'applicazione."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

        self._registratore: RegistratoreAudio | None = None
        self._cartella_corrente: Path | None = None
        self._worker: WorkerElaborazione | None = None
        self._secondi_trascorsi = 0
        self._in_registrazione = False

        self._costruisci_interfaccia()

        # Timer che aggiorna il cronometro ogni secondo durante la registrazione.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._aggiorna_cronometro)

    # ------------------------------------------------------------- interfaccia
    def _costruisci_interfaccia(self) -> None:
        self.setWindowTitle("Trascrittore AI — Riunioni")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Indicatore REC + cronometro.
        self.etichetta_rec = QLabel("Pronto")
        self.etichetta_rec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etichetta_rec.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(self.etichetta_rec)

        # Selettore del motore di trascrizione (Groq cloud vs Locale).
        riga_backend = QHBoxLayout()
        etichetta_backend = QLabel("Trascrizione:")
        self.combo_backend = QComboBox()
        # Il testo e' cio' che vede l'utente; il "dato" e' il valore tecnico.
        self.combo_backend.addItem("☁ Groq (cloud, veloce)", "groq")
        self.combo_backend.addItem("🖥 Locale (privato, lento)", "faster_whisper")
        # Preseleziona il backend indicato nella configurazione (di default: groq).
        indice = self.combo_backend.findData(self.config.trascrizione.backend)
        if indice >= 0:
            self.combo_backend.setCurrentIndex(indice)
        riga_backend.addWidget(etichetta_backend)
        riga_backend.addWidget(self.combo_backend, stretch=1)
        layout.addLayout(riga_backend)

        # Grande pulsante Avvia / Stop.
        self.pulsante = QPushButton("● Avvia registrazione")
        self.pulsante.setMinimumHeight(64)
        self.pulsante.setStyleSheet("font-size: 18px;")
        self.pulsante.clicked.connect(self._click_pulsante)
        layout.addWidget(self.pulsante)

        # Barra di avanzamento (usata durante l'elaborazione finale).
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self.barra.setVisible(False)
        layout.addWidget(self.barra)

        # Barra di stato testuale.
        self.etichetta_stato = QLabel("")
        self.etichetta_stato.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.etichetta_stato.setWordWrap(True)
        self.etichetta_stato.setStyleSheet("color: #555;")
        layout.addWidget(self.etichetta_stato)

    # ----------------------------------------------------------- avviso legale
    def mostra_avviso_legale(self) -> None:
        """Promemoria sul consenso alla registrazione, mostrato all'avvio."""
        QMessageBox.information(
            self,
            "Avviso importante",
            "Registrare una riunione puo' richiedere il CONSENSO dei "
            "partecipanti, e le regole cambiano a seconda del paese e del "
            "contesto aziendale.\n\n"
            "Assicurati di avere il diritto e/o il consenso di registrare prima "
            "di avviare.",
        )

    # ----------------------------------------------------------- gestione click
    def _click_pulsante(self) -> None:
        if not self._in_registrazione:
            self._avvia_registrazione()
        else:
            self._ferma_e_elabora()

    def _avvia_registrazione(self) -> None:
        """Crea la cartella della riunione e avvia la cattura audio."""
        try:
            self._cartella_corrente = crea_cartella_riunione(self.config.cartella_output)
            self._registratore = RegistratoreAudio(self._cartella_corrente)
            self._registratore.avvia()
        except ErroreAudio as e:
            QMessageBox.critical(self, "Impossibile registrare", str(e))
            self._registratore = None
            self._cartella_corrente = None
            return

        # Aggiorna lo stato dell'interfaccia.
        self._in_registrazione = True
        self._secondi_trascorsi = 0
        # Blocchiamo la scelta del backend mentre si registra/elabora.
        self.combo_backend.setEnabled(False)
        self.barra.setVisible(False)
        self.etichetta_stato.setText("Registrazione in corso (microfono + audio di sistema)...")
        self.pulsante.setText("■ Stop")
        self.etichetta_rec.setText("● REC  00:00:00")
        self.etichetta_rec.setStyleSheet("font-size: 22px; font-weight: bold; color: #c0392b;")
        self._timer.start()

    def _ferma_e_elabora(self) -> None:
        """Ferma la registrazione e lancia la pipeline in background."""
        self._timer.stop()
        self._in_registrazione = False
        self.pulsante.setEnabled(False)
        self.pulsante.setText("Elaborazione...")
        self.etichetta_rec.setText("Registrazione terminata")
        self.etichetta_rec.setStyleSheet("font-size: 22px; font-weight: bold;")

        # Finalizza l'audio (i file restano salvati comunque).
        assert self._registratore is not None
        risultato_rec = self._registratore.ferma()
        self._registratore = None

        # Applichiamo il backend di trascrizione scelto dall'utente nel menù.
        self.config.trascrizione.backend = self.combo_backend.currentData()

        # Avvia il thread di elaborazione (trascrizione + riepilogo).
        self.barra.setVisible(True)
        self.barra.setValue(0)
        self.etichetta_stato.setText("Avvio elaborazione...")

        assert self._cartella_corrente is not None
        self._worker = WorkerElaborazione(
            self.config,
            self._cartella_corrente,
            risultato_rec.file_microfono,
            risultato_rec.file_sistema,
        )
        self._worker.progresso.connect(self._aggiorna_progresso)
        self._worker.finito.connect(self._elaborazione_finita)
        self._worker.start()

    # --------------------------------------------------------------- callback UI
    def _aggiorna_cronometro(self) -> None:
        self._secondi_trascorsi += 1
        ore = self._secondi_trascorsi // 3600
        minuti = (self._secondi_trascorsi % 3600) // 60
        secondi = self._secondi_trascorsi % 60
        self.etichetta_rec.setText(f"● REC  {ore:02d}:{minuti:02d}:{secondi:02d}")

    def _aggiorna_progresso(self, frazione: float, messaggio: str) -> None:
        self.barra.setValue(int(frazione * 100))
        self.etichetta_stato.setText(messaggio)

    def _elaborazione_finita(self, risultato: RisultatoPipeline) -> None:
        """Chiamata quando la pipeline ha finito: mostra l'esito e apre la cartella."""
        self.pulsante.setEnabled(True)
        self.pulsante.setText("● Avvia registrazione")
        self.combo_backend.setEnabled(True)  # ri-abilita la scelta del backend
        self.barra.setValue(100)

        righe = [f"Risultati salvati in:\n{risultato.cartella}"]
        if risultato.errore_trascrizione:
            righe.append(f"\n⚠ Trascrizione NON riuscita: {risultato.errore_trascrizione}")
            righe.append("(L'audio grezzo e' comunque salvato nella cartella.)")
        else:
            righe.append("\n✔ Trascrizione: trascrizione.md")
        if risultato.errore_riepilogo:
            righe.append(f"\n⚠ Riepilogo: {risultato.errore_riepilogo}")
        elif risultato.file_riepilogo:
            righe.append("✔ Riepilogo: riepilogo.md")

        self.etichetta_stato.setText("Completato.")
        QMessageBox.information(self, "Elaborazione completata", "\n".join(righe))

        # Apre la cartella dei risultati in Esplora File.
        self._apri_cartella(risultato.cartella)

    @staticmethod
    def _apri_cartella(cartella: Path) -> None:
        """Apre la cartella nel file manager del sistema (Windows: Esplora File)."""
        try:
            if os.name == "nt":
                os.startfile(str(cartella))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(cartella)])
        except Exception:
            pass  # se non riesce ad aprire, non e' un problema bloccante

    def closeEvent(self, event) -> None:  # noqa: N802 (nome richiesto da Qt)
        """Se chiudi la finestra mentre registri, fermiamo l'audio per sicurezza."""
        if self._registratore is not None:
            try:
                self._registratore.ferma()
            except Exception:
                pass
        event.accept()


def avvia_app() -> None:
    """Crea l'applicazione Qt, mostra l'avviso legale e apre la finestra."""
    config = Config.carica()
    app = QApplication.instance() or QApplication([])
    finestra = FinestraPrincipale(config)
    finestra.show()
    finestra.mostra_avviso_legale()
    app.exec()
