"""Da un guasto tecnico a una frase che si capisce.

Il problema che risolve
    Quando un lavoro cade, quello che arriva non e' una frase del programma:
    e' una frase di qualcun altro. FFmpeg dice ``Invalid data found when
    processing input``, yt-dlp dice ``HTTP Error 403: Forbidden``, Windows
    risponde con un numero esadecimale di otto cifre. Sono precise e sono
    inutili: chi ha premuto un bottone vuole sapere se ha sbagliato lui, se
    deve installare qualcosa, o se conviene riprovare fra un minuto.

    Finche' c'era la scheda del diario, quelle righe finivano li' in mezzo ad
    altre duecento e il problema non si poneva, perche' non le leggeva
    nessuno. Adesso un errore apre una finestra, e in cima a quella finestra
    ci vuole una riga in italiano.

Cosa fa e cosa non fa
    Riconosce le famiglie di guasti che Pica produce davvero - non tutte
    quelle possibili - e per ognuna restituisce una frase. Il testo tecnico
    non lo butta via: continua a viaggiare accanto, nel suo riquadro, perche'
    e' quello che si copia per cercarlo in rete.

    Quando non riconosce niente non inventa: restituisce ``err.unknown``, che
    dice onestamente «e' andato storto qualcosa» e lascia parlare il riquadro
    sotto. Una classificazione sbagliata sarebbe peggio di nessuna
    classificazione: manderebbe a cercare la causa dalla parte opposta.

Perche' le regole stanno in una tabella
    Perche' cosi' si leggono. Una catena di ``if`` lunga quaranta righe
    nasconde quante famiglie si riconoscono e in che ordine; un elenco di
    coppie lo dice guardandolo. L'ordine conta ed e' quello scritto: la prima
    che corrisponde vince, quindi le regole strette stanno sopra le larghe -
    «spazio esaurito» prima di «errore di scrittura», o la seconda si
    prenderebbe anche la prima.
"""
from __future__ import annotations

import re

from server.config import i18n


class ErroreSpiegato(Exception):
    """Un guasto di cui il programma sa gia' dire la causa, in italiano.

    Serve a distinguere due cose che altrimenti arriverebbero uguali alla
    finestra. Un file video illeggibile, una cartella senza tracce, un
    montaggio «unisci» con un file solo: non sono difetti del programma, sono
    richieste che non si possono soddisfare, e il programma sa gia' spiegarle
    con una frase sua. Un ``KeyError`` a meta' di ``_tag_m4a``, invece, e' un
    difetto, e li' serve il traceback.

    Chi la solleva mette nel messaggio la frase gia' tradotta. Chi la prende -
    ``_in_thread`` - la mostra cosi' com'e' e NON allega il testo tecnico: di
    una frase che si capisce gia', il traceback sotto direbbe solo in che riga
    di Python e' stata scritta, che non interessa a nessuno.
    """


# L'ordine conta: la prima che corrisponde vince, quindi le regole strette
# stanno sopra le larghe.
_REGOLE: tuple[tuple[re.Pattern[str], str], ...] = (
    # Strumenti che mancano. Vanno per primi: senza di loro il resto del
    # messaggio parla di un lavoro che non e' nemmeno cominciato.
    (re.compile(r'ffmpeg|ffprobe', re.I), 'err.ffmpeg'),
    (re.compile(r'pywin32|win32com|pythoncom|no module named [\'"]?win32', re.I),
     'err.no_pywin32'),

    # Disco e permessi.
    (re.compile(r'no space left|disk full|spazio.*(esaurit|insufficient)|errno 28', re.I),
     'err.spazio'),
    (re.compile(r'permission denied|access is denied|accesso negato|errno 13', re.I),
     'err.permessi'),
    (re.compile(r'no such file|file not found|errno 2|impossibile trovare il (file|percorso)',
                re.I), 'err.manca_file'),
    (re.compile(r'invalid data found|moov atom not found|could not find codec|'
                r'end of file|formato.*non riconosciut', re.I), 'err.illeggibile'),

    # Masterizzazione. Le tre cause distinte stanno sopra l'HRESULT generico,
    # che altrimenti se le prenderebbe tutte.
    (re.compile(r'nessun masterizzator|no recorder|no cd.?(writer|recorder)|'
                r'masterizzatore non trovato', re.I), 'err.no_masterizzatore'),
    (re.compile(r'no media|nessun disco|media not present|supporto assente|'
                r'0x80040219|0xc0aa0202', re.I), 'err.no_disco'),
    (re.compile(r'media (is )?not (blank|erasable)|disco non (vuoto|vergine)|0xc0aa0207',
                re.I), 'err.disco_pieno'),
    (re.compile(r'imapi|0x80040|0xc0aa', re.I), 'err.imapi'),

    # Rete e YouTube.
    (re.compile(r'403|forbidden|sign in to confirm|age.?restrict|private video|'
                r'not available in your country|members.?only', re.I), 'err.vietato'),
    (re.compile(r'404|video unavailable|has been removed|no longer available', re.I),
     'err.sparito'),
    (re.compile(r'timed? ?out|connection (reset|refused|aborted|error)|'
                r'temporary failure in name resolution|getaddrinfo|'
                r'unable to (download|connect)|network is unreachable|ssl', re.I),
     'err.rete'),

    (re.compile(r'keyboardinterrupt|interrotto dall\'utente|cancelled by user', re.I),
     'err.interrotto'),
)


def classifica_errore(messaggio: str) -> str:
    """La frase in italiano che spiega un guasto, o quella di ripiego.

    ``messaggio`` e' il testo grezzo: il ``str(eccezione)``, oppure il
    traceback intero. Si guarda tutto, perche' la parola che identifica la
    famiglia sta spesso nella riga di mezzo e non in quella finale - il nome
    del modulo mancante, il codice HTTP, l'HRESULT.
    """
    if not messaggio:
        return i18n.t('err.unknown')
    for regola, chiave in _REGOLE:
        if regola.search(messaggio):
            return i18n.t(chiave)
    return i18n.t('err.unknown')
