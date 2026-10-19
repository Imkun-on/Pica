"""Nascondere l'IP: tutto quello che va verso YouTube passa da Tor.

Cosa fa
    YouTube (e LRCLIB per i testi) non vedono l'indirizzo di casa: vedono
    quello di un nodo d'uscita di Tor, che cambia. Il programma avvia un
    ``tor.exe`` suo, in sottofondo, all'apertura della finestra, e ci fa
    passare yt-dlp, le copertine, le miniature e i testi.

    E' sempre acceso, senza interruttore. Se Tor non parte, i download NON
    ripiegano sulla connessione diretta: si fermano con un messaggio. Un
    ripiego silenzioso mostrerebbe l'IP proprio nel momento in cui si crede
    di averlo nascosto.

    Non passano da Tor gli scaricamenti dei modelli (Whisper, Opus-MT,
    Real-ESRGAN): sono centinaia di megabyte da siti che non c'entrano con
    cosa si guarda, e su Tor ci metterebbero molto di piu'.

Da dove viene tor.exe
    Dal «Tor Expert Bundle» ufficiale, scaricato da torproject.org la prima
    volta (circa 22 MB), in ``%LOCALAPPDATA%\\Pica\\tor``. La versione
    la dice l'indice che usa anche Tor Browser per aggiornarsi.

YouTube e Tor
    A volte YouTube riconosce un nodo d'uscita e risponde «conferma di non
    essere un bot». Si chiede allora a Tor un'identita' nuova (``NEWNYM``, un
    altro nodo d'uscita) e si riprova: e' quello che fa ``nuova_identita``.
    Nella prova del 30/09/2026, cinque download su cinque sono passati al
    primo colpo, a 1-2 MB/s.
"""
from __future__ import annotations

import atexit
import os
import socket
import subprocess
import tarfile
import tempfile
import threading
import time

import requests

from server.config import paths
from server.utils.console import setup_logger

log = setup_logger('tor', 'tor.log')

CARTELLA = paths.locale('tor')
ESEGUIBILE = os.path.join(CARTELLA, 'tor', 'tor.exe')
DATI = os.path.join(CARTELLA, 'dati')
_INDICE = ('https://aus1.torproject.org/torbrowser/update_3/release/'
           'download-windows-x86_64.json')
_ARCHIVIO = ('https://dist.torproject.org/torbrowser/{v}/'
             'tor-expert-bundle-windows-x86_64-{v}.tar.gz')

# Quanto aspettare che Tor sia pronto prima di arrendersi. Il primo avvio
# scarica l'elenco dei nodi e ci mette di piu'; dopo, pochi secondi.
ATTESA = 120

_pronto = threading.Event()
_serratura = threading.Lock()
_stato = {'fase': 'spento', 'errore': '', 'socks': 0, 'controllo': 0}
_processo: subprocess.Popen | None = None
_ultima_identita = 0.0


def stato() -> dict:
    """Per la pagina: 'spento', 'avvio', 'pronto' o 'errore', e il perche'."""
    return {'fase': _stato['fase'], 'errore': _stato['errore']}


def _porta_libera() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def installa() -> None:
    """Scarica e scompatta il Tor Expert Bundle, se non c'e' gia'."""
    if os.path.isfile(ESEGUIBILE):
        return
    os.makedirs(CARTELLA, exist_ok=True)
    versione = requests.get(_INDICE, timeout=30).json()['version']
    log.info('Scarico Tor %s', versione)
    risposta = requests.get(_ARCHIVIO.format(v=versione), timeout=120)
    risposta.raise_for_status()
    with tempfile.TemporaryFile() as f:
        f.write(risposta.content)
        f.seek(0)
        with tarfile.open(fileobj=f, mode='r:gz') as tar:
            tar.extractall(CARTELLA, filter='data')
    if not os.path.isfile(ESEGUIBILE):
        raise RuntimeError('Tor scaricato, ma manca tor.exe')


def _avvia() -> None:
    global _processo
    try:
        _stato['fase'] = 'avvio'
        installa()
        os.makedirs(DATI, exist_ok=True)
        socks, controllo = _porta_libera(), _porta_libera()
        geoip = os.path.join(CARTELLA, 'data')
        _processo = subprocess.Popen(
            [ESEGUIBILE,
             '--SocksPort', f'127.0.0.1:{socks}',
             '--ControlPort', f'127.0.0.1:{controllo}',
             '--CookieAuthentication', '1',
             '--DataDirectory', DATI,
             '--GeoIPFile', os.path.join(geoip, 'geoip'),
             '--GeoIPv6File', os.path.join(geoip, 'geoip6'),
             # Se il programma si chiude male, Tor se ne accorge e si chiude
             # anche lui, invece di restare appeso fra i processi.
             '__OwningControllerProcess', str(os.getpid())],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        atexit.register(ferma)
        for riga in _processo.stdout:
            log.debug(riga.rstrip())
            if 'Bootstrapped 100%' in riga:
                _stato.update(socks=socks, controllo=controllo, fase='pronto')
                _pronto.set()
                log.info('Tor pronto sulla porta %d', socks)
                break
        else:
            raise RuntimeError('Tor si e\' chiuso prima di collegarsi')
        # Il resto dei messaggi va letto comunque, o il tubo si riempie e
        # Tor si blocca.
        for riga in _processo.stdout:
            log.debug(riga.rstrip())
    except Exception as e:                  # noqa: BLE001
        log.error('Tor non avviato: %s', e)
        _stato.update(fase='errore', errore=str(e)[:200])
        _pronto.set()


def avvia_in_sottofondo() -> None:
    """Avvia Tor una volta sola, senza aspettarlo."""
    with _serratura:
        if _stato['fase'] in ('spento', 'errore'):
            _pronto.clear()
            _stato.update(fase='avvio', errore='')
            threading.Thread(target=_avvia, daemon=True, name='tor').start()


def proxy() -> str:
    """L'indirizzo del proxy per yt-dlp; aspetta che Tor sia pronto.

    Se Tor non c'e', solleva un errore invece di restituire None: chi chiama
    non deve poter andare su internet a viso scoperto per distrazione.
    """
    avvia_in_sottofondo()
    if not _pronto.wait(ATTESA) or _stato['fase'] != 'pronto':
        raise RuntimeError(
            'Tor non e\' raggiungibile, quindi non scarico per non mostrare il '
            'tuo IP. ' + (_stato['errore'] or 'Controlla la connessione e riprova.'))
    return f"socks5h://127.0.0.1:{_stato['socks']}"


def proxies() -> dict:
    """Lo stesso proxy, nella forma che vuole requests."""
    p = proxy()
    return {'http': p, 'https': p}


def bloccato_da_youtube(errore: object) -> bool:
    """True se YouTube ha riconosciuto il nodo d'uscita e chiede di accedere."""
    testo = str(errore).lower()
    return 'not a bot' in testo or 'sign in to confirm' in testo


def nuova_identita() -> None:
    """Chiede a Tor un altro nodo d'uscita. Tor ne concede uno ogni ~10 s."""
    global _ultima_identita
    if _stato['fase'] != 'pronto':
        return
    attesa = 10 - (time.monotonic() - _ultima_identita)
    if attesa > 0:
        time.sleep(attesa)
    try:
        with open(os.path.join(DATI, 'control_auth_cookie'), 'rb') as f:
            biscotto = f.read().hex()
        with socket.create_connection(('127.0.0.1', _stato['controllo']), timeout=10) as s:
            s.sendall(f'AUTHENTICATE {biscotto}\r\nSIGNAL NEWNYM\r\nQUIT\r\n'.encode())
            risposta = s.recv(256)
        log.info('Nuova identita\' Tor: %s', risposta.decode(errors='replace').split()[:2])
    except OSError as e:
        log.warning('Nuova identita\' non ottenuta: %s', e)
    _ultima_identita = time.monotonic()


def ferma() -> None:
    if _processo and _processo.poll() is None:
        _processo.terminate()
