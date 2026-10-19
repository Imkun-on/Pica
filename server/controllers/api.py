"""Cosa la pagina puo' chiedere, e nient'altro.

La regola di questo file
    Qui non si decide niente di importante. Si riceve una richiesta, si
    controlla che abbia senso, si chiama chi la sa eseguire, e si traduce la
    risposta in qualcosa che la pagina possa mostrare. Se in un metodo qui
    dentro compare una decisione vera - quale preset abbia senso, se un ordine
    di tracce ci stia su un CD, se un URL sia una playlist - e' nel posto
    sbagliato: sta gia' nei motori, ed e' li' che deve restare, o si finisce
    con due risposte diverse alla stessa domanda.

Ogni metodo risponde con un dizionario
    Sempre, e sempre con almeno ``ok``. La pagina non deve mai ricevere
    un'eccezione Python: in JavaScript arriverebbe come un rifiuto senza
    spiegazione, e non c'e' una console aperta in cui andarla a leggere.

I motori si caricano quando servono
    I quattro ``_motore()``, ``_burndex()``, ``_pixdex()``, ``_clipdex()`` non
    importano niente finche' nessuno preme un bottone. E' il motivo per cui la
    finestra si apre in meno di un secondo invece che in cinque: yt-dlp, COM e
    il resto arrivano al primo uso, mentre chi guarda sta gia' leggendo la
    schermata.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import sys
import threading
import traceback

import webview

from server.config import i18n
from server.config.paths import (
    cartella_audio as _audio, cartella_montaggi as _montaggi,
    cartella_rimasterizzati as _rimasterizzati, cartella_video as _video,
    dati as _dati, riordina_risultati)
from server.config.settings import FORMATI_AUDIO as _FORMATI_AUDIO
from server.config.strings.app import TESTI as TESTI_APP
from server.config.strings.audio import TESTI as TESTI_AUDIO
from server.controllers import bridge
from server.state import progress as _spia
from server.state.jobs import Posto
from server.config.strings.errori import TESTI as TESTI_DIAGNOSI
from server.utils.contract import ErroreSpiegato, classifica_errore
from server.utils.media import VIDEO_EXTS as _VIDEO_EXTS
from server.utils.text import leggi_tempo as _leggi_tempo

# pywebview 6 ha rinominato le costanti dei selettori di file. Si prendono le
# nuove quando esistono e si ricade sulle vecchie: cosi' il programma non
# stampa avvisi di deprecazione sulle versioni recenti e continua a girare su
# quelle precedenti.
_DLG_CARTELLA = getattr(getattr(webview, 'FileDialog', None), 'FOLDER',
                        getattr(webview, 'FOLDER_DIALOG', 2))
_DLG_APRI = getattr(getattr(webview, 'FileDialog', None), 'OPEN',
                    getattr(webview, 'OPEN_DIALOG', 10))
_DLG_SALVA = getattr(getattr(webview, 'FileDialog', None), 'SAVE',
                     getattr(webview, 'SAVE_DIALOG', 30))


# ── Dalla fase finita alla fase in corso ─────────────────────────────────────
#
# AudioDex riferisce la fase *conclusa*: ``on_phase(nome)`` si legge "la
# traccia ha superato la fase indicata", e infatti ``phase('convert')`` sta
# subito sotto il commento "FFmpeg ha finito". La pastiglia accanto alla traccia
# dice invece cosa sta succedendo adesso, che e' l'unica cosa utile mentre si
# guarda: passando il nome cosi' com'e', diceva "converto" a conversione finita
# e "scrivo i tag" a lavoro concluso - un passo indietro su tutta la riga.
#
# Fra le due letture c'e' esattamente un passo, ed e' questa tabella. 'tag' e'
# l'ultima: dopo di lei non c'e' una fase successiva da annunciare, e un istante
# dopo arriva comunque tracciaFinita a scrivere l'esito.
# 'lyrics_plain' e' l'eccezione: la manda download_single *prima* di mettersi
# ad ascoltare il brano per dare i tempi a un testo che non li ha, perche' e'
# un passo di minuti e la pastiglia deve dirlo mentre succede.
_DOPO = {'download': 'convert', 'convert': 'lyrics', 'lyrics': 'tag', 'tag': 'tag',
         'lyrics_plain': 'sync'}


# ── Moduli del motore, caricati alla prima richiesta ──────────────────────────
# Importare AudioDex costa qualche secondo (yt-dlp non e' leggero): farlo qui
# invece che all'avvio fa comparire la finestra subito, che e' la prima cosa
# che si giudica di un programma.
_audiodex = None


_burn = None


_pix = None


_clip = None


def _motore():
    global _audiodex
    if _audiodex is None:
        from server.services import audio as _ad
        _audiodex = _ad
    return _audiodex


def _burndex():
    global _burn
    if _burn is None:
        from server import burn as _bd
        _burn = _bd
    return _burn


def _pixdex():
    global _pix
    if _pix is None:
        from server import video as _px
        _pix = _px
    return _pix


def _clipdex():
    global _clip
    if _clip is None:
        from server.video import edit as _cd
        _clip = _cd
    return _clip


def _apri_col_sistema(percorso: str) -> None:
    """Apre un file o una cartella col programma che il sistema gli associa."""
    if sys.platform == 'win32':
        os.startfile(percorso)          # noqa: S606 - e' quello che si vuole
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', percorso])


# Il file di log di ciascuna sezione. I nomi sono quelli che i motori danno ai
# propri logger in setup_logger(), e vanno tenuti allineati a quelli.
_LOG_DI = {'audio': 'audiodex', 'burn': 'burndex', 'pix': 'pixdex', 'clip': 'clipdex',
           # Video, Sottotitoli e Doppiaggio scrivono nel log di audiodex (lo
           # stesso dei loro moduli): senza una voce qui righe ed errori sparivano.
           'video': 'audiodex', 'sub': 'audiodex', 'dop': 'audiodex'}


class Diario(io.TextIOBase):
    """Raccoglie cio' che i moduli stampano e lo scrive nel log su file.

    Prima queste righe finivano in una scheda dentro la finestra. Non ci vanno
    piu', ed e' il punto: erano il racconto tecnico, riga per riga, dello
    stesso lavoro che la barra di avanzamento racconta meglio in una riga
    sola. Peggio, quando qualcosa andava storto la riga che contava finiva
    sepolta sotto le altre invece di farsi notare - adesso quella apre una
    finestra e le altre restano qui.

    «Qui» e' ``logs/<sezione>.log``, che i motori scrivono gia' per conto
    loro: questo non aggiunge un secondo diario, si limita a versare nello
    stesso file anche cio' che i motori *stampano* invece di registrare.
    Quindi non si e' perso niente, e chi va a cercare trova tutto in un posto
    solo.

    I moduli del motore parlano con Rich, che colora scrivendo sequenze di
    controllo ANSI: dentro un file di testo diventerebbero caratteri strani in
    mezzo alle righe, quindi si tolgono.
    """

    _ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

    def __init__(self, dove: str):
        self._log = logging.getLogger(_LOG_DI.get(dove, 'pica'))
        self._resto = ''
        self._lucchetto = threading.Lock()

    def write(self, s: str) -> int:      # type: ignore[override]
        if not s:
            return 0
        with self._lucchetto:
            self._resto += s
            while '\n' in self._resto:
                riga, self._resto = self._resto.split('\n', 1)
                self._manda(riga)
        return len(s)

    def flush(self) -> None:
        with self._lucchetto:
            if self._resto:
                self._manda(self._resto)
                self._resto = ''

    def _manda(self, grezza: str) -> None:
        testo = self._ANSI.sub('', grezza).rstrip()
        if testo:
            self._log.info(testo)


def _riporta_avanzamento(descrizione: str, fatti: float, totale: float | None) -> None:
    """Porta alla pagina un avanzamento riferito da un motore.

    E' l'unico traduttore fra il modo in cui i motori contano - tracce,
    fotogrammi, settori - e la barra: qui si decide soltanto come mostrarlo,
    mai quanto sia avanzato il lavoro.
    """
    if not totale:
        # Un motore che non sa quanto manca non deve far finta di saperlo:
        # resta la scritta, la barra non si muove.
        bridge.verso_pagina('avanzaLavoro', 0, 0, None, descrizione)
        return
    bridge.verso_pagina('avanzaLavoro', int(fatti), int(totale),
                  min(fatti / totale, 1.0), descrizione)


class Api:
    """I metodi che la pagina puo' chiamare, e nient'altro.

    Ogni metodo restituisce un dizionario con almeno ``ok``: la pagina non
    deve mai ricevere un'eccezione Python, che in JavaScript arriverebbe come
    un rifiuto senza spiegazione.
    """

    def __init__(self):
        # Il posto di lavoro e' uno solo per tutto il programma, e la sua
        # meccanica sta in server/state/jobs.py: qui la si usa e basta.
        self._posto = Posto()
        # Cio' che l'ultima analisi ha trovato, cosa e' arrivato e dove: uno
        # per sezione. Erano condivisi, e un download in Video cambiava sotto
        # i piedi la coda che Audio stava per scaricare.
        self._lotti: dict[str, dict] = {
            sez: {'risultati': [], 'playlist': '', 'pronti': {}}
            for sez in ('audio', 'video')}

    def _lotto(self, sezione: str | None) -> dict:
        return self._lotti['video' if sezione == 'video' else 'audio']

    # ── Avvio ────────────────────────────────────────────────────────────────

    def avvio(self) -> dict:
        # Le cartelle di prima (``musica``, ``montaggi``...) si svuotano nella
        # struttura di adesso: una volta sola, poi non c'e' piu' niente da
        # spostare e la chiamata costa un ``isdir``.
        try:
            riordina_risultati()
        except OSError:
            pass
        return self._avvio()

    def _avvio(self) -> dict:
        """Tutto cio' che serve alla pagina per disegnarsi la prima volta.

        Qui accanto c'era anche ``dipinta()``, che la pagina chiamava al primo
        fotogramma davvero composto per far togliere a Python l'immagine di
        caricamento di PyInstaller. Quell'immagine non c'e' piu' - l'attesa
        sta tutta dentro la pagina, sotto il velo - e con lei se n'e' andato
        tutto il giro: mostrare la finestra, contare i fotogrammi, la scadenza
        di sicurezza che la scopriva comunque. La finestra nasce visibile e
        massimizzata, e non c'e' niente da scoprire.
        """
        # Tor parte subito, mentre si incolla il primo link: quando serve e'
        # gia' pronto, invece di far aspettare il primo download.
        from server.utils import ffmpeg, tor
        tor.avvia_in_sottofondo()
        # Lo stesso per FFmpeg: chi non ce l'ha lo riceve adesso, in sottofondo.
        ffmpeg.avvia_in_sottofondo()
        return {
            'ok': True,
            # I tre cataloghi che la pagina puo' avere bisogno di dire, e solo
            # quelli: i testi di AudioDex, quelli dell'interfaccia, e le frasi
            # con cui si spiega un guasto. I cataloghi di BurnDex, PixDex e
            # ClipDex restano fuori: sono le loro schermate a terminale, piene
            # di markup di Rich, e la finestra non ne dice una riga.
            'testi': {**TESTI_AUDIO, **TESTI_APP, **TESTI_DIAGNOSI},
            'sfondo': self._video_sfondo(),
        }

    @staticmethod
    def stato_tor() -> dict:
        """Per la spia nella barra laterale: se l'IP e' nascosto, o perche' no."""
        from server.utils import tor
        return tor.stato()

    @staticmethod
    def stato_ffmpeg() -> dict:
        """Per la spia accanto: se FFmpeg si sta ancora scaricando, e quanto manca."""
        from server.utils import ffmpeg
        return ffmpeg.stato()

    @staticmethod
    def _video_sfondo() -> str:
        """Indirizzo del video di sfondo, se e' gia' sul disco.

        Nessuno lo scarica: se qualcuno lo ha messo li' si mostra, altrimenti
        restano i gradienti animati del tema - che non sono un ripiego mesto
        ma uno sfondo a sua volta guardabile, ed e' il motivo per cui il file
        e' rimasto facoltativo invece di diventare un download all'avvio.
        """
        percorso = _dati('assets', 'cyberpunk-citadel.mp4')
        try:
            if os.path.getsize(percorso) < 1_000_000:
                return ''
        except OSError:
            return ''
        return Api._url_file(percorso)

    # Dove si apre ogni finestra di scelta: nella cartella dei risultati della
    # sezione, che e' quasi sempre dove sta cio' che si cerca.
    _PARTENZE = {'audio': _audio, 'video': _video, 'rimasterizza': _rimasterizzati}

    def _partenza(self, dove: str) -> str:
        funzione = self._PARTENZE.get(dove or '')
        return funzione() if funzione else ''

    def scegli_cartella(self, dove: str = '') -> dict:
        """Apre il selettore di cartelle del sistema."""
        try:
            scelta = bridge.attuale().create_file_dialog(
                _DLG_CARTELLA, directory=self._partenza(dove))
        except Exception as exc:
            return {'ok': False, 'errore': str(exc)}
        return {'ok': True, 'cartella': scelta[0] if scelta else ''}

    # ── Download: Audio e Video ──────────────────────────────────────────────
    #
    # Le due sezioni fanno lo stesso lavoro con due esiti diversi, e passano
    # dagli stessi due metodi. La pagina chiama ``analizza`` col link e le
    # opzioni: un brano solo si scarica di fila, nello stesso lavoro; una
    # playlist o un album fanno aprire alla pagina la finestra coi brani da
    # spuntare, e la scelta torna con ``scarica``.

    def analizza(self, testo: str, sezione: str = 'audio',
                 opzioni: dict | None = None) -> dict:
        """Guarda cosa c'e' dietro un link, senza scaricare nulla.

        Torna subito: il lavoro vero avviene in un thread, e la pagina viene
        avvisata a cose fatte. Cosi' la finestra non si congela nei secondi in
        cui yt-dlp interroga YouTube.
        """
        sezione = 'video' if sezione == 'video' else 'audio'
        bridge.entra(sezione)
        testo = (testo or '').strip()
        if not testo:
            return {'ok': False, 'errore': i18n.t('err.no_input')}
        # Il posto si prende dopo i controlli, non prima: un modulo compilato
        # male non deve lasciare il programma occupato senza che giri niente.
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}

        self._in_thread(self._analizza_davvero, testo,
                        {**(opzioni or {}), 'sezione': sezione})
        return {'ok': True, 'avviato': True}

    def _analizza_davvero(self, testo: str, opzioni: dict) -> None:
        ad = _motore()
        lotto = self._lotto(opzioni.get('sezione'))
        lotto['playlist'] = ''
        album = None
        if ad.e_playlist(testo):
            nome, trovati, _meta = ad.get_playlist_entries(testo)
            lotto['playlist'] = nome or 'Playlist'
            titolo = i18n.t('res.playlist', n=len(trovati), titolo=nome)
        else:
            info = ad.get_video_details(testo)
            trovati = [ad.entry_da_info(info, testo)] if info else []
            titolo = i18n.t('res.single',
                            titolo=(info or {}).get('title', '')) if info else ''
            # Un album caricato come video unico si riconosce dai capitoli (la
            # scaletta coi tempi nella descrizione): se ci sono e sembrano
            # davvero brani, si chiede se dividerlo invece di partire subito.
            # Solo in Audio: un video diviso in pezzi non serve a nessuno.
            if info and opzioni.get('sezione') != 'video':
                album = self._album(info, testo)
                if album:
                    trovati[0]['capitoli'] = album

        lotto['risultati'] = trovati or []
        if not lotto['risultati']:
            raise ErroreSpiegato(i18n.t('err.nothing'))
        bridge.verso_pagina('mostraScelta', {
            'titolo': titolo,
            'playlist': bool(lotto['playlist']),
            'voci': [{
                'titolo': v.get('title', ''),
                'durata': self._durata(v.get('duration')),
                'canale': v.get('uploader') or v.get('channel') or '',
                'miniatura': self._miniatura(v.get('id')),
            } for v in lotto['risultati']],
            'album': [{
                'titolo': c['titolo'],
                'inizio': c['inizio'],
                'durata': c['fine'] - c['inizio'],
            } for c in album] if album else None,
        })
        # Un video solo parte subito, intero; se e' un album aspetta la
        # risposta della finestra, che torna con ``scarica``. Con ``attendi``
        # non parte niente: la pagina mette in coda quello che ha trovato, e a
        # scaricare ci pensa il suo bottone.
        if not lotto['playlist'] and not album and not opzioni.get('attendi'):
            self._scarica_davvero({**opzioni, 'scelti': [0], 'dividi': False})

    # ── Download ─────────────────────────────────────────────────────────────

    def scarica(self, opzioni: dict) -> dict:
        """Avvia il download di cio' che l'analisi ha trovato."""
        bridge.entra('video' if opzioni.get('sezione') == 'video' else 'audio')
        if not self._lotto(opzioni.get('sezione'))['risultati']:
            return {'ok': False, 'errore': i18n.t('err.nothing')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}

        self._in_thread(self._scarica_davvero, opzioni)
        return {'ok': True, 'avviato': True}

    def _scarica_davvero(self, opzioni: dict) -> None:
        """Scarica le tracce scelte, raccontando alla pagina cosa succede a
        ciascuna mentre succede.

        Non si usa ``download_batch``, che disegna da se' le proprie barre con
        Rich: qui il ciclo lo si tiene in mano per poter dire alla pagina, per
        ogni singola traccia, se sta scaricando, convertendo, cercando il
        testo o scrivendo i tag. E' la differenza fra una barra che gira e
        un'interfaccia che dice cosa sta facendo.

        ``download_single`` protegge ogni uso di Rich con un controllo, quindi
        passandogli ``progress=None`` lavora in silenzio.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        ad = _motore()
        video = opzioni.get('sezione') == 'video'
        lotto = self._lotto(opzioni.get('sezione'))
        # Una playlist o un album finiscono in una cartella tutta loro, col
        # loro nome, dentro quella della sezione.
        cartella = _video() if video else _audio()
        # In Audio la destinazione si puo' scegliere, e la cartella della
        # playlist si puo' non volere.
        scelta = (opzioni.get('cartella') or '').strip() if not video else ''
        if scelta and os.path.isdir(scelta):
            cartella = scelta
        # Il formato si sceglie solo in Audio. Un album diviso in tracce resta
        # M4A: e' il solo formato che ``dividi_per_capitoli`` sa taggare.
        formato = 'mp4' if video else (opzioni.get('formato') or 'm4a')
        if formato not in _FORMATI_AUDIO or opzioni.get('dividi'):
            formato = 'mp4' if video else 'm4a'
        ritocchi = None if video else {
            chiave: opzioni.get(chiave) for chiave in
            ('bitrate', 'frequenza', 'mono', 'normalizza')}
        if ritocchi is not None:
            ritocchi['metadati'] = bool(opzioni.get('metadati', True))
            ritocchi['copertina'] = bool(opzioni.get('copertina', True))
        if lotto['playlist'] and (video or opzioni.get('cartella_playlist', True)):
            from server.utils.text import nome_file_pulito
            cartella = os.path.join(cartella, nome_file_pulito(lotto['playlist']))
            os.makedirs(cartella, exist_ok=True)

        scelti = opzioni.get('scelti')
        indici = ([i for i in scelti if 0 <= i < len(lotto['risultati'])]
                  if scelti else list(range(len(lotto['risultati']))))
        if not indici:
            bridge.verso_pagina('mostraRiepilogo',
                          {'testo': i18n.t('err.nothing'), 'ok': False})
            return

        # Cosa e' arrivato e dove, per i bottoni «Apri» della pagina: la pagina
        # chiede per numero di traccia, e i percorsi restano da questa parte.
        lotto['pronti'] = {}

        totale = len(indici)
        fatte = [0]
        bridge.verso_pagina('iniziaLavoro', totale)

        # Quanto e' avanzato il download di ogni traccia ancora in corso, da 0
        # a 1, ricavato dai byte che yt-dlp conta gia' per conto suo.
        #
        # Il peso 0.9 non e' un abbellimento: scaricare i byte e' quasi tutto
        # il lavoro di una traccia, ma non tutto - dopo restano la conversione
        # con FFmpeg, il testo sincronizzato e i tag. Contando i byte per
        # l'intero, la barra arriverebbe in fondo con il programma ancora al
        # lavoro, che e' il difetto peggiore che possa avere una barra. Cosi'
        # invece l'ultimo decimo lo mette solo la traccia davvero finita.
        PESO_BYTE = 0.9
        quote: dict[int, float] = {}
        ultimo_invio = [0.0]
        serratura = threading.Lock()

        def riferisci(forza: bool = False) -> None:
            """Manda alla pagina l'avanzamento complessivo, byte compresi."""
            import time as _time
            with serratura:
                adesso = _time.monotonic()
                # Il ponte con JavaScript non va intasato: con otto download in
                # parallelo yt-dlp chiama decine di volte al secondo, e l'occhio
                # non vede nessuna differenza sotto il decimo di secondo.
                if not forza and adesso - ultimo_invio[0] < 0.12:
                    return
                ultimo_invio[0] = adesso
                parziale = fatte[0] + sum(quote.values()) * PESO_BYTE
            bridge.verso_pagina('avanzaLavoro', fatte[0], totale,
                          min(parziale / totale, 1.0) if totale else 0)

        # I thread del pool non ereditano l'indirizzo di sezione: senza
        # rientrare qui, ogni scheda di un download Video finiva in Audio.
        dove = bridge.qui()

        def una(indice: int) -> dict:
            bridge.entra(dove)
            entry = lotto['risultati'][indice]
            bridge.verso_pagina('tracciaFase', indice, 'download')

            def byte(scaricati: int, totali: int, k=indice) -> None:
                frazione = min(scaricati / totali, 1.0) if totali else 0.0
                # Sotto serratura perche' riferisci() somma questo stesso
                # dizionario: aggiungere una chiave mentre un altro thread lo
                # sta scorrendo fa alzare a Python un RuntimeError, e questa
                # funzione gira dentro il gancio di yt-dlp, dove un'eccezione
                # abortisce un download altrimenti sano.
                with serratura:
                    quote[k] = frazione
                bridge.verso_pagina('tracciaAvanza', k, round(frazione, 4))
                riferisci()

            esito = ad.download_single(
                # Il video e' sempre mp4: l'mkv prendeva il 4K e scaricava
                # molto di piu' per niente.
                entry, cartella, formato,
                ritocchi=ritocchi,
                track_num=indice + 1,
                total_tracks=totale,
                numbered=bool(lotto['playlist']),
                fetch_lyrics=not video and bool(opzioni.get('testi', True)),
                sincronizza=not video and bool(opzioni.get('sincronizza', True)),
                media='video' if video else 'audio',
                dividi=not video and bool(opzioni.get('dividi', False)),
                sottotitoli=(opzioni.get('sottotitoli') or '') if video else '',
                traduci=(opzioni.get('traduci') or '') if video else '',
                on_phase=lambda fase, k=indice: bridge.verso_pagina('tracciaFase', k,
                                                             _DOPO.get(fase, fase)),
                on_progress=byte,
            )
            esito['indice'] = indice
            with serratura:
                fatte[0] += 1
                quote.pop(indice, None)
            file = os.path.join(cartella, esito['file']) if esito.get('file') else ''
            c_era = os.path.isfile(file)
            # Quando e' arrivato il file: l'ora dell'ultima scrittura e' quella
            # in cui il download e' finito, oggi o in un giorno passato.
            if c_era:
                esito['quando'] = self._quando(os.path.getmtime(file))
                lotto['pronti'][indice] = file
            # Il testo per leggerlo mentre si ascolta: quello appena trovato,
            # o per un brano che c'era gia' quello scritto nel suo file.
            testo = ''
            if not video and c_era:
                testo = esito.get('testo') or ''
                if not testo and esito.get('status') == 'skip':
                    from server.audio.tagging import leggi_testo
                    testo = leggi_testo(file)
            bridge.verso_pagina('tracciaFinita', indice, esito.get('status', 'fail'),
                                esito.get('error', ''),
                                self._url_file(file) if c_era else '',
                                esito.get('quando', ''), testo,
                                # Per la libreria: quanto pesa e in che formato.
                                os.path.getsize(file) if c_era else 0,
                                os.path.splitext(file)[1].lstrip('.').lower())
            riferisci(forza=True)
            return esito

        esiti: list[dict] = []
        # Tre download alla volta, sempre: di piu' YouTube comincia a
        # rallentare, di meno si aspetta per niente.
        with ThreadPoolExecutor(max_workers=3) as pool:
            lavori = {pool.submit(una, i): i for i in indici}
            for lavoro in as_completed(lavori):
                try:
                    esiti.append(lavoro.result())
                except Exception as exc:      # noqa: BLE001
                    indice = lavori[lavoro]
                    bridge.verso_pagina('tracciaFinita', indice, 'fail', str(exc))
                    esiti.append({'status': 'fail', 'indice': indice,
                                  'title': lotto['risultati'][indice].get('title', ''),
                                  'error': str(exc)})

        tot = len(esiti)
        falliti = sum(1 for e in esiti if e.get('status') == 'fail')
        # I thread finiscono in ordine sparso: l'elenco torna in quello della playlist.
        in_ordine = sorted(esiti, key=lambda e: e.get('indice', 0))
        gia = [{'titolo': e.get('title', ''), 'quando': e.get('quando', '')}
               for e in in_ordine if e.get('status') == 'skip']
        # I non riusciti, ognuno con la sua causa: in italiano se il guasto e'
        # di una famiglia nota, altrimenti com'e' arrivato.
        errori = []
        for e in in_ordine:
            if e.get('status') != 'fail':
                continue
            grezzo = re.sub(r'^ERROR:\s*(\[[^\]]+\]\s*[\w-]+:\s*)?', '',
                            str(e.get('error') or '')).strip()
            spiegato = classifica_errore(grezzo)
            errori.append({'titolo': e.get('title', ''),
                           'causa': grezzo if spiegato == i18n.t('err.unknown') and grezzo
                           else spiegato})
        cosa = ('video' if video else 'brano') if tot == 1 else ('video' if video else 'brani')
        if falliti:
            testo = i18n.t('done.summary', ok=tot - falliti, tot=tot, falliti=falliti)
        elif len(gia) == tot:
            testo = i18n.t('done.uno.gia' if tot == 1 else 'done.tutti.gia', tot=tot, cosa=cosa)
        elif tot == 1:
            testo = i18n.t('done.uno', cosa=cosa)
        else:
            testo = i18n.t('done.tutti', tot=tot, cosa=cosa)
        if gia and len(gia) < tot:
            testo += ' ' + i18n.t('done.gia', n=len(gia))
        bridge.verso_pagina('mostraRiepilogo', {
            'testo': testo,
            'ok': falliti == 0,
            'gia': gia,
            'errori': errori,
            'finestra': True,
        })

    # ── La libreria di Audio ─────────────────────────────────────────────────

    def libreria(self) -> dict:
        """I brani gia' scaricati, dal piu' recente: quelli che la sezione
        Audio mostra all'apertura.

        Vengono dal registro dei download, ma solo quelli il cui file c'e'
        ancora: un brano cancellato dal disco non e' un brano della libreria.
        """
        from server.audio.tagging import leggi_testo
        from server.state import db

        radice = os.path.dirname(os.path.abspath(db.percorso_db()))
        brani = []
        for r in db.get_downloads('audio', limit=500):
            if (r.get('media_kind') or 'audio') != 'audio':
                continue
            file = r.get('file_path') or ''
            if not os.path.isabs(file):
                file = os.path.normpath(os.path.join(radice, file))
            if not os.path.isfile(file):
                continue
            brani.append({
                'titolo': r.get('title') or os.path.basename(file),
                'artista': r.get('artist') or '',
                'album': r.get('collection_name') or '',
                'durata': self._durata(r.get('duration_secs')),
                'formato': os.path.splitext(file)[1].lstrip('.').lower(),
                'peso': os.path.getsize(file),
                'url': self._url_file(file),
                'miniatura': self._miniatura(r.get('source_id')),
                'testo': leggi_testo(file),
            })
        return {'ok': True, 'brani': brani, **self._spazio()}

    def spazio(self) -> dict:
        """Quanto spazio resta sul disco dove finisce l'audio."""
        return {'ok': True, **self._spazio()}

    @staticmethod
    def _spazio() -> dict:
        import shutil
        try:
            return {'libero': shutil.disk_usage(_audio()).free, 'cartella': _audio()}
        except OSError:
            return {'libero': 0, 'cartella': _audio()}

    def apri_cartella(self, dove: str = 'audio', cartella: str = '') -> dict:
        """Apre nel gestore dei file la cartella dei risultati di una sezione,
        o quella indicata."""
        percorso = (cartella or '').strip() or self._partenza(dove)
        if not percorso or not os.path.isdir(percorso):
            return {'ok': False, 'errore': i18n.t('burn.no_folder')}
        _apri_col_sistema(percorso)
        return {'ok': True}

    def apri_scaricato(self, indice: int, sezione: str = 'video') -> dict:
        """Apre un file appena scaricato col programma predefinito di Windows."""
        file = self._lotto(sezione)['pronti'].get(int(indice), '')
        if not os.path.isfile(file):
            return {'ok': False, 'errore': i18n.t('err.nothing')}
        _apri_col_sistema(file)
        return {'ok': True}

    @staticmethod
    def _quando(istante: float) -> str:
        """Data e ora di un file, come le legge una persona: 28/09/2026 alle 22:10."""
        import time as _time
        t = _time.localtime(istante)
        return i18n.t('done.quando', data=_time.strftime('%d/%m/%Y', t),
                      ora=_time.strftime('%H:%M', t))

    # ── Masterizzazione ──────────────────────────────────────────────────────

    def burn_scansiona(self, cartella: str) -> dict:
        """Elenca i brani di una cartella nell'ordine in cui finirebbero sul CD.

        L'ordine non e' alfabetico: e' quello che decide BurnDex, che sa
        riconoscere la numerazione nei nomi e rispettarla. Mostrarne uno
        diverso qui vorrebbe dire mentire su cosa verra' inciso.
        """
        bridge.entra('burn')
        cartella = (cartella or '').strip().strip('"')
        if not os.path.isdir(cartella):
            return {'ok': False, 'errore': i18n.t('burn.no_folder')}

        bd = _burndex()
        percorsi, criterio = bd.ordina_tracce(cartella)
        if not percorsi:
            return {'ok': False, 'errore': i18n.t('burn.no_audio')}

        durate = [bd.durata_traccia(p) for p in percorsi]

        # Una traccia che ffprobe non sa leggere vale zero settori per
        # _settori_totali, e a quel punto la barra della capienza direbbe che
        # ci sta della roba che non ci sta - proprio nella schermata che serve
        # a decidere se incidere. Masterizzare si fermerebbe comunque (lo fa
        # gia' masterizza_cartella, con il nome del file), ma dopo aver detto
        # il contrario. Meglio dirlo qui, dove si sta ancora scegliendo.
        illeggibili = [os.path.basename(p) for p, d in zip(percorsi, durate) if not d]
        if illeggibili:
            return {'ok': False,
                    'errore': i18n.t('tracklist.unreadable',
                                   files=', '.join(illeggibili))}

        settori = bd.settori_totali(durate)
        minuti = bd.sectors_to_minutes(settori)
        return {
            'ok': True,
            'criterio': i18n.t(criterio) if criterio.startswith('order.') else criterio,
            'minuti': round(minuti, 1),
            'limite': bd.SAFE_MINUTES,
            'ci_sta': minuti <= bd.SAFE_MINUTES,
            # Un album tiene i suoi silenzi, una raccolta di singoli no: lo si
            # dice qui perche' la pagina lo scriva sotto la scaletta.
            'album': bd.e_un_album(percorsi),
            'tracce': [{
                'percorso': p,
                'nome': os.path.basename(p),
                'durata': self._durata(d),
                'peso': round(os.path.getsize(p) / 1024 / 1024, 1),
            } for p, d in zip(percorsi, durate)],
        }

    def burn_unita(self) -> dict:
        """Elenca i masterizzatori collegati. Su sistemi non Windows dice perche' no."""
        bridge.entra('burn')
        if sys.platform != 'win32':
            return {'ok': False, 'errore': i18n.t('burn.only_windows'), 'unita': []}
        try:
            bd = _burndex()
            if not bd._HAS_PYWIN32:
                return {'ok': False, 'errore': i18n.t('burn.no_pywin32'), 'unita': []}
            import pythoncom
            # Ogni CoInitialize vuole il suo CoUninitialize: senza, il conteggio
            # di COM su questo thread - che e' quello della finestra, e vive
            # quanto il programma - cresce a ogni chiamata. E questa viene
            # chiamata a ogni apertura della sezione e a ogni cambio di lingua,
            # non una volta sola.
            pythoncom.CoInitialize()
            try:
                # I dizionari portano via solo stringhe e numeri: gli oggetti
                # COM non escono da qui, quindi si puo' chiudere subito dopo.
                unita = [{'indice': i, 'nome': bd.nome_unita(r)}
                         for i, r in enumerate(bd.elenca_unita())]
            finally:
                pythoncom.CoUninitialize()
            return {'ok': True, 'unita': unita,
                    'errore': '' if unita else i18n.t('burn.no_drive')}
        except Exception as exc:                       # noqa: BLE001
            return {'ok': False, 'errore': str(exc), 'unita': []}

    def burn_masterizza(self, opzioni: dict) -> dict:
        bridge.entra('burn')
        if not (opzioni.get('cartella') or '').strip():
            return {'ok': False, 'errore': i18n.t('burn.no_folder')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        self._in_thread(self._burn_davvero, opzioni)
        return {'ok': True, 'avviato': True}

    def _burn_davvero(self, opzioni: dict) -> None:
        """Prepara l'ordine scelto e passa la palla a BurnDex.

        Se le tracce sono state riordinate, si costruisce una cartella
        temporanea di collegamenti numerati: BurnDex ordina per nome, quindi i
        prefissi impongono l'ordine voluto senza copiare un solo byte e senza
        toccare i file originali.
        """
        import shutil as _shutil
        import tempfile as _tempfile

        bd = _burndex()
        cartella = opzioni['cartella'].strip().strip('"')
        ordine = opzioni.get('ordine') or []

        temporanea = None
        da_incidere = cartella
        originali, _crit = bd.ordina_tracce(cartella)
        if ordine and ordine != [os.path.basename(p) for p in originali]:
            temporanea = _tempfile.mkdtemp(prefix='audiodexapp_burn_')
            cifre = max(2, len(str(len(ordine))))
            for i, nome in enumerate(ordine, 1):
                src = os.path.join(cartella, nome)
                dst = os.path.join(temporanea, f'{i:0{cifre}d} - {nome}')
                try:
                    os.link(src, dst)
                except OSError:
                    _shutil.copy2(src, dst)
            da_incidere = temporanea
            bridge.verso_pagina('nota', i18n.t('burn.reordered'))

        # BurnDex conta gia' tutto quello che serve - tracce misurate,
        # decodificate, scritte - per la barra che disegna a terminale: qui la
        # si ascolta e la si ripete alla pagina. Le fasi si succedono, e ogni
        # fase riparte da zero con il proprio totale: e' la verita', ed e'
        # anche cio' che ci si aspetta guardando masterizzare.
        bridge.verso_pagina('iniziaLavoro', 0)
        try:
            with _spia.ascolta(_riporta_avanzamento):
                from server.services.burn import masterizza_cartella
                # Niente da scegliere: velocita' e unita' automatiche, volume
                # sempre livellato, disco lasciato nell'unita' (lo si toglie a
                # mano). I silenzi ai bordi si rifilano nelle raccolte di
                # singoli e si lasciano negli album (vedi ``e_un_album``).
                from server.utils.console import console as _console
                with _console.capture() as cattura:
                    codice = masterizza_cartella(
                        da_incidere,
                        speed_x=None,
                        dry_run=False,
                        espelli=False,
                        indice_unita=None,
                        livella=True,
                        rifila=not bd.e_un_album(originali),
                    )
                racconto = cattura.get()
                # Nel log come prima: la cattura lo aveva solo trattenuto.
                print(racconto)
                if codice != 0:
                    # Il motore spiega il perche' nelle sue ultime righe.
                    righe = [r.strip() for r in racconto.splitlines() if r.strip()]
                    raise ErroreSpiegato(' '.join([i18n.t('burn.failed')] + righe[-3:]))
        finally:
            if temporanea:
                _shutil.rmtree(temporanea, ignore_errors=True)

    # ── Rimasterizzazione ────────────────────────────────────────────────────

    def pix_analizza(self, percorso: str) -> dict:
        """Diagnosi di un video piu' le risoluzioni possibili, ognuna col suo giudizio.

        Le opzioni non sono un elenco fisso: il fattore di ingrandimento e il
        commento dipendono da *questo* file. E' il punto in cui il programma e'
        piu' onesto - la stessa riga che offre il 4K dice, quando e' il caso,
        che da quella sorgente non aggiunge un solo dettaglio.
        """
        bridge.entra('pix')
        percorso = (percorso or '').strip().strip('"')
        if not os.path.isfile(percorso):
            return {'ok': False, 'errore': i18n.t('err.no_file')}

        px = _pixdex()
        info = px.probe(percorso)
        if not info or not px.e_un_filmato(info):
            return {'ok': False, 'errore': i18n.t('pix.unreadable')}

        problemi, consigliato = px.diagnosi(info)
        automatica = px.altezza_obiettivo(info, None, consigliato)

        def voce(chiave, altezza):
            fattore = px.fattore_ingrandimento(info, altezza)
            _colore, nota = px.giudizio_fattore(fattore)
            return {'chiave': chiave, 'altezza': altezza,
                    'etichetta': i18n.t(chiave), 'fattore': round(fattore, 2),
                    'nota': i18n.t(nota),
                    'livello': ('ok' if fattore <= px.FATTORE_BUONO
                                else 'molle' if fattore <= px.FATTORE_MOLLE else 'finto'),
                    'consigliata': chiave == 'quality.auto'}

        return {
            'ok': True,
            'nome': os.path.basename(percorso),
            # Il video stesso, da guardare nella pagina prima di lavorarci.
            'video': self._url_file(percorso),
            # Per la stima del tempo dei trattamenti con l'AI.
            'larghezza': info['width'], 'altezza': info['height'],
            'fotogrammi': info['frames'] or 0,
            'durata': info['duration'],
            'scheda': (f"{info['width']}×{info['height']}  ·  {info['fps']:.0f} fps"
                       f"  ·  {info['bitrate'] // 1000} kbit/s"
                       f"  ·  {self._durata(info['duration'])}"),
            'problemi': problemi,
            'preset': consigliato,
            'preset_nome': px.PRESETS[consigliato]['nome'](),
            'presets': [{'chiave': k, 'nome': px.PRESETS[k]['nome'](),
                         'desc': px.PRESETS[k]['desc']()}
                        for k in ('pulito', 'standard', 'forte', 'animazione', 'vecchio')]
                       # I trattamenti con l'AI stanno in fondo e non sono mai
                       # quelli consigliati: costano ore, e la scelta di
                       # spenderle spetta a chi guarda (vedi server/video/ai.py).
                       + [{'chiave': k, 'nome': i18n.t(f'pix.{k}.nome'),
                           'desc': i18n.t(f'pix.{k}.desc')}
                          for k in ('ai',)],
            'risoluzioni': [voce('quality.auto', automatica),
                            voce('quality.none', info['height']),
                            voce('quality.hd', 1080),
                            voce('quality.2k', 1440),
                            voce('quality.4k', 2160)],
        }

    def pix_da_link(self, link: str) -> dict:
        """Scarica da YouTube il video da migliorare, poi lo fa analizzare.

        Finisce in ``risultati/Video`` come uno scaricato dalla sezione Video:
        cosi' resta, e l'originale da confrontare col migliorato c'e'.
        """
        bridge.entra('pix')
        link = (link or '').strip()
        if not link:
            return {'ok': False, 'errore': i18n.t('err.no_input')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        self._in_thread(self._pix_scarica, link)
        return {'ok': True, 'avviato': True}

    def _pix_scarica(self, link: str) -> None:
        ad = _motore()
        bridge.verso_pagina('iniziaLavoro', 0)
        bridge.verso_pagina('avanzaLavoro', 0, 0, None, i18n.t('pix.link.analizzo'))
        info = ad.get_video_details(link)
        if not info:
            raise ErroreSpiegato(i18n.t('err.nothing'))
        entry = ad.entry_da_info(info, link)

        def byte(scaricati: int, totali: int) -> None:
            frazione = min(scaricati / totali, 1.0) if totali else None
            bridge.verso_pagina('avanzaLavoro', 0, 0, frazione,
                                i18n.t('pix.link.scarico', titolo=entry['title']))

        esito = ad.download_single(entry, _video(), 'mp4', media='video',
                                   fetch_lyrics=False, on_progress=byte)
        file = os.path.join(_video(), esito.get('file') or '')
        if esito.get('status') == 'fail' or not os.path.isfile(file):
            raise ErroreSpiegato(i18n.t('pix.link.fallito',
                                        causa=classifica_errore(esito.get('error', ''))))
        bridge.verso_pagina('pixScaricato', {'file': file})

    def pix_rimasterizza(self, opzioni: dict) -> dict:
        bridge.entra('pix')
        if not (opzioni.get('file') or '').strip():
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        self._in_thread(self._pix_davvero, opzioni)
        return {'ok': True, 'avviato': True}

    def _pix_ai(self, px, percorso: str, info: dict, preset: str, opzioni: dict) -> None:
        """Il trattamento con Real-ESRGAN: stesso ingresso e stessa uscita
        degli altri, ma un fotogramma alla volta nella rete neurale."""
        import time as _time
        from server.video import ai

        richiesta = opzioni.get('altezza')
        # Senza una scelta, l'AI raddoppia: e' il suo mestiere, e il costo
        # cresce col quadrato del fattore.
        altezza = (int(richiesta) if richiesta not in (None, '', 'auto')
                   else info['height'] * 2)
        dst = px.nome_uscita(percorso, altezza, _rimasterizzati())
        prova = int(opzioni.get('prova') or 0)
        dst = os.path.splitext(dst)[0] + (' [AI prova].mp4' if prova else ' [AI].mp4')
        tagliato = ''
        if prova and info['duration'] > prova:
            # La prova: dieci secondi presi a un terzo del video, dove di
            # solito la sigla e' finita. Si ricodifica senza perdite visibili
            # per tagliare al fotogramma giusto.
            import tempfile as _tempfile
            tagliato = os.path.join(_tempfile.gettempdir(),
                                    f'pica_prova_{os.getpid()}.mp4')
            subprocess.run(
                ['ffmpeg', '-v', 'error', '-nostdin', '-y',
                 '-ss', f"{info['duration'] / 3:.3f}", '-i', percorso, '-t', str(prova),
                 '-c:v', 'libx264', '-crf', '12', '-preset', 'veryfast',
                 '-c:a', 'aac', '-b:a', '192k', tagliato], check=True)
            info = px.probe(tagliato)
            percorso = tagliato

        fase = ['']
        inizio = [None]
        ultimo = [0.0]
        bridge.verso_pagina('iniziaLavoro', info['frames'] or 0)

        def dici(testo: str) -> None:
            fase[0] = testo
            bridge.verso_pagina('avanzaLavoro', 0, 0, None, testo)

        def avanzamento(fatti: int, totale: int) -> None:
            adesso = _time.monotonic()
            if inizio[0] is None:
                inizio[0] = (adesso, fatti)
            if adesso - ultimo[0] < 1.0 and fatti < totale:
                return
            ultimo[0] = adesso
            # Quanto manca, dalla velocita' misurata finora: su un lavoro di
            # ore e' l'unica cosa che interessa davvero.
            testo = fase[0]
            t0, f0 = inizio[0]
            if fatti - f0 >= 3:
                resto = (totale - fatti) * (adesso - t0) / (fatti - f0)
                testo += '  ·  ' + i18n.t('pix.ai.manca', tempo=self._durata(resto) or '<1:00')
            bridge.verso_pagina('avanzaLavoro', fatti, totale,
                                fatti / totale if totale else None, testo)

        ok = False
        try:
            ok = ai.migliora(info, dst, preset, altezza, px.CRF_DEFAULT,
                             avanzamento=avanzamento, dici=dici)
        except Exception as exc:            # noqa: BLE001
            logging.getLogger('pixdex').exception("Miglioramento con l'AI non riuscito")
            raise ErroreSpiegato(i18n.t('pix.ai.fallito', causa=str(exc)[:300])) from exc
        finally:
            if not ok and tagliato and os.path.exists(tagliato):
                os.remove(tagliato)
        if not ok:
            raise ErroreSpiegato(i18n.t('pix.failed'))

        png = ''
        if opzioni.get('confronto', True):
            # Con la prova, il riferimento e' lo spezzone tagliato: lo stesso
            # istante del risultato. Solo dopo lo si cancella.
            png = px.confronto(percorso, dst,
                               os.path.splitext(dst)[0] + ' [confronto].png',
                               max(info['duration'] / 3, 0.0)) or ''
        if tagliato and os.path.exists(tagliato):
            os.remove(tagliato)
        bridge.verso_pagina('pixFinito', {
            'file': os.path.basename(dst),
            # La prova e' uno spezzone: accanto al video intero non starebbe in
            # sincrono, quindi li' il confronto resta l'immagine.
            'video': '' if tagliato else self._url_file(dst),
            'confronto': self._url_file(png) if png else '',
            'testo': i18n.t('pix.done', file=os.path.basename(dst)),
        })

    def _pix_davvero(self, opzioni: dict) -> None:
        px = _pixdex()
        percorso = opzioni['file'].strip().strip('"')
        info = px.probe(percorso)
        if not info or not px.e_un_filmato(info):
            raise ErroreSpiegato(i18n.t('pix.unreadable'))

        preset = opzioni.get('preset') or px.diagnosi(info)[1]
        if preset == 'ai':
            self._pix_ai(px, percorso, info, preset, opzioni)
            return
        richiesta = opzioni.get('altezza')
        altezza = px.altezza_obiettivo(
            info, int(richiesta) if richiesta not in (None, '', 'auto') else None, preset)
        # I tre ritocchi del pannello delle opzioni. Con l'AI non valgono: li'
        # l'immagine la ridisegna la rete, e la catena di filtri non c'e'.
        dettaglio = opzioni.get('dettaglio')
        catena = px.catena_filtri(
            preset, info, altezza,
            rumore=bool(opzioni.get('rumore')),
            stabilizza=bool(opzioni.get('stabilizza')),
            dettaglio=int(dettaglio) if dettaglio not in (None, '') else None)
        dst = px.nome_uscita(percorso, altezza or info['height'], _rimasterizzati())

        totale = info['frames'] or 0
        bridge.verso_pagina('iniziaLavoro', totale)
        ultimo = [0.0]

        def avanzamento(n, tot, velocita):
            import time as _time
            adesso = _time.monotonic()
            if adesso - ultimo[0] < .4 and (not tot or n < tot):
                return
            ultimo[0] = adesso
            bridge.verso_pagina('avanzaLavoro', n, tot or totale or n or 1)

        ok = px.rimasterizza(info, dst, catena, bool(opzioni.get('gpu')),
                             px.CRF_DEFAULT, avanzamento=avanzamento)
        if not ok:
            raise ErroreSpiegato(i18n.t('pix.failed'))

        png = ''
        if opzioni.get('confronto', True):
            png = px.confronto(percorso, dst,
                               os.path.splitext(dst)[0] + ' [confronto].png',
                               max(info['duration'] / 3, 0.0)) or ''
        bridge.verso_pagina('pixFinito', {
            'file': os.path.basename(dst),
            # Il risultato, da confrontare nella pagina col video di partenza.
            'video': self._url_file(dst),
            'confronto': self._url_file(png) if png else '',
            'testo': i18n.t('pix.done', file=os.path.basename(dst)),
        })

    # ── Montaggio ────────────────────────────────────────────────────────────

    @staticmethod
    def _cartella_timeline(percorso: str) -> str:
        """Dove stanno i fotogrammi e l'onda di un video: una cartella
        provvisoria col nome ricavato dal file e dalla sua ultima modifica,
        cosi' un video cambiato non riusa le immagini di prima."""
        import hashlib
        import tempfile
        impronta = hashlib.sha1(
            f'{percorso}|{os.path.getmtime(percorso)}'.encode('utf-8')).hexdigest()[:16]
        return os.path.join(tempfile.gettempdir(), 'pica_timeline', impronta)

    def clip_apri(self, percorso: str) -> dict:
        """Quello che serve alla pagina per mostrare un video da montare: il
        video stesso, le sue misure e i fotogrammi della timeline."""
        bridge.entra('clip')
        percorso = (percorso or '').strip().strip('"')
        if not os.path.isfile(percorso):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        px = _pixdex()
        info = px.probe(percorso)
        if not info or not px.e_un_filmato(info):
            return {'ok': False, 'errore': i18n.t('pix.unreadable')}
        cd = _clipdex()
        try:
            fotogrammi = cd.striscia(percorso, self._cartella_timeline(percorso),
                                     info['duration'])
        except (OSError, subprocess.SubprocessError):
            fotogrammi = []
        return {
            'ok': True,
            'nome': os.path.basename(percorso),
            'video': self._url_file(percorso),
            'durata': info['duration'],
            'larghezza': info['width'], 'altezza': info['height'],
            'fps': round(info['fps'], 2),
            'peso': info['size'],
            'audio': (f"{info['audio_codec'].upper()}  ·  {info['audio_rate'] // 1000} kHz"
                      f"  ·  {'Mono' if info['audio_ch'] == 1 else 'Stereo'}"
                      if info['has_audio'] else ''),
            'fotogrammi': [self._url_file(f) for f in fotogrammi],
        }

    def clip_onda(self, percorso: str) -> dict:
        """La forma d'onda dell'audio. E' una chiamata a parte perche' su un
        video lungo ci mette qualche secondo, e la timeline non deve
        aspettarla per comparire."""
        percorso = (percorso or '').strip().strip('"')
        if not os.path.isfile(percorso):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        dst = os.path.join(self._cartella_timeline(percorso), 'onda.png')
        try:
            fatta = _clipdex().onda(percorso, dst)
        except (OSError, subprocess.SubprocessError):
            fatta = False
        return {'ok': fatta, 'onda': self._url_file(dst) if fatta else ''}

    def clip_esegui(self, opzioni: dict) -> dict:
        bridge.entra('clip')
        # I controlli si fanno qui e non nel thread: rispondere 'avviato' per
        # poi aprire una finestra d'errore che dice che mancava il file lascia
        # il programma occupato per un istante senza motivo, e la risposta era
        # una bugia. Un rifiuto immediato torna come {'ok': False}, e la
        # pagina ne fa un avviso.
        sorgenti = [f.strip().strip('"') for f in (opzioni.get('file') or []) if f.strip()]
        if not sorgenti:
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        if opzioni.get('azione') == 'unisci' and len(sorgenti) < 2:
            return {'ok': False, 'errore': i18n.t('clip.need_two')}
        mancanti = [f for f in sorgenti if not os.path.isfile(f)]
        if mancanti:
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        self._in_thread(self._clip_davvero, opzioni)
        return {'ok': True, 'avviato': True}

    def _clip_davvero(self, opzioni: dict) -> None:
        cd = _clipdex()
        azione = opzioni.get('azione', 'taglia')
        sorgenti = [s.strip().strip('"') for s in (opzioni.get('file') or []) if s.strip()]
        if not sorgenti:
            raise ErroreSpiegato(i18n.t('err.no_file'))

        # ClipDex chiede a FFmpeg quanti fotogrammi ha gia' prodotto (l'opzione
        # -progress) e con quelli disegna la sua barra a terminale. Restando in
        # ascolto, gli stessi fotogrammi muovono anche questa.
        bridge.verso_pagina('iniziaLavoro', 0)
        primo = sorgenti[0]
        esito = False

        with _spia.ascolta(_riporta_avanzamento):
            if azione == 'unisci':
                if len(sorgenti) < 2:
                    raise ErroreSpiegato(i18n.t('clip.need_two'))
                dst = cd.nome_uscita(primo, 'ClipDex unito', '.mp4', cartella=_montaggi(azione))
                esito = cd.unisci(sorgenti, dst,
                                  capitoli=bool(opzioni.get('capitoli', True)))
            elif azione == 'taglia':
                inizio = _leggi_tempo(opzioni.get('da')) or 0.0
                fine = _leggi_tempo(opzioni.get('a'))
                # Contenitore, codec e risoluzione: senza una scelta lo
                # spezzone resta com'e' l'originale, copiato e non ricodificato.
                contenitore = (opzioni.get('contenitore') or '').lower()
                estensione = ('.' + contenitore
                              if '.' + contenitore in cd.CODEC_PER_CONTENITORE else None)
                altezza = opzioni.get('altezza')
                dst = cd.nome_uscita(primo, 'ClipDex taglio', estensione,
                                     cartella=_montaggi(azione))
                esito = cd.taglia(primo, dst, inizio, fine,
                                  preciso=bool(opzioni.get('preciso')),
                                  codec=(opzioni.get('codec') or '').lower(),
                                  altezza=int(altezza) if altezza else 0,
                                  audio=bool(opzioni.get('audio', True)))
            else:                                   # gif, webp
                dst = cd.nome_uscita(primo, f'ClipDex {azione}',
                                      '.gif' if azione == 'gif' else '.webp',
                                      cartella=_montaggi(azione))
                funzione = cd.gif if azione == 'gif' else cd.webp
                esito = funzione(primo, dst, _leggi_tempo(opzioni.get('da')),
                                 _leggi_tempo(opzioni.get('durata')),
                                 int(opzioni.get('fps') or cd.GIF_FPS),
                                 int(opzioni.get('larghezza') or cd.GIF_LARGHEZZA))
        # Quello che esce si guarda qui: la GIF e il WebP come immagini, lo
        # spezzone e l'unione nel lettore.
        if not esito:
            raise ErroreSpiegato(i18n.t('clip.failed', file=os.path.basename(dst)))
        anteprima = self._url_file(dst)
        bridge.verso_pagina('clipFinito', {
            'ok': bool(esito),
            'file': os.path.basename(dst),
            'anteprima': anteprima,
            'testo': i18n.t('clip.done' if esito else 'clip.failed',
                            file=os.path.basename(dst)),
        })

    # ── Sottotitoli: correggere a mano ───────────────────────────────────────
    #
    # La pagina riceve i riquadri dei .srt accanto al video e li disegna da
    # se' sopra il video che sta suonando: una correzione si vede nell'istante
    # in cui la si scrive, senza rifare niente. Salvare riscrive il .srt; la
    # traccia nel file e la copia impressa si rifanno solo a richiesta, perche'
    # la seconda costa minuti.

    def sub_apri(self, percorso: str) -> dict:
        from server.video import sottotitoli as st

        video = (percorso or '').strip().strip('"')
        if not os.path.isfile(video):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        srt = st.nome_srt(video)
        if not os.path.isfile(srt):
            return {'ok': False, 'errore': i18n.t('sub.no_srt')}
        lista, colori = st.leggi_srt(srt)
        info = _pixdex().probe(video) or {}
        return {'ok': True, 'video': self._url_file(video),
                'nome': os.path.basename(video),
                # Le lingue in cui i sottotitoli esistono: l'originale (vuota)
                # e le traduzioni che hanno il loro .srt accanto al video.
                'lingue': [codice or '' for codice, _p in st.srt_del_video(video)],
                # I colori fra cui scegliere la voce di una riga.
                'tavolozza': st.COLORI,
                'scheda': {'altezza': info.get('height', 0), 'fps': info.get('fps', 0),
                           'peso': info.get('size', 0),
                           'durata': self._durata(info.get('duration'))},
                'riquadri': [{'inizio': r.inizio, 'fine': r.fine,
                              'righe': [{'testo': t, 'colore': colori.get(p, ''),
                                         'lineetta': l} for p, t, l in r.righe]}
                             for r in lista]}

    def sub_esporta(self, percorso: str, riquadri: list, formato: str = 'srt',
                    lingua: str = '') -> dict:
        """Scrive i sottotitoli in un file a parte, dove si sceglie: SRT o
        WebVTT, nella lingua originale (coi riquadri com'e' adesso nell'editor,
        anche non ancora aggiornati) o in una traduzione gia' fatta."""
        from server.video import sottotitoli as st

        video = (percorso or '').strip().strip('"')
        if not os.path.isfile(video):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        formato = 'vtt' if (formato or '').lower() == 'vtt' else 'srt'
        try:
            if lingua:
                srt = st.nome_srt(video, lingua)
                if not os.path.isfile(srt):
                    return {'ok': False, 'errore': i18n.t('sub.no_srt')}
                lista, colori = st.leggi_srt(srt)
            else:
                lista, colori = st.riquadri_da_pagina(riquadri or [])
            base = os.path.splitext(os.path.basename(video))[0]
            proposto = f"{base}{'.' + lingua if lingua else ''}.{formato}"
            scelta = bridge.attuale().create_file_dialog(
                _DLG_SALVA, directory=os.path.dirname(video), save_filename=proposto)
            if not scelta:
                return {'ok': True, 'file': ''}
            destinazione = scelta if isinstance(scelta, str) else scelta[0]
            if not destinazione.lower().endswith('.' + formato):
                destinazione += '.' + formato
            (st.scrivi_vtt if formato == 'vtt' else st.scrivi_srt)(lista, destinazione, colori)
        except (OSError, ValueError, KeyError) as exc:
            return {'ok': False, 'errore': str(exc)}
        return {'ok': True, 'file': destinazione,
                'testo': i18n.t('sub.esportato', file=os.path.basename(destinazione))}

    def sub_aggiorna(self, percorso: str, riquadri: list, impressa: bool = True) -> dict:
        """Salva le correzioni nel .srt e rifa' il resto: la traduzione, le
        tracce nel file, la copia impressa. Il salvataggio e' immediato; il
        resto gira in un thread, perche' la copia impressa costa minuti."""
        from server.video import sottotitoli as st

        bridge.entra('sub')
        video = (percorso or '').strip().strip('"')
        if not os.path.isfile(video):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        try:
            st.scrivi_riquadri(st.nome_srt(video), riquadri or [])
        except (OSError, ValueError, KeyError) as exc:
            self._posto.libera()
            return {'ok': False, 'errore': str(exc)}
        self._in_thread(self._sub_davvero, video, bool(impressa))
        return {'ok': True, 'avviato': True}

    def _sub_davvero(self, video: str, impressa: bool = True) -> None:
        from server.video import sottotitoli as st

        bridge.verso_pagina('iniziaLavoro', 0)
        st.riscrivi(video, impressa)
        bridge.verso_pagina('subFinito', {
            'ok': True,
            'video': self._url_file(video),
            'testo': i18n.t('sub.fatto', file=os.path.basename(video)),
        })

    # ── Doppiaggio ───────────────────────────────────────────────────────────
    #
    # Il lavoro vero sta in server/video/doppiaggio.py. Qui si aprono le
    # battute di un video sottotitolato, e si lancia la copia doppiata in un
    # thread: su un portatile senza scheda video costa minuti per ogni frase.

    def dop_apri(self, percorso: str) -> dict:
        from server.video import doppiaggio as dp
        from server.video import sottotitoli as st

        video = (percorso or '').strip().strip('"')
        if not os.path.isfile(video):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        if not os.path.isfile(st.nome_srt(video)):
            return {'ok': False, 'errore': i18n.t('sub.no_srt')}
        dati = dp.apri(video)
        return {'ok': True, 'nome': os.path.basename(video),
                'video': self._url_file(video),
                'doppiato': self._url_file(dati['doppiato']),
                'battute': dati['battute'],
                # La stima la fa la pagina mentre si scrive: le servono i
                # due numeri, non una chiamata a ogni tasto.
                'stima': {'base': dp._CARICAMENTO,
                          'per_carattere': dp._SECONDI_PER_SECONDO / dp._CARATTERI_AL_SECONDO}}

    def dop_avvia(self, percorso: str, riscritture: dict) -> dict:
        bridge.entra('dop')
        video = (percorso or '').strip().strip('"')
        if not os.path.isfile(video):
            return {'ok': False, 'errore': i18n.t('err.no_file')}
        cambi = {int(k): str(v) for k, v in (riscritture or {}).items() if str(v).strip()}
        if not cambi:
            return {'ok': False, 'errore': i18n.t('dop.niente')}
        if not self._posto.occupa():
            return {'ok': False, 'errore': i18n.t('err.busy')}
        self._in_thread(self._dop_davvero, video, cambi)
        return {'ok': True, 'avviato': True}

    def _dop_davvero(self, video: str, cambi: dict) -> None:
        from server.video import doppiaggio as dp

        bridge.verso_pagina('iniziaLavoro', 0)

        def avanza(testo: str, fatte: int = 0, totale: int = 0) -> None:
            bridge.verso_pagina('avanzaLavoro', fatte, totale,
                                fatte / totale if totale else None, testo)

        uscita = dp.doppia(video, cambi, avanza)
        bridge.verso_pagina('dopFinito', {
            'ok': True,
            'video': self._url_file(uscita),
            'testo': i18n.t('dop.fatto', file=os.path.basename(uscita)),
        })

    # ── Selettori di file ────────────────────────────────────────────────────

    def scegli_file(self, multi: bool = False, dove: str = '') -> dict:
        """Apre il selettore di file del sistema, per uno o piu' video, nella
        cartella dei risultati della sezione ``dove``."""
        try:
            # L'elenco delle estensioni sta negli attrezzi condivisi, quindi
            # aprire il selettore non fa piu' caricare il motore di montaggio
            # per intero - con dentro Rich - solo per sapere come si chiamano i
            # file video.
            # Le estensioni si separano col punto e virgola: con lo spazio
            # pywebview rifiuta il filtro e la finestra non si apre affatto.
            tipi = ('Video (' + ';'.join(f'*{e}' for e in sorted(_VIDEO_EXTS)) + ')',
                    'Audio (*.m4a;*.mp3;*.opus;*.wav;*.flac)', 'Tutti (*.*)')
            scelti = bridge.attuale().create_file_dialog(
                _DLG_APRI, directory=self._partenza(dove),
                allow_multiple=bool(multi), file_types=tipi)
        except Exception as exc:                # noqa: BLE001
            return {'ok': False, 'errore': str(exc), 'file': []}
        return {'ok': True, 'file': list(scelti) if scelti else []}

    @staticmethod
    def _url_file(percorso: str) -> str:
        """Trasforma un percorso di Windows in un indirizzo che la pagina apre.

        Non ``file:///``: la pagina arriva da un indirizzo http, e da li' il
        motore di Edge non carica niente dal disco. Passa dal server dei file
        multimediali (vedi ``server/controllers/media.py``).
        """
        from server.controllers import media
        return media.indirizzo(percorso)

    # ── Utilita' interne ─────────────────────────────────────────────────────

    def _in_thread(self, funzione, *argomenti) -> None:
        """Fa girare il lavoro fuori dal thread della finestra.

        Il posto e' gia' stato preso da ``_occupa()`` prima di arrivare qui, e
        qui lo si rende: prenderlo dentro al thread lo lascerebbe libero per
        tutto il tempo fra la risposta alla pagina e la partenza del thread, che
        e' esattamente la fessura che ``_occupa()`` serve a chiudere.

        L'output dei moduli viene dirottato al log solo per la durata del
        lavoro: farlo per sempre catturerebbe anche i messaggi di pywebview,
        che nel diario di un download non c'entrano niente.

        Il thread eredita l'indirizzo di sezione con ``bridge.entra()``: quello del
        chiamante non arriva qui da solo, e senza, ogni riferimento di questo
        lavoro finirebbe nella sezione Audio per ripiego.
        """
        dove = bridge.qui()

        def guscio():
            bridge.entra(dove)
            bridge.lavora_per(dove)
            bridge.verso_pagina('cambiaStato', 'working')
            diario = Diario(dove)
            vecchio_out, vecchio_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = diario
            try:
                self._aspetta_ffmpeg()
                funzione(*argomenti)
                bridge.verso_pagina('cambiaStato', 'done')
            except Exception as exc:
                bridge.verso_pagina('erroreLavoro', self._scheda_errore(exc))
                bridge.verso_pagina('cambiaStato', 'error')
            finally:
                diario.flush()
                sys.stdout, sys.stderr = vecchio_out, vecchio_err
                bridge.lavora_per(None)
                self._posto.libera()

        threading.Thread(target=guscio, daemon=True).start()

    @staticmethod
    def _aspetta_ffmpeg() -> None:
        """Tiene fermo il lavoro finche' FFmpeg non e' sul disco.

        Capita solo al primo avvio, a chi non l'aveva gia': intanto la barra
        del lavoro dice che cosa si sta aspettando e a che punto e'.
        """
        from server.utils import ffmpeg
        while not ffmpeg.attendi(1):
            _riporta_avanzamento(i18n.t('ffmpeg.scarico'),
                                 round(ffmpeg.stato()['parte'] * 100), 100)

    @staticmethod
    def _scheda_errore(exc: Exception) -> dict:
        """Prepara cio' che la finestra dell'errore deve mostrare.

        Due forme, e la differenza conta. Un ``ErroreSpiegato`` e' una
        richiesta che non si poteva soddisfare e che il programma sa gia'
        raccontare: si mostra la sua frase e basta, perche' il traceback sotto
        direbbe solo in che riga di Python e' scritta. Tutto il resto e' un
        guasto: la causa la indovina ``classifica_errore`` leggendo il testo
        tecnico, e il testo tecnico resta allegato, perche' e' quello che si
        copia per cercarlo in rete.

        Il traceback intero viene anche scritto nel log del lavoro: la
        finestra si chiude, il file no.
        """
        if isinstance(exc, ErroreSpiegato):
            return {'titolo': i18n.t('err.title'), 'causa': str(exc), 'dettaglio': ''}

        tecnico = traceback.format_exc()
        logging.getLogger(_LOG_DI.get(bridge.qui(), 'pica')).error(tecnico)
        return {
            'titolo': i18n.t('err.title'),
            # Si classifica sul traceback intero e non sul solo str(exc):
            # la parola che dice di che famiglia si tratta - il nome del
            # modulo mancante, l'HRESULT, il codice HTTP - sta spesso in una
            # riga di mezzo, e l'ultima riga da sola la perderebbe.
            'causa': classifica_errore(f'{exc}\n{tecnico}'),
            'dettaglio': tecnico.strip(),
        }

    @staticmethod
    def _album(info: dict, url: str) -> list[dict] | None:
        """Le tracce di un album caricato come video unico, o None.

        Prima i capitoli di YouTube. Se non ci sono, e il video e' abbastanza
        lungo da poter essere un disco, la scaletta scritta a mano: nella
        descrizione, poi nei commenti piu' votati, dove la mette di solito chi
        ascolta. Ogni scaletta passa dagli stessi criteri dei capitoli veri.
        """
        from server.audio.chapters import (DURATA_MINIMA_ALBUM, capitoli_album,
                                           scaletta_da_testo)
        album = capitoli_album(info)
        durata = float(info.get('duration') or 0)
        if album or info.get('chapters') or durata < DURATA_MINIMA_ALBUM:
            return album

        def prova(testo: str) -> list[dict] | None:
            capitoli = scaletta_da_testo(testo, durata)
            return capitoli_album({'chapters': capitoli, 'duration': durata}) if capitoli else None

        album = prova(info.get('description') or '')
        if album:
            return album
        from server.sources.youtube import commenti_migliori
        for commento in commenti_migliori(info.get('webpage_url') or url):
            album = prova(commento)
            if album:
                return album
        return None

    @staticmethod
    def _miniatura(video_id) -> str:
        """Indirizzo della miniatura, ricavato dall'identificativo del video.

        YouTube le serve a un indirizzo prevedibile, quindi non serve nessuna
        chiamata in piu': l'identificativo sta gia' dentro la entry che il
        motore produce, e il motore non va toccato per averla.

        Passa dal server locale, che la scarica attraverso Tor: chiesta dalla
        pagina, mostrerebbe a YouTube l'IP di casa.
        """
        from server.controllers import media
        return media.remoto(f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg') if video_id else ''

    @staticmethod
    def _durata(secondi) -> str:
        try:
            s = int(secondi or 0)
        except (TypeError, ValueError):
            return ''
        if not s:
            return ''
        ore, resto = divmod(s, 3600)
        minuti, sec = divmod(resto, 60)
        return f'{ore}:{minuti:02d}:{sec:02d}' if ore else f'{minuti}:{sec:02d}'
