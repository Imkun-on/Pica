"""FFmpeg c'e' o non c'e', e se non c'e' lo si va a prendere.

Tre motori su quattro non sanno fare niente senza FFmpeg, e tutti e tre
avevano la stessa funzione scritta a modo loro: ``_check_ffmpeg`` in ClipDex,
``_check_ffmpeg`` in PixDex, ``_check_tools`` in BurnDex. Le prime due erano
identiche riga per riga; la terza cambiava solo la chiave del messaggio.

Il controllo si fa una volta all'avvio, prima di qualunque altra cosa.
L'alternativa e' scoprire l'assenza di FFmpeg a meta' decodifica, dopo che chi
sta al terminale ha gia' scelto la raccolta, le tracce e la velocita' - e su
BurnDex, dopo che il disco e' gia' in movimento.

Servono ENTRAMBI gli eseguibili, e per compiti distinti: ``ffprobe`` legge le
durate senza decodificare, ``ffmpeg`` fa il lavoro. Vengono elencati insieme
quelli mancanti, cosi' chi ha installato male il pacchetto risolve tutto in un
colpo invece di scoprire il secondo problema dopo aver corretto il primo.

Da dove viene, se manca
    Chi ha gia' FFmpeg nel PATH usa il suo, e qui non succede niente. Agli
    altri lo si scarica al primo avvio, in sottofondo, come si fa con Tor
    (vedi ``utils/tor.py``): la build «full shared» di gyan.dev, la stessa
    famiglia che installa ``winget install Gyan.FFmpeg``, circa 100 MB, in
    ``%LOCALAPPDATA%\\Pica\\ffmpeg``. La cartella viene poi messa in testa
    al PATH di questo processo: tutti i motori chiamano ``ffmpeg`` per nome,
    e continuano a farlo senza sapere da dove arriva.

    Non passa da Tor, per la stessa ragione dei modelli: sono tanti megabyte
    da un sito che non c'entra con cosa si guarda.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import zipfile

import requests

from server.config import i18n, paths
from server.utils.console import console, setup_logger

log = setup_logger('ffmpeg', 'ffmpeg.log')

CARTELLA = paths.locale('ffmpeg')
_NOMI = ('ffmpeg', 'ffprobe')
# L'ultima versione la dice GitHub, dove gyan.dev pubblica le sue build. Se
# GitHub non risponde resta l'indirizzo fisso di gyan.dev, che ha solo la
# build «essentials»: piu' piccola dentro ma basta a tutto quello che si fa qui.
_INDICE = 'https://api.github.com/repos/GyanD/codexffmpeg/releases/latest'
_SCELTA = 'full_build-shared.zip'
_RIPIEGO = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

_pronto = threading.Event()
_serratura = threading.Lock()
_stato = {'fase': 'spento', 'errore': '', 'parte': 0.0}


def check_ffmpeg(chiave: str = 'tools.no_ffmpeg') -> bool:
    """True se ffmpeg e ffprobe sono nel PATH; altrimenti lo stampa e dice no.

    ``chiave`` esiste solo perche' BurnDex ha sempre detto la stessa cosa con
    parole sue (``tools.missing``). Unificare la logica non e' una buona
    ragione per cambiare, senza dirlo a nessuno, una frase che qualcuno legge
    da mesi.
    """
    mancanti = [nome for nome in _NOMI if not shutil.which(nome)]
    if mancanti:
        console.print(i18n.t(chiave, tools=', '.join(mancanti)))
        console.print(i18n.t('tools.install_ffmpeg'))
        return False
    return True


def stato() -> dict:
    """Per la pagina: 'spento', 'avvio', 'scarico', 'pronto' o 'errore', e a
    che punto e' lo scaricamento."""
    return dict(_stato)


def _nel_path() -> bool:
    return all(shutil.which(nome) for nome in _NOMI)


def _indirizzo() -> str:
    try:
        uscita = requests.get(_INDICE, timeout=30).json()
        for allegato in uscita['assets']:
            if allegato['name'].endswith(_SCELTA):
                return allegato['browser_download_url']
    except Exception as e:                  # noqa: BLE001
        log.warning('Indice di FFmpeg non letto (%s): uso il ripiego', e)
    return _RIPIEGO


def installa() -> None:
    """Scarica FFmpeg e ne tiene la cartella ``bin``, senza ffplay.

    Si scompatta in una cartella provvisoria e la si rinomina alla fine: una
    chiusura a meta' non lascia una cartella che sembra a posto e non lo e'.
    """
    indirizzo = _indirizzo()
    log.info('Scarico FFmpeg da %s', indirizzo)
    os.makedirs(os.path.dirname(CARTELLA), exist_ok=True)
    provvisoria = CARTELLA + '.parziale'
    shutil.rmtree(provvisoria, ignore_errors=True)
    shutil.rmtree(CARTELLA, ignore_errors=True)
    os.makedirs(provvisoria)
    with tempfile.TemporaryFile() as f:
        with requests.get(indirizzo, stream=True, timeout=60) as risposta:
            risposta.raise_for_status()
            totale = int(risposta.headers.get('Content-Length') or 0)
            scaricati = 0
            for pezzo in risposta.iter_content(1 << 20):
                f.write(pezzo)
                scaricati += len(pezzo)
                if totale:
                    _stato['parte'] = scaricati / totale
        f.seek(0)
        with zipfile.ZipFile(f) as archivio:
            for voce in archivio.infolist():
                nome = os.path.basename(voce.filename)
                if (voce.is_dir() or '/bin/' not in voce.filename
                        or nome.lower() == 'ffplay.exe'):
                    continue
                with archivio.open(voce) as da, \
                        open(os.path.join(provvisoria, nome), 'wb') as a:
                    shutil.copyfileobj(da, a)
    os.replace(provvisoria, CARTELLA)


def _funziona() -> bool:
    """True se l'ffmpeg scaricato c'e' e parte davvero."""
    if not all(os.path.isfile(os.path.join(CARTELLA, n + '.exe')) for n in _NOMI):
        return False
    try:
        return subprocess.run(
            [os.path.join(CARTELLA, 'ffmpeg.exe'), '-version'],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _prepara() -> None:
    try:
        if not _nel_path():
            if not _funziona():
                _stato.update(fase='scarico', parte=0.0)
                installa()
                if not _funziona():
                    raise RuntimeError('scaricato, ma non parte')
            os.environ['PATH'] = CARTELLA + os.pathsep + os.environ.get('PATH', '')
        _stato.update(fase='pronto', parte=1.0)
        log.info('FFmpeg pronto: %s', shutil.which('ffmpeg'))
    except Exception as e:                  # noqa: BLE001
        log.error('FFmpeg non installato: %s', e)
        _stato.update(fase='errore', errore=str(e)[:200])
    _pronto.set()


def avvia_in_sottofondo() -> None:
    """Cerca FFmpeg e, se manca, lo scarica: una volta sola, senza aspettarlo."""
    with _serratura:
        if _stato['fase'] in ('spento', 'errore'):
            _pronto.clear()
            _stato.update(fase='avvio', errore='')
            threading.Thread(target=_prepara, daemon=True, name='ffmpeg').start()


def attendi(secondi: float | None = None) -> bool:
    """Aspetta che FFmpeg sia pronto. False se il tempo non e' bastato.

    Se non si e' riusciti a scaricarlo solleva un errore: il lavoro che lo
    aspettava si ferma qui con una spiegazione, invece che a meta' strada.
    """
    avvia_in_sottofondo()
    if not _pronto.wait(secondi):
        return False
    if _stato['fase'] != 'pronto':
        raise RuntimeError('FFmpeg non scaricato: ' + _stato['errore'])
    return True
