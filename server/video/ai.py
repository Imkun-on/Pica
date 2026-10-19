"""Migliorare un video con l'intelligenza artificiale: Real-ESRGAN.

Il resto di «Migliora qualita'» lavora in sottrazione: toglie quadretti e
bande, e l'ingrandimento non aggiunge dettaglio. Real-ESRGAN fa l'opposto:
una rete neurale ridisegna ogni fotogramma a una risoluzione piu' alta, e
il dettaglio che mette - capelli, trame, contorni - e' *plausibile*, ma
inventato. Sui cartoni rende benissimo; sui volti e sulle scritte a volte
sbaglia (pelle di plastica, lettere storte).

Si usa la versione ncnn-vulkan: un .exe da 45 MB, senza Python ne' CUDA,
che lavora sulla scheda grafica attraverso Vulkan - anche sulla Vega 8
integrata di un Ryzen 5 3500U. Si scarica la prima volta che serve, in
``%LOCALAPPDATA%\\Pica\\realesrgan``.

E' lento, ed e' la sua natura: su quel portatile il modello per video
(``realesr-animevideov3``, x2) impiega circa 2,5 secondi per fotogramma a
360p, dall'estrazione alla codifica. Un minuto di video a 24 fotogrammi al
secondo e' circa un'ora.

Come lavora, a blocchi
    I fotogrammi si estraggono tutti in JPEG (pesano poco), poi a blocchi di
    ``BLOCCO``: la rete li ingrandisce, FFmpeg ne fa uno spezzone video, e i
    fotogrammi del blocco si cancellano. Cosi' sul disco non si accumulano
    decine di gigabyte di immagini ingrandite. Alla fine gli spezzoni si
    uniscono in copia e ci si rimette l'audio originale, non ricodificato.
"""
from __future__ import annotations

import glob
import io
import os
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile

import requests

from server.config import paths
from server.utils.console import setup_logger

log = setup_logger('pixdex', 'pixdex.log')

CARTELLA = paths.locale('realesrgan')
ESEGUIBILE = os.path.join(CARTELLA, 'realesrgan-ncnn-vulkan.exe')
_ARCHIVIO = ('https://github.com/xinntao/Real-ESRGAN/releases/download/'
             'v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip')

# Il modello offerto: quello fatto per i video, leggero e coerente da un
# fotogramma all'altro, che sa ingrandire di 2, 3 o 4.
#
# C'era anche quello per le foto (``realesrgan-x4plus``), piu' ricco di
# dettaglio. Misurato sulla Vega 8: circa 150 secondi a fotogramma da 360p,
# quaranta volte il modello per video - un minuto di video, sessanta ore.
# Offrirlo sarebbe stato offrire un bottone che non finisce mai.
MODELLI = {
    'ai':         ('realesr-animevideov3', (2, 3, 4)),
}

BLOCCO = 240        # fotogrammi per blocco: dieci secondi a 24 fps


def pronto() -> bool:
    return os.path.isfile(ESEGUIBILE)


def installa(dici=None) -> None:
    """Scarica e scompatta Real-ESRGAN, se non c'e' gia'."""
    if pronto():
        return
    os.makedirs(CARTELLA, exist_ok=True)
    if dici:
        dici('scarico Real-ESRGAN (45 MB, una volta sola)')
    risposta = requests.get(_ARCHIVIO, timeout=60)
    risposta.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(risposta.content)) as z:
        for nome in z.namelist():
            # Le immagini e il video di esempio non servono a nessuno.
            if nome.lower().endswith(('.jpg', '.mp4', '.md')):
                continue
            z.extract(nome, CARTELLA)
    if not pronto():
        raise RuntimeError('Real-ESRGAN scaricato, ma manca il programma')


def fattore(preset: str, altezza_da: int, altezza_a: int) -> int:
    """Di quanto far ingrandire la rete per arrivare ad ``altezza_a``.

    Il fattore piu' piccolo che basta: la rete lavora sui pixel d'uscita, e un
    x4 costa quattro volte un x2. Se si chiede di non ingrandire, si usa
    comunque il minimo e poi si riporta giu': il passaggio nella rete pulisce
    anche a parita' di risoluzione.
    """
    scale = MODELLI[preset][1]
    for s in scale:
        if altezza_da * s >= altezza_a:
            return s
    return scale[-1]


def _conta(cartella: str) -> int:
    try:
        return len(os.listdir(cartella))
    except OSError:
        return 0


def migliora(info: dict, dst: str, preset: str, altezza: int, crf: int,
             avanzamento=None, dici=None) -> bool:
    """Ingrandisce il video fotogramma per fotogramma con Real-ESRGAN.

    ``avanzamento(fatti, totale)`` riceve i fotogrammi gia' passati dalla
    rete. ``dici(testo)`` riceve la fase in corso. Restituisce True se il
    file d'arrivo e' stato scritto.
    """
    installa(dici)
    modello, _scale = MODELLI[preset]
    s = fattore(preset, info['height'], altezza or info['height'])
    fps = info['fps'] or 25.0
    altezza = altezza or info['height']

    with tempfile.TemporaryDirectory(prefix='pica_ai_') as tmp:
        tutti = os.path.join(tmp, 'tutti')
        os.makedirs(tutti)
        if dici:
            dici('estraggo i fotogrammi')
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-i', info['path'],
             '-map', '0:v:0', '-fps_mode', 'passthrough', '-q:v', '2',
             os.path.join(tutti, '%07d.jpg')],
            check=True)
        fotogrammi = sorted(os.listdir(tutti))
        totale = len(fotogrammi)
        if not totale:
            return False

        spezzoni: list[str] = []
        fatti = 0
        for n, inizio in enumerate(range(0, totale, BLOCCO)):
            entra = os.path.join(tmp, 'entra')
            esce = os.path.join(tmp, 'esce')
            for d in (entra, esce):
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d)
            blocco = fotogrammi[inizio:inizio + BLOCCO]
            for i, nome in enumerate(blocco):
                os.replace(os.path.join(tutti, nome),
                           os.path.join(entra, f'{i:07d}.jpg'))
            if dici:
                dici(f"l'AI ridisegna i fotogrammi (x{s})")

            proc = subprocess.Popen(
                [ESEGUIBILE, '-i', entra, '-o', esce, '-n', modello,
                 '-s', str(s), '-f', 'png'],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            # Lo stderr si svuota in un thread: la rete scrive una riga di
            # percentuale per ogni fotogramma, e una pipe piena la fermerebbe.
            errore: list[bytes] = []
            lettore = threading.Thread(
                target=lambda: errore.append(proc.stderr.read()), daemon=True)
            lettore.start()
            while proc.poll() is None:
                if avanzamento:
                    avanzamento(fatti + _conta(esce), totale)
                time.sleep(1.0)
            lettore.join(timeout=5)
            if proc.returncode != 0 or _conta(esce) < len(blocco):
                coda = (b''.join(errore).decode('utf-8', 'replace')
                        .strip().splitlines() or ['?'])[-1]
                log.error('Real-ESRGAN fallito (%s): %s', proc.returncode, coda)
                raise RuntimeError(f'Real-ESRGAN: {coda}')
            fatti += len(blocco)
            if avanzamento:
                avanzamento(fatti, totale)

            # Lo spezzone: gia' all'altezza d'arrivo, cosi' i PNG grandi si
            # possono cancellare subito.
            spezzone = os.path.join(tmp, f'spezzone{n:04d}.mp4')
            subprocess.run(
                ['ffmpeg', '-v', 'error', '-nostdin', '-y',
                 '-framerate', f'{fps:.6f}', '-i', os.path.join(esce, '%07d.png'),
                 '-vf', f'scale=-2:{altezza}:flags=lanczos,format=yuv420p',
                 '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf),
                 spezzone],
                check=True)
            spezzoni.append(spezzone)
            shutil.rmtree(entra, ignore_errors=True)
            shutil.rmtree(esce, ignore_errors=True)

        if dici:
            dici('unisco e rimetto l\'audio')
        elenco = os.path.join(tmp, 'elenco.txt')
        with open(elenco, 'w', encoding='utf-8') as fh:
            for p in spezzoni:
                fh.write("file '" + p.replace('\\', '/').replace("'", "'\\''") + "'\n")
        from server.video.remaster import _comando_audio
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-y',
             '-f', 'concat', '-safe', '0', '-i', elenco,
             '-i', info['path'],
             '-map', '0:v:0', '-map', '1:a:0?',
             '-c:v', 'copy', *_comando_audio(info),
             '-movflags', '+faststart', dst],
            check=True)
    return os.path.isfile(dst) and os.path.getsize(dst) > 0


def pulisci_residui() -> None:
    """Toglie le cartelle temporanee rimaste da un lavoro interrotto."""
    for d in glob.glob(os.path.join(tempfile.gettempdir(), 'pica_ai_*')):
        shutil.rmtree(d, ignore_errors=True)
