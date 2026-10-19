"""Nessuna finestra nera per i programmi che Pica lancia da se'.

Il guasto
    Pica e' un programma a finestra, senza console (``console=False``
    nel .spec). Su Windows, quando un programma senza console lancia un
    programma da console - ffmpeg, ffprobe, il Python del doppiaggio, pip -
    Windows gliene apre una nuova. Un download ne lancia parecchi: ffprobe per
    leggere il file, ffmpeg per unire audio e video, per la copertina, per il
    volume. Ognuno era una finestra di terminale che lampeggiava sullo
    schermo.

Perche' qui e non chiamata per chiamata
    Le chiamate sono una quarantina, sparse in tutto ``server/``, e alcune
    nemmeno sono nostre: yt-dlp lancia ffmpeg per conto suo. Mettere
    ``CREATE_NO_WINDOW`` a mano su ognuna vuol dire dimenticarne una alla
    prossima modifica. Si mette invece una volta sola, su ``subprocess.Popen``,
    da cui passano tutte - ``subprocess.run`` compreso.

    Chi chiede esplicitamente una console nuova (``CREATE_NEW_CONSOLE``) o
    nessuna (``DETACHED_PROCESS``) la ottiene comunque: la regola vale solo
    per chi non ha detto niente.
"""
from __future__ import annotations

import subprocess
import sys

_FATTO = False


def nascondi_console() -> None:
    """Da chiamare una volta, all'avvio, prima di lanciare qualunque cosa."""
    global _FATTO
    if _FATTO or sys.platform != 'win32':
        return
    _FATTO = True

    senza_finestra = subprocess.CREATE_NO_WINDOW
    con_console = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS
    originale = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        flag = kwargs.get('creationflags') or 0
        if not flag & con_console:
            kwargs['creationflags'] = flag | senza_finestra
        originale(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
