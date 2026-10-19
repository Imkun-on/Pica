"""Il testo sincronizzato, cercato su LRCLIB.

E' la cosa che distingue un file scaricato da uno comprato: il testo in
formato LRC, con il tempo su ogni riga, scritto DENTRO il file. Sul telefono
scorre da solo mentre il brano suona, e nessuno deve piu' cercarlo a parte.

LRCLIB non chiede chiavi ne' registrazioni, e la ricerca si fa con artista e
titolo. Per questo meta' del modulo serve a ricavare artista e titolo da un
titolo di YouTube, che e' un problema piu' difficile di quanto sembri: fra
``(Official Video)``, ``[HD]`` e i trattini decorativi, la stessa canzone
arriva scritta in dieci modi. Si provano quindi piu' forme, dalla piu'
affidabile, e un testo sincronizzato vince sempre su uno semplice.

Quando LRCLIB ha solo il testo semplice, i tempi li mette
``server.audio.sincronia``, ascoltando il brano.
"""
from __future__ import annotations

import re

import requests

from server.config.settings import REQUEST_TIMEOUT
from server.utils import tor
from server.utils.console import setup_logger

log = setup_logger('audiodex', 'audiodex.log')

# API pubblica e gratuita di testi sincronizzati (formato LRC), senza chiave.
LRCLIB_API = 'https://lrclib.net/api'

# Oltre questa differenza di durata (in secondi) il testo e' di un'altra
# versione: live, remix, edit radiofonico. Un testo sincronizzato di un'altra
# versione scorre sfasato, ed e' peggio che non averlo.
SCARTO_DURATA = 10

HEADERS = {'User-Agent': 'Pica/1.0 (https://github.com/Imkun-on/Pica)'}

_DECORAZIONI = ('official|video|lyric|audio|visualizer|hd|4k|remaster|m/?v'
                '|testo|videoclip')


def _clean_track_title(title: str) -> str:
    """Ripulisce il titolo YouTube dalle decorazioni non musicali.

    Rimuove le parentesi tipo '(Official Video)', '[HD]', '(Lyrics)' ecc.,
    che farebbero fallire la ricerca del testo nei database di lyrics.
    """
    cleaned = re.sub(
        r'[\(\[][^)\]]*(' + _DECORAZIONI + r')[^)\]]*[\)\]]',
        '', title, flags=re.IGNORECASE,
    )
    # Le decorazioni senza parentesi, in coda: «Brano | Official Video».
    cleaned = re.sub(r'\s*[|/]\s*(official|lyric|video|audio).*$', '', cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip(' -_|')
    return cleaned or title


def _senza_ospiti(testo: str) -> str:
    """Toglie «feat. X», «ft. X», «(with X)»: su LRCLIB spesso non ci sono."""
    testo = re.sub(r'[\(\[]\s*(feat|ft|with)\.?\s[^)\]]*[\)\]]', '', testo,
                   flags=re.IGNORECASE)
    testo = re.sub(r'\s(feat|ft)\.?\s.*$', '', testo, flags=re.IGNORECASE)
    return testo.strip(' "\'“”-')


def _canale(uploader: str | None) -> str:
    """Il nome del canale senza « - Topic» e «VEVO», che non sono l'artista.

    I canali VEVO scrivono il nome tutto attaccato («LuisFonsiVEVO»): lo si
    riapre sulle maiuscole, «Luis Fonsi».
    """
    nome = (uploader or '').removesuffix(' - Topic').strip()
    if nome.endswith('VEVO'):
        nome = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', nome.removesuffix('VEVO'))
    return nome.strip()


def _split_artist_title(title: str, uploader: str | None = None) -> tuple[str, str]:
    """Separa artista e brano dal titolo di un video YouTube.

    I titoli musicali sono quasi sempre nel formato 'Artista - Brano
    (decorazioni)': dopo la pulizia delle decorazioni, la parte prima del
    trattino è l'artista. Se il formato manca, come artista si usa il nome
    del canale. Restituisce (artista, brano); artista può essere stringa vuota.
    """
    cleaned = _clean_track_title(title)
    for trattino in (' - ', ' – ', ' — '):
        if trattino in cleaned:
            artist, track = cleaned.split(trattino, 1)
            return artist.strip(), track.strip()
    return _canale(uploader), cleaned


def _candidati(title: str, uploader: str | None, artista_yt: str | None,
               brano_yt: str | None) -> list[tuple[str, str]]:
    """Le coppie (artista, brano) da provare, dalla piu' affidabile.

    Un solo tentativo falliva spesso per un dettaglio: un «feat.» che su
    LRCLIB non c'e', il canale «ArtistaVEVO», un titolo scritto «Brano -
    Artista» al contrario. Si provano tutte le forme ragionevoli; la prima
    che trova un testo sincronizzato vince.
    """
    coppie: list[tuple[str, str]] = []
    # YouTube Music e i canali « - Topic» dichiarano artista e brano: sono i
    # dati migliori, quando ci sono.
    if artista_yt and brano_yt:
        coppie.append((artista_yt.split(',')[0].strip(), brano_yt))
    artist, track = _split_artist_title(title, uploader)
    coppie.append((artist, track))
    coppie.append((_senza_ospiti(artist), _senza_ospiti(track)))
    canale = _canale(uploader)
    if canale and canale.lower() != artist.lower():
        coppie.append((canale, _senza_ospiti(track)))
    # «Brano - Artista»: capita piu' di quanto si creda.
    if artist:
        coppie.append((_senza_ospiti(track), _senza_ospiti(artist)))

    visti, uniche = set(), []
    for a, b in coppie:
        chiave = (a.lower(), b.lower())
        if b and chiave not in visti:
            visti.add(chiave)
            uniche.append((a, b))
    return uniche


def _vicina(item: dict, duration: float | None) -> bool:
    """Vero se la durata del testo e' compatibile con quella del brano."""
    if not duration or not item.get('duration'):
        return True
    return abs(item['duration'] - duration) <= SCARTO_DURATA


def _get(params: dict) -> dict | None:
    resp = requests.get(f'{LRCLIB_API}/get', params=params, headers=HEADERS,
                        timeout=REQUEST_TIMEOUT, proxies=tor.proxies())
    return resp.json() if resp.status_code == 200 else None


def _search(params: dict) -> list[dict]:
    resp = requests.get(f'{LRCLIB_API}/search', params=params, headers=HEADERS,
                        timeout=REQUEST_TIMEOUT, proxies=tor.proxies())
    return resp.json() if resp.status_code == 200 else []


def cerca_testo(title: str, artist: str, duration: int | float | None,
                artista_yt: str | None = None, brano_yt: str | None = None
                ) -> tuple[str | None, str | None]:
    """Cerca su LRCLIB il testo sincronizzato (karaoke) di una traccia.

    Restituisce (testo_sincronizzato_lrc, testo_semplice); entrambi None se
    non trovato. Per ogni coppia (artista, brano) candidata tenta prima la
    corrispondenza esatta con la durata (``/get``), poi la ricerca
    (``/search``) scartando i risultati di durata troppo diversa. Il primo
    testo semplice trovato si tiene da parte: si restituisce da solo se alla
    fine nessuna forma porta a uno sincronizzato.
    Qualsiasi errore di rete viene solo loggato: i testi sono un extra, mai
    un motivo di fallimento.
    """
    semplice: str | None = None

    def valuta(item: dict | None) -> str | None:
        """Il testo sincronizzato dell'item, ricordando quello semplice."""
        nonlocal semplice
        if not item or item.get('instrumental') or not _vicina(item, duration):
            return None
        if not semplice and item.get('plainLyrics'):
            semplice = item['plainLyrics']
        return item.get('syncedLyrics') or None

    try:
        coppie = _candidati(title, artist, artista_yt, brano_yt)
        for a, b in coppie:
            if a and duration:
                trovato = valuta(_get({'artist_name': a, 'track_name': b,
                                       'duration': int(duration)}))
                if trovato:
                    return trovato, semplice
            params = {'track_name': b, 'artist_name': a} if a else {'track_name': b}
            for item in _search(params):
                trovato = valuta(item)
                if trovato:
                    return trovato, semplice
        # Ultima spiaggia: la ricerca a testo libero, che perdona l'ordine
        # delle parole e i nomi scritti in modo diverso.
        # Per ultimo il solo titolo: e' la durata a scartare le omonime.
        a, b = coppie[0] if coppie else ('', _clean_track_title(title))
        for q in dict.fromkeys((f'{a} {b}'.strip(), _senza_ospiti(b))):
            for item in _search({'q': q}):
                trovato = valuta(item)
                if trovato:
                    return trovato, semplice
    except Exception as e:                  # noqa: BLE001
        log.debug("LRCLIB errore per '%s': %s", title, e)
    return None, semplice
