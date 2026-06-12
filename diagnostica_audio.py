"""
diagnostica_audio.py
====================
Script di SOLA VERIFICA: non registra nulla.
Controlla che il tuo PC esponga il microfono di default e il dispositivo
di loopback (audio di sistema) che la app userebbe per registrare.
"""

import pyaudiowpatch as pyaudio

pa = pyaudio.PyAudio()

print("=" * 60)
print("MICROFONO DI DEFAULT (sara' etichettato 'Io')")
print("=" * 60)
try:
    mic = pa.get_default_input_device_info()
    print(f"  Nome:        {mic['name']}")
    print(f"  Canali:      {mic['maxInputChannels']}")
    print(f"  Frequenza:   {int(mic['defaultSampleRate'])} Hz")
except Exception as e:
    print(f"  ERRORE: nessun microfono trovato -> {e}")

print()
print("=" * 60)
print("USCITA AUDIO + LOOPBACK (sara' etichettato 'Partecipanti')")
print("=" * 60)
try:
    info_wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    uscita = pa.get_device_info_by_index(info_wasapi["defaultOutputDevice"])
    print(f"  Uscita di default: {uscita['name']}")

    loop = None
    if uscita.get("isLoopbackDevice", False):
        loop = uscita
    else:
        for info in pa.get_loopback_device_info_generator():
            if uscita["name"] in info["name"]:
                loop = info
                break

    if loop is None:
        print("  ERRORE: loopback NON trovato per l'uscita di default.")
        print("  Dispositivi loopback disponibili:")
        for info in pa.get_loopback_device_info_generator():
            print(f"    - {info['name']}")
    else:
        print(f"  Loopback trovato:  {loop['name']}")
        print(f"  Canali:            {loop['maxInputChannels']}")
        print(f"  Frequenza:         {int(loop['defaultSampleRate'])} Hz")
        print()
        print("  >>> TUTTO OK: il PC e' pronto a registrare entrambe le sorgenti.")
except Exception as e:
    print(f"  ERRORE WASAPI -> {e}")

pa.terminate()
