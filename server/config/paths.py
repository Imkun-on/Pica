"""Dove stanno le cose, dentro e fuori dall'eseguibile.

Il problema che risolve
    Ogni modulo del progetto calcola la propria cartella con
    ``os.path.dirname(os.path.abspath(__file__))``, e finche' si lancia
    ``python main.py`` e' esattamente quello che serve.

    Dentro un eseguibile costruito con PyInstaller non lo e' piu'. In modalita'
    a file unico il contenuto viene estratto a ogni avvio in una cartella
    temporanea, e ``__file__`` punta li'. Un log scritto in quella cartella, o
    una preferenza salvata li', sparirebbero alla chiusura del programma
    insieme alla cartella stessa. E i brani scaricati finirebbero in un posto
    che nessuno andrebbe mai a cercare.

Le due cartelle, che non coincidono
    risorse   cio' che e' stato impacchettato insieme al programma e non
              cambia mai: la pagina web, le icone. Dentro l'eseguibile sta
              nella cartella temporanea; fuori, accanto ai sorgenti.

    dati      cio' che appartiene a chi usa il programma e deve restare:
              i brani scaricati, i log, la lingua scelta. Dentro
              l'eseguibile sta accanto al file .exe, dove la si trova
              aprendo la cartella; fuori, accanto ai sorgenti.

    Fuori dall'eseguibile le due coincidono, ed e' il motivo per cui finora
    la distinzione non serviva a nessuno.
"""
from __future__ import annotations

import os
import sys

# La radice del progetto quando si lavora sui sorgenti.
#
# I passi hanno un nome invece di stare dentro a tre dirname annidati: cosi'
# chi legge CONTA i livelli invece di dedurli dalle parentesi. Non e'
# pedanteria - e' la riga piu' fragile del progetto. Qui dentro finiscono i
# log, la lingua scelta, il database dei download e i brani scaricati:
# sbagliare di un livello non da' nessun errore, sposta soltanto tutte e
# quattro le cose in una cartella dove nessuno le cerchera'. Spostando questo
# file si aggiunge o si toglie un passo, e il nome dice subito se il conto
# torna.
_QUESTO_FILE = os.path.abspath(__file__)
_CARTELLA_CONFIG = os.path.dirname(_QUESTO_FILE)      # server/config
_CARTELLA_SERVER = os.path.dirname(_CARTELLA_CONFIG)  # server
_SORGENTI = os.path.dirname(_CARTELLA_SERVER)         # la radice


def impacchettato() -> bool:
    """True se stiamo girando dentro un eseguibile costruito con PyInstaller."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def cartella_risorse() -> str:
    """Dove stanno i file impacchettati col programma (la pagina, le icone)."""
    return sys._MEIPASS if impacchettato() else _SORGENTI


def cartella_dati() -> str:
    """Dove stanno i file di chi usa il programma, e dove restano.

    Accanto all'eseguibile, non nella cartella temporanea: e' l'unico posto
    che chi lo ha lanciato sa ritrovare, ed e' l'unico che sopravvive alla
    chiusura.
    """
    if impacchettato():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _SORGENTI


def dati(*parti: str) -> str:
    """Percorso dentro la cartella dei dati, creata se non c'e' ancora."""
    percorso = os.path.join(cartella_dati(), *parti)
    return percorso


def risorsa(*parti: str) -> str:
    """Percorso dentro la cartella delle risorse impacchettate."""
    return os.path.join(cartella_risorse(), *parti)


# ── Gli strumenti scaricati, fuori dalla cartella del programma ──────────────
#
# FFmpeg, Tor, Real-ESRGAN e l'ambiente della voce stanno in
# %LOCALAPPDATA%\Pica. Fino a quando il programma si chiamava MediaDex la
# cartella era %LOCALAPPDATA%\MediaDex: la si rinomina una volta sola, cosi'
# nessuno riscarica un giga e mezzo solo perche' e' cambiato il nome. Se il
# rinomino non riesce (un tor.exe ancora aperto, per dire) si continua a usare
# la vecchia: meglio un nome vecchio che un download inutile.

_VECCHIO_NOME = 'MediaDex'


def _cartella_locale() -> str:
    base = os.environ.get('LOCALAPPDATA') or cartella_dati()
    nuova = os.path.join(base, 'Pica')
    vecchia = os.path.join(base, _VECCHIO_NOME)
    if os.path.isdir(vecchia) and not os.path.exists(nuova):
        try:
            os.rename(vecchia, nuova)
        except OSError:
            return vecchia
    return nuova


def locale(*parti: str) -> str:
    """Percorso dentro %LOCALAPPDATA%\\Pica, dove stanno gli strumenti scaricati."""
    return os.path.join(_cartella_locale(), *parti)


# ── Dove finisce quello che il programma produce ─────────────────────────────
#
# Una cartella sola, divisa come la finestra: una sottocartella per ogni
# sezione che produce file, e dentro, dove la sezione fa cose diverse, una per
# ciascuna.
#
#     risultati/
#         Audio/                 brani; una sottocartella per playlist o album
#         Video/                 video e i loro .srt; una per playlist
#             Sottotitolati/     le copie coi sottotitoli impressi
#         Doppiaggio/            le copie con le voci rigenerate
#         Rimasterizza/
#         Montaggio/
#             Tagli/  Unioni/  GIF/  WebP/
#
# Masterizzazione e Sottotitoli non producono file nuovi: la prima scrive su
# un CD, la seconda corregge i .srt accanto ai video che ci sono gia'.
#
# Prima la finestra chiedeva dove salvare, poi c'era un posto solo con tutto
# dentro alla rinfusa («musica», video compresi). Le sottocartelle si creano
# da sole al primo file che ci finisce dentro.

def risultati(*parti: str) -> str:
    """La cartella dei risultati, o qualcosa dentro di essa."""
    return dati('risultati', *parti)


def _assicura(percorso: str) -> str:
    """Crea la cartella se non c'e' e restituisce il percorso.

    Creare qui invece che nei chiamanti evita il difetto classico: il motore
    scrive il file, la cartella non esiste, e l'errore che arriva parla di un
    percorso invece che di quello che si stava facendo.
    """
    os.makedirs(percorso, exist_ok=True)
    return percorso


def cartella_audio() -> str:
    """I brani scaricati, una sottocartella per playlist o album."""
    return _assicura(risultati('Audio'))


def cartella_video() -> str:
    """I video scaricati coi loro .srt, una sottocartella per playlist."""
    return _assicura(risultati('Video'))


SOTTOTITOLATI = 'Sottotitolati'


def cartella_doppiaggio() -> str:
    """Le copie ridoppiate dalla sezione Doppiaggio, e le battute riscritte."""
    return _assicura(risultati('Doppiaggio'))


def cartella_rimasterizzati() -> str:
    """I video rifatti da PixDex, piu' i confronti prima/dopo."""
    return _assicura(risultati('Rimasterizza'))


# Le operazioni di ClipDex e la sottocartella di ciascuna.
MONTAGGI = {'taglia': 'Tagli', 'unisci': 'Unioni', 'gif': 'GIF', 'webp': 'WebP'}


def cartella_montaggi(operazione: str) -> str:
    """Spezzoni, unioni, GIF e WebP prodotti da ClipDex, ognuno al suo posto."""
    return _assicura(risultati('Montaggio', MONTAGGI.get(operazione, '')))


_AUDIO = ('.m4a', '.mp3', '.opus', '.flac', '.wav', '.ogg', '.aac')


def riordina_risultati() -> list[str]:
    """Sposta i file delle vecchie cartelle nella struttura di adesso.

    Una volta sola: dopo, le cartelle vecchie non ci sono piu' e non c'e'
    niente da fare. ``musica/`` teneva insieme brani e video: i file audio
    vanno in Audio, il resto in Video, le copie «(sottotitolato)» in
    Video/Sottotitolati. Una sottocartella che contiene video (una playlist
    scaricata come video) va in Video, le altre in Audio. Un file che
    all'arrivo trova gia' un omonimo resta dov'e', per non perdere niente.
    Restituisce cio' che non e' riuscito a spostare.
    """
    import shutil

    rimasti: list[str] = []

    def sposta(sorgente: str, cartella: str) -> None:
        os.makedirs(cartella, exist_ok=True)
        dest = os.path.join(cartella, os.path.basename(sorgente))
        if os.path.exists(dest):
            rimasti.append(sorgente)
            return
        try:
            shutil.move(sorgente, dest)
        except OSError:
            rimasti.append(sorgente)

    def svuota(cartella: str) -> None:
        try:
            os.rmdir(cartella)
        except OSError:
            pass

    musica = risultati('musica')
    if os.path.isdir(musica):
        for nome in os.listdir(musica):
            p = os.path.join(musica, nome)
            if os.path.isdir(p):
                dentro = [f.lower() for f in os.listdir(p)]
                video = any(not f.endswith(_AUDIO) and os.path.splitext(f)[1] in
                            ('.mp4', '.mkv', '.webm', '.mov') for f in dentro)
                sposta(p, risultati('Video' if video else 'Audio'))
            elif ' (sottotitolato)' in nome:
                sposta(p, risultati('Video', SOTTOTITOLATI))
            elif nome.lower().endswith(_AUDIO):
                sposta(p, risultati('Audio'))
            else:
                sposta(p, risultati('Video'))
        svuota(musica)

    vecchi = risultati('rimasterizzati')
    if os.path.isdir(vecchi):
        for nome in os.listdir(vecchi):
            sposta(os.path.join(vecchi, nome), risultati('Rimasterizza'))
        svuota(vecchi)

    vecchi = risultati('montaggi')
    if os.path.isdir(vecchi):
        for nome in os.listdir(vecchi):
            minuscolo = nome.lower()
            operazione = next((op for op, parola in (('taglia', 'taglio'), ('unisci', 'unito'),
                                                     ('gif', '.gif'), ('webp', '.webp'))
                               if parola in minuscolo), '')
            sposta(os.path.join(vecchi, nome),
                   risultati('Montaggio', MONTAGGI.get(operazione, '')))
        svuota(vecchi)
    return rimasti
