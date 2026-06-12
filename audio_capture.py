"""
audio_capture.py
================
Cattura DUE sorgenti audio contemporaneamente e le scrive su disco:

  1) il MICROFONO  -> sara' etichettato "Io"
  2) l'AUDIO DI SISTEMA (loopback WASAPI, cioe' "cio' che si sente" da
     casse/cuffie) -> sara' etichettato "Partecipanti"

Idea chiave: tenendo i due canali su DUE file separati otteniamo "gratis" la
distinzione tra te e gli altri, senza usare modelli pesanti di diarizzazione.

Scelte importanti per il tuo PC (16 GB RAM, no GPU):
  - L'audio viene scritto su disco IN CONTINUAZIONE (a blocchi), tramite il
    meccanismo "callback" di PyAudio. NON teniamo mai l'intera riunione in RAM.
  - Ogni stream registra al suo formato nativo (sample rate / canali del
    dispositivo). La conversione a 16 kHz mono avviene piu' tardi, al momento
    della trascrizione (cosi' la fase di cattura resta leggera e robusta).
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import pyaudiowpatch as pyaudio


class ErroreAudio(Exception):
    """Errore "amichevole" da mostrare all'utente quando l'audio non parte."""


@dataclass
class RisultatoRegistrazione:
    """Percorsi dei file WAV prodotti da una registrazione."""
    file_microfono: Path
    file_sistema: Path


class _ScrittoreWav:
    """
    Piccolo aiutante che apre un file WAV e ci scrive dentro i blocchi audio
    mano a mano che arrivano dal dispositivo. Pensato per essere usato dentro
    una callback di PyAudio.
    """

    def __init__(self, percorso: Path, canali: int, ampiezza_byte: int, frequenza: int) -> None:
        self.percorso = percorso
        self._wave = wave.open(str(percorso), "wb")
        self._wave.setnchannels(canali)
        self._wave.setsampwidth(ampiezza_byte)
        self._wave.setframerate(frequenza)

    def scrivi(self, dati: bytes) -> None:
        """Aggiunge un blocco di byte al file WAV (scrittura incrementale)."""
        self._wave.writeframes(dati)

    def chiudi(self) -> None:
        """Finalizza il file WAV (scrive l'header corretto e chiude)."""
        if self._wave is not None:
            self._wave.close()
            self._wave = None  # type: ignore[assignment]


class RegistratoreAudio:
    """
    Gestisce l'intera registrazione: trova i dispositivi, apre i due stream,
    scrive su disco e si ferma su richiesta.

    Uso tipico:
        rec = RegistratoreAudio(cartella_destinazione)
        rec.avvia()
        ... (la riunione va avanti) ...
        risultato = rec.ferma()
    """

    def __init__(self, cartella_destinazione: Path) -> None:
        self.cartella = Path(cartella_destinazione)
        self.cartella.mkdir(parents=True, exist_ok=True)

        self._pa: pyaudio.PyAudio | None = None
        self._stream_mic = None
        self._stream_sys = None
        self._scrittore_mic: _ScrittoreWav | None = None
        self._scrittore_sys: _ScrittoreWav | None = None
        self._in_corso = False

        # Percorsi dei file di output (per canale).
        self.percorso_mic = self.cartella / "audio_microfono.wav"
        self.percorso_sys = self.cartella / "audio_sistema.wav"

    # ----------------------------------------------------------------- utilità
    @staticmethod
    def _trova_dispositivi(pa: pyaudio.PyAudio) -> tuple[dict, dict]:
        """
        Trova:
          - il microfono di default (dispositivo di INPUT),
          - il dispositivo di output di default in modalita' LOOPBACK.

        Solleva ErroreAudio con un messaggio chiaro se qualcosa manca.
        """
        # 1) Microfono di default.
        try:
            mic = pa.get_default_input_device_info()
        except OSError as e:
            raise ErroreAudio(
                "Nessun microfono di default trovato.\n"
                "Verifica in Impostazioni Windows > Sistema > Audio che ci sia "
                "un microfono attivo e impostato come predefinito."
            ) from e

        # 2) Loopback dell'uscita audio (WASAPI).
        #    Prima troviamo l'uscita di default, poi cerchiamo il suo "gemello"
        #    in modalita' loopback (che PyAudioWPatch espone come device a parte).
        try:
            info_wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as e:
            raise ErroreAudio(
                "WASAPI non disponibile su questo sistema. La cattura "
                "dell'audio di sistema (loopback) richiede Windows con WASAPI."
            ) from e

        uscita_default = pa.get_device_info_by_index(info_wasapi["defaultOutputDevice"])

        dispositivo_loopback: dict | None = None
        if uscita_default.get("isLoopbackDevice", False):
            dispositivo_loopback = uscita_default
        else:
            # Cerchiamo tra i device loopback quello col nome dell'uscita di default.
            for info in pa.get_loopback_device_info_generator():
                if uscita_default["name"] in info["name"]:
                    dispositivo_loopback = info
                    break

        if dispositivo_loopback is None:
            raise ErroreAudio(
                "Impossibile trovare il dispositivo di LOOPBACK per l'audio di "
                "sistema.\n"
                "Possibili cause e soluzioni:\n"
                " - Assicurati di avere un dispositivo di uscita audio attivo "
                "(casse o cuffie) impostato come predefinito in Windows.\n"
                " - Alcune cuffie Bluetooth in modalita' 'mani libere/headset' "
                "non espongono il loopback: prova con casse/cuffie su jack o USB, "
                "oppure cambia il profilo Bluetooth in 'stereo'."
            )

        return mic, dispositivo_loopback

    # --------------------------------------------------------------- controllo
    def avvia(self) -> None:
        """
        Avvia la registrazione: apre i due stream e comincia a scrivere su disco.
        Da chiamare una sola volta. Solleva ErroreAudio in caso di problemi.
        """
        if self._in_corso:
            return

        self._pa = pyaudio.PyAudio()
        try:
            mic, sys_loop = self._trova_dispositivi(self._pa)

            # Parametri del microfono (usiamo i suoi valori nativi).
            mic_canali = int(mic["maxInputChannels"]) or 1
            mic_freq = int(mic["defaultSampleRate"])

            # Parametri del loopback di sistema.
            sys_canali = int(sys_loop["maxInputChannels"]) or 2
            sys_freq = int(sys_loop["defaultSampleRate"])

            # Registriamo a 16 bit con segno (formato standard, leggero).
            formato = pyaudio.paInt16
            ampiezza = self._pa.get_sample_size(formato)

            # Creiamo i due scrittori su file.
            self._scrittore_mic = _ScrittoreWav(self.percorso_mic, mic_canali, ampiezza, mic_freq)
            self._scrittore_sys = _ScrittoreWav(self.percorso_sys, sys_canali, ampiezza, sys_freq)

            # --- Callback: vengono chiamate da PyAudio quando arriva audio. ---
            # Scrivono subito su disco e dicono a PyAudio di continuare.
            def _cb_mic(in_data, frame_count, time_info, status):  # noqa: ANN001
                if self._scrittore_mic is not None:
                    self._scrittore_mic.scrivi(in_data)
                return (None, pyaudio.paContinue)

            def _cb_sys(in_data, frame_count, time_info, status):  # noqa: ANN001
                if self._scrittore_sys is not None:
                    self._scrittore_sys.scrivi(in_data)
                return (None, pyaudio.paContinue)

            # Stream del microfono.
            self._stream_mic = self._pa.open(
                format=formato,
                channels=mic_canali,
                rate=mic_freq,
                input=True,
                input_device_index=int(mic["index"]),
                frames_per_buffer=1024,
                stream_callback=_cb_mic,
            )

            # Stream del loopback di sistema.
            self._stream_sys = self._pa.open(
                format=formato,
                channels=sys_canali,
                rate=sys_freq,
                input=True,
                input_device_index=int(sys_loop["index"]),
                frames_per_buffer=1024,
                stream_callback=_cb_sys,
            )

            self._stream_mic.start_stream()
            self._stream_sys.start_stream()
            self._in_corso = True

        except ErroreAudio:
            # Errore "amichevole" gia' pronto: ripuliamo e rilanciamo.
            self._pulisci()
            raise
        except Exception as e:  # qualsiasi altro problema tecnico
            self._pulisci()
            raise ErroreAudio(f"Errore durante l'avvio della registrazione: {e}") from e

    def ferma(self) -> RisultatoRegistrazione:
        """
        Ferma la registrazione, finalizza i file WAV e restituisce i percorsi.
        Sicura da chiamare anche se la registrazione e' gia' ferma.
        """
        self._in_corso = False

        # Ferma e chiude gli stream.
        for stream in (self._stream_mic, self._stream_sys):
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass  # in chiusura ignoriamo errori secondari

        self._stream_mic = None
        self._stream_sys = None

        # Finalizza i file (header WAV corretto).
        if self._scrittore_mic is not None:
            self._scrittore_mic.chiudi()
        if self._scrittore_sys is not None:
            self._scrittore_sys.chiudi()

        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

        return RisultatoRegistrazione(
            file_microfono=self.percorso_mic,
            file_sistema=self.percorso_sys,
        )

    def _pulisci(self) -> None:
        """Chiusura di emergenza usata se l'avvio fallisce a meta'."""
        for stream in (self._stream_mic, self._stream_sys):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        self._stream_mic = None
        self._stream_sys = None
        if self._scrittore_mic is not None:
            self._scrittore_mic.chiudi()
        if self._scrittore_sys is not None:
            self._scrittore_sys.chiudi()
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None


# ---------------------------------------------------------------------------
# Piccolo test manuale: registra 5 secondi e salva i due file.
# Lancialo con:  python audio_capture.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import time

    print("Registro 5 secondi di prova (parla al microfono e fai suonare qualcosa)...")
    rec = RegistratoreAudio(Path("output") / "_prova_audio")
    rec.avvia()
    time.sleep(5)
    risultato = rec.ferma()
    print("Fatto! File creati:")
    print("  Microfono:", risultato.file_microfono)
    print("  Sistema:  ", risultato.file_sistema)
