"""Sottotitoli con i parlanti: chi dice cosa, e quando.

Due domande diverse, due modelli diversi, e poi si incastrano le risposte.

    COSA si dice   Whisper (faster-whisper, su CPU): il testo, parola per
                   parola, ognuna col suo istante di inizio e fine.
    CHI parla      pyannote segmentation-3.0 guarda l'audio a finestre di
                   dieci secondi e dice, fotogramma per fotogramma, quante
                   voci ci sono e quando si sovrappongono. Di ogni voce di
                   ogni finestra si prende l'impronta (CAM++, via
                   sherpa-onnx), e le impronte simili finiscono nello stesso
                   mucchio: ogni mucchio e' una persona, e ha il suo colore.
    COSA si sente  CED (via sherpa-onnx) riconosce musica, pubblico,
                   applausi: dove non si parla, o non si capisce, vanno a
                   schermo tra parentesi (vedi ``etichette``).

L'incastro sta qui: ogni parola va alla persona che in quel momento parla. Se
ne parlano due insieme, decide l'impronta del pezzo attorno alla parola.

Quando si parlano addosso
    Due battute brevi che si rincorrono - una domanda e la risposta, o una
    frase detta sopra quella dell'altro - vanno a schermo insieme, come si fa
    nei sottotitoli dei film: la prima resta in alto, la seconda compare sotto
    quando comincia, ognuna col suo colore e con la lineetta davanti. Chi
    legge vede lo scambio come un elenco, invece di due colori che si danno il
    cambio in un secondo.

Quando le voci si somigliano troppo
    Due voci simili che si parlano in fretta, in una stanza diversa da quella
    del resto del video, possono avere impronte indistinguibili: misurato su un
    dialogo vero, due frasi della stessa persona si somigliavano quanto due
    frasi di persone diverse. Li' non si chiede piu' alle impronte CHI parla,
    ma DOVE cambia chi parla (vedi ``_punti_di_cambio``), e i turni si
    dividono fra due voci partendo dall'alternanza, che e' la forma di quasi
    ogni scambio. Ogni turno va a capo con la lineetta: anche se un colore
    fosse sbagliato, lo scambio resta leggibile. Il testo non resta mai
    bianco, salvo quando nel video parla una persona sola.

Perche' questi modelli
    pyannote «vero» chiede un account e una chiave su Hugging Face; la stessa
    segmentazione esportata in ONNX e CAM++ si scaricano da GitHub senza
    chiedere niente a nessuno. Ed e' lo spirito del programma: niente account,
    niente chiavi, il lavoro gira su questo computer e l'audio non esce da qui.
    La pipeline gia' pronta di sherpa-onnx e' stata provata e scartata: piu'
    lenta, e con un'impronta (ResNet34 di VoxCeleb) che spezzava la stessa voce
    in due persone appena sotto cambiava la musica.

Cosa esce
    dentro il file   una traccia di sottotitoli attivabile, accesa di default.
                     Nel .mkv e' ASS, coi colori; nel .mp4 e' mov_text, e i
                     colori si perdono: l'encoder di FFmpeg li scarta. Restano
                     le lineette dei dialoghi.
    impressi         a richiesta, una copia «(sottotitolato)» coi sottotitoli
                     disegnati nell'immagine, colori compresi: si vedono
                     ovunque. Il video si porta almeno a 1080 righe prima di
                     scriverci sopra, cosi' le lettere sono nitide anche se il
                     filmato non lo e'.
    accanto          un .srt con lo stesso nome del video, per sicurezza: si
                     corregge a mano, e resta anche se un programma butta la
                     traccia interna.
I modelli si scaricano la prima volta, in ``modelli/`` accanto al programma.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field

import numpy as np

from server.config import paths
from server.utils.console import setup_logger

log = setup_logger('audiodex', 'audiodex.log')

FREQUENZA = 16000

# Whisper 'small' e' il compromesso per una CPU qualunque: in italiano sbaglia
# poco, e 'medium' sbaglia meno ma impiega circa tre volte tanto.
MODELLO_WHISPER = 'small'

_GITHUB = 'https://github.com/k2-fsa/sherpa-onnx/releases/download'
_SEGMENTATORE = (f'{_GITHUB}/speaker-segmentation-models/'
                 'sherpa-onnx-pyannote-segmentation-3-0.tar.bz2')
# CAM++ di 3D-Speaker, addestrato su cinese e inglese: l'impronta di una voce
# non dipende dalla lingua che parla, e fra i quattro modelli provati e' quello
# che separa meglio e fa prima. ("recongition" e' scritto cosi' anche sul
# server: non e' un refuso nostro.)
_IMPRONTA = (f'{_GITHUB}/speaker-recongition-models/'
             '3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx')

# Il segmentatore lavora su dieci secondi alla volta e restituisce un
# fotogramma ogni 270 campioni (17 ms). Le finestre avanzano di due secondi e
# mezzo: ogni istante e' visto da quattro finestre, e la media delle quattro
# opinioni e' molto piu' ferma di una sola.
_FINESTRA = 160000
_AVANZO = 40000
_SPOSTAMENTO = 270
_PASSO = _SPOSTAMENTO / FREQUENZA
# Le sette classi del segmentatore sono insiemi di voci (nessuna, una delle
# tre, due insieme): questa matrice le traduce in «chi e' attivo».
_INSIEMI = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                     [1, 1, 0], [1, 0, 1], [0, 1, 1]], dtype=np.float32)

# Distanza (coseno) sotto la quale due mucchi sono la stessa persona. Misurata
# su un dialogo vero: a 0,5 una voce si spezza in quattro, a 0,8 due persone
# diverse si fondono.
SOGLIA_PARLANTI = 0.6
# Somiglianza fra le impronte medie di due persone oltre la quale sono la
# stessa (vedi ``_persone``).
SOGLIA_STESSA_PERSONA = 0.68

# Una voce di una finestra entra nel raggruppamento solo se parla da sola per
# almeno un secondo: meno e' un'impronta troppo incerta per decidere chi
# esiste. Le voci piu' brevi, fino a un quarto di secondo, vengono attribuite
# dopo alla persona piu' simile.
_VOCE_PIENA = 1.0
_VOCE_MINIMA = 0.25

# Una «persona» con meno di cosi' di voce non e' una persona: e' una risata,
# una frase urlata sopra la musica. Servono entrambe le soglie: la quota da
# sola, su un video corto, e' meno di una parola; i secondi da soli, su
# un'ora, sono un'inezia.
QUOTA_MINIMA = 0.04
SECONDI_MINIMI = 4.5

# Quando una voce e' riconosciuta con sicurezza: somiglia alla sua persona
# almeno quanto le voci tipiche di quella persona (meno un margine), e alle
# altre persone chiaramente meno.
_SICURO_MARGINE = 0.15
_SICURO_TETTO = 0.78

# Come si spezza una battuta. Le regole dei sottotitolatori dicono da 36 a 40
# caratteri a riga: oltre, l'occhio non fa in tempo a leggere. Le stesse
# regole ammettono due righe e sette secondi, ma allora a schermo c'e' gia'
# tutta la frase quando chi parla e' appena all'inizio, e si leggono parole
# che non ha ancora detto. Qui una riga sola e pochi secondi: il testo cambia
# piu' spesso, e resta attaccato alla voce.
RIGA_MAX = 40
RIGHE_MAX = 1
PAUSA_MAX = 0.9     # secondi di silenzio che chiudono una battuta
DURATA_MAX = 3.5    # nessuna battuta dura piu' di cosi'

# Il «parlante» delle etichette dei suoni: [musica], [applausi]. Bianche,
# senza lineetta, e mai in un dialogo a elenco.
ETICHETTA = -1
# Chi parla in un video con una voce sola: bianco anche lui, ma parla.
UNA_VOCE = -2


def _chi_riga(colore: str | None, testo: str, colori: dict[int, str]) -> int:
    """La persona di una riga riletta da un .srt: dal colore, o se non ne
    ha, un'etichetta dei suoni se e' tra parentesi quadre e la voce unica
    altrimenti."""
    if colore:
        persona = next((p for p, c in colori.items() if c == colore), len(colori))
        colori[persona] = colore
        return persona
    return ETICHETTA if testo.startswith('[') and testo.endswith(']') else UNA_VOCE

# Un colore per persona, sempre lo stesso per tutto il video, scelti per
# leggersi su qualunque immagine col bordo scuro sotto. In ordine RGB. Il
# bianco non c'e': e' riservato ai video in cui parla una persona sola.
COLORI = ['#FFD21F', '#5CE1FF', '#7CFF6B', '#FF8AD8',
          '#FFA64D', '#B69CFF', '#FF6B6B']
BIANCO = '#FFFFFF'

# Il titolo della traccia nel file: e' anche il segno, per il giro dopo, che i
# sottotitoli ci sono gia'.
TITOLO_TRACCIA = 'Dialoghi'


@dataclass
class Voci:
    """Chi parla, fotogramma per fotogramma."""
    attivo: np.ndarray      # (fotogramma, persona) bool
    sicuro: np.ndarray      # (fotogramma, persona) bool: attivo e riconosciuto
    centri: np.ndarray      # (persona, dimensione): l'impronta media di ognuno
    # Le probabilita' grezze del segmentatore, prima di ogni decisione: quanto
    # e' probabile che qualcuno parli, e che ci sia una seconda voce. Servono
    # nei tratti incerti, dove la decisione netta ha visto una voce sola ma i
    # cambi di turno lasciano comunque un segno - un calo, un'altra voce che
    # affiora per un istante.
    parla: np.ndarray       # (fotogramma,) float
    seconda: np.ndarray     # (fotogramma,) float

    @property
    def persone(self) -> int:
        return self.attivo.shape[1]


@dataclass
class Battuta:
    """Parole consecutive dello stesso turno di una persona."""
    inizio: float
    fine: float
    parlante: int
    parole: list[str] = field(default_factory=list)
    turno: int = 0
    scambio: bool = False   # apre o chiude uno scambio veloce: va la lineetta

    @property
    def testo(self) -> str:
        return ''.join(self.parole).strip()


@dataclass
class Riquadro:
    """Quello che sta a schermo in un intervallo, al piu' due righe. Ogni riga
    e' ``(parlante, testo, lineetta)``."""
    inizio: float
    fine: float
    righe: list[tuple[int, str, bool]]


# ── I modelli ────────────────────────────────────────────────────────────────

def _cartella_modelli() -> str:
    cartella = paths.dati('modelli')
    os.makedirs(cartella, exist_ok=True)
    return cartella


def _scarica(url: str) -> bytes:
    import requests

    log.info('Scarico il modello: %s', url)
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def _salva(percorso: str, dati: bytes) -> None:
    """Scrive in un file di passaggio e rinomina solo a fine corsa: un
    download interrotto non deve lasciare un modello a meta' che al giro dopo
    sembri buono."""
    with open(percorso + '.part', 'wb') as f:
        f.write(dati)
    os.replace(percorso + '.part', percorso)


def _modello_segmentatore() -> str:
    percorso = os.path.join(_cartella_modelli(), 'pyannote-segmentation-3.0.onnx')
    if not os.path.isfile(percorso):
        with tarfile.open(fileobj=io.BytesIO(_scarica(_SEGMENTATORE))) as tar:
            membro = next(m for m in tar.getmembers()
                          if m.name.endswith('/model.onnx'))
            _salva(percorso, tar.extractfile(membro).read())
    return percorso


def _modello_impronta() -> str:
    percorso = os.path.join(_cartella_modelli(), os.path.basename(_IMPRONTA))
    if not os.path.isfile(percorso):
        _salva(percorso, _scarica(_IMPRONTA))
    return percorso


def _estrattore():
    import sherpa_onnx

    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_modello_impronta(),
            num_threads=max(1, min(4, os.cpu_count() or 1))))


def _impronta(estrattore, audio: np.ndarray) -> np.ndarray:
    flusso = estrattore.create_stream()
    flusso.accept_waveform(FREQUENZA, audio)
    flusso.input_finished()
    v = np.asarray(estrattore.compute(flusso), dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-9)


# ── Chi parla ────────────────────────────────────────────────────────────────

def estrai_audio(video: str) -> np.ndarray:
    """L'audio del video come i modelli lo vogliono: mono, 16 kHz, float32."""
    uscita = subprocess.run(
        ['ffmpeg', '-v', 'error', '-nostdin', '-i', video, '-vn', '-ac', '1',
         '-ar', str(FREQUENZA), '-f', 'f32le', '-'],
        capture_output=True, check=True)
    return np.frombuffer(uscita.stdout, dtype=np.float32).copy()


def _segmenta(campioni: np.ndarray):
    """Le finestre, il loro audio, chi e' attivo in ognuna e le probabilita'
    grezze: ``(inizi, pezzi, attivita' (finestra, fotogramma, voce locale),
    probabilita' (finestra, fotogramma, classe))``."""
    import onnxruntime as ort

    opzioni = ort.SessionOptions()
    opzioni.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
    sessione = ort.InferenceSession(_modello_segmentatore(), opzioni,
                                    providers=['CPUExecutionProvider'])
    inizi = list(range(0, max(1, len(campioni) - _FINESTRA + 1), _AVANZO))
    if inizi[-1] + _FINESTRA < len(campioni):
        inizi.append(len(campioni) - _FINESTRA)
    pezzi = []
    for s in inizi:
        pezzo = campioni[s:s + _FINESTRA]
        if len(pezzo) < _FINESTRA:
            pezzo = np.pad(pezzo, (0, _FINESTRA - len(pezzo)))
        pezzi.append(pezzo)
    attivita = []
    probabilita = []
    for i in range(0, len(pezzi), 16):
        uscita = sessione.run(None, {'x': np.stack(pezzi[i:i + 16])[:, None, :]})[0]
        attivita.extend(np.eye(7, dtype=np.float32)[uscita.argmax(-1)] @ _INSIEMI)
        probabilita.extend(np.exp(uscita))
    return inizi, pezzi, np.array(attivita), np.array(probabilita)


def chi_parla(campioni: np.ndarray, n_parlanti: int | None = None) -> Voci:
    """Chi parla in ogni istante, sovrapposizioni comprese.

    ``n_parlanti`` fissa il numero di persone quando lo si sa gia'; senza, lo
    decide la soglia di somiglianza.
    """
    inizi, pezzi, attivita, probabilita = _segmenta(campioni)
    n_fot = attivita.shape[1]
    estrattore = _estrattore()

    # L'impronta di ogni voce di ogni finestra, presa solo dove parla da sola:
    # un pezzo in cui parlano in due avrebbe l'impronta di nessuno dei due.
    impronte, chiavi, secondi = [], [], []
    for c, pezzo in enumerate(pezzi):
        a = attivita[c]
        for k in range(3):
            sola = (a[:, k] > 0) & (a.sum(1) == 1)
            durata = sola.sum() * _PASSO
            if durata < _VOCE_MINIMA:
                continue
            maschera = np.repeat(sola, _SPOSTAMENTO)[:_FINESTRA]
            maschera = np.pad(maschera, (0, _FINESTRA - len(maschera)))
            impronte.append(_impronta(estrattore, pezzo[maschera]))
            chiavi.append((c, k))
            secondi.append(durata)
    if not impronte:
        vuoto = np.zeros((int(np.ceil(len(campioni) / _SPOSTAMENTO)) + n_fot, 0), bool)
        zeri = np.zeros(len(vuoto), np.float32)
        return Voci(vuoto, vuoto, np.zeros((0, 1), np.float32), zeri, zeri)
    impronte = np.array(impronte)
    secondi = np.array(secondi)

    centri = _persone(impronte, secondi, n_parlanti)

    # Ogni voce locale va alla persona piu' simile. Due voci della stessa
    # finestra di solito sono due persone diverse, e allora la seconda prende
    # la sua seconda scelta, se le somiglia abbastanza. Non sempre, pero': il
    # segmentatore a volte spezza in due la stessa voce quando cambia tono, e
    # se la seconda somiglia molto alla persona gia' presa resta sua.
    somiglia = impronte @ centri.T
    persona = np.full(len(chiavi), -1)
    per_finestra: dict[int, list[int]] = {}
    for i, (c, _) in enumerate(chiavi):
        per_finestra.setdefault(c, []).append(i)
    for indici in per_finestra.values():
        prese: set[int] = set()
        for i in sorted(indici, key=lambda i: -somiglia[i].max()):
            ordine = [int(p) for p in np.argsort(-somiglia[i])]
            migliore = ordine[0]
            if migliore not in prese or somiglia[i, migliore] >= 0.7:
                persona[i] = migliore
            else:
                libere = [p for p in ordine if p not in prese
                          and somiglia[i, p] >= 0.5]
                if libere:
                    persona[i] = libere[0]
            if persona[i] >= 0:
                prese.add(int(persona[i]))

    # Sicura: somiglia alla sua persona quanto le voci tipiche di quella
    # persona, e alle altre chiaramente meno.
    tipica = np.array([np.median(somiglia[persona == p, p]) if np.any(persona == p)
                       else 1.0 for p in range(len(centri))])
    sicura = np.zeros(len(chiavi), bool)
    for i, p in enumerate(persona):
        if p < 0:
            continue
        altre = np.delete(somiglia[i], p)
        margine = somiglia[i, p] - (altre.max() if len(altre) else 0.0)
        sicura[i] = (somiglia[i, p] >= min(_SICURO_TETTO, tipica[p] - 0.1)
                     and margine >= _SICURO_MARGINE)

    # Le opinioni delle finestre che si sovrappongono si mettono in media.
    n = int(np.ceil(len(campioni) / _SPOSTAMENTO)) + n_fot
    somma = np.zeros((n, len(centri)), np.float32)
    somma_sicura = np.zeros((n, len(centri)), np.float32)
    viste = np.zeros(n, np.float32)
    for c, s in enumerate(inizi):
        f0 = s // _SPOSTAMENTO
        viste[f0:f0 + n_fot] += 1
        # Nella finestra, per persona: attiva se lo e' una qualunque delle sue
        # voci locali (di solito una sola, due se il segmentatore l'ha spezzata).
        qui = np.zeros((n_fot, len(centri)), np.float32)
        qui_sicura = np.zeros((n_fot, len(centri)), np.float32)
        for i in per_finestra.get(c, []):
            p, k = persona[i], chiavi[i][1]
            if p < 0:
                continue
            qui[:, p] = np.maximum(qui[:, p], attivita[c][:, k])
            if sicura[i]:
                qui_sicura[:, p] = np.maximum(qui_sicura[:, p], attivita[c][:, k])
        somma[f0:f0 + n_fot] += qui
        somma_sicura[f0:f0 + n_fot] += qui_sicura
    parla = np.zeros(n, np.float32)
    seconda = np.zeros(n, np.float32)
    for c, s in enumerate(inizi):
        f0 = s // _SPOSTAMENTO
        voci_locali = probabilita[c] @ _INSIEMI
        parla[f0:f0 + n_fot] += 1.0 - probabilita[c][:, 0]
        seconda[f0:f0 + n_fot] += voci_locali.sum(1) - voci_locali.max(1)
    parla /= np.maximum(viste, 1)
    seconda /= np.maximum(viste, 1)

    viste = np.maximum(viste, 1)[:, None]
    attivo = somma / viste > 0.5
    sicuro = attivo & (somma_sicura / np.maximum(somma, 1e-9) > 0.5)
    log.info('Parlanti: %d persone, %.0f%% del parlato riconosciuto con sicurezza, '
             '%.1f s di voci sovrapposte', len(centri),
             100 * sicuro.any(1).sum() / max(1, attivo.any(1).sum()),
             (attivo.sum(1) > 1).sum() * _PASSO)
    return Voci(attivo, sicuro, centri, parla, seconda)


def _persone(impronte: np.ndarray, secondi: np.ndarray,
             n_parlanti: int | None) -> np.ndarray:
    """Le impronte medie delle persone che ci sono davvero.

    Si raggruppano solo le voci piene; i mucchi con troppo poca voce per
    essere una persona si sciolgono, e ogni voce torna alla persona alla cui
    media somiglia di piu' finche' le medie non si fermano.
    """
    from scipy.cluster.hierarchy import fcluster, linkage

    piene = secondi >= _VOCE_PIENA
    if piene.sum() < 2:
        piene = secondi >= secondi.max()
    x, w = impronte[piene], secondi[piene]
    if len(x) < 2:
        return x[:1].copy()
    albero = linkage(x, method='average', metric='cosine')
    if n_parlanti:
        gruppi = fcluster(albero, t=n_parlanti, criterion='maxclust') - 1
    else:
        gruppi = fcluster(albero, t=SOGLIA_PARLANTI, criterion='distance') - 1
    peso = np.bincount(gruppi, weights=w)
    veri = [k for k in range(len(peso))
            if peso[k] >= max(SECONDI_MINIMI, QUOTA_MINIMA * w.sum())]
    if not veri:
        veri = [int(np.argmax(peso))]
    for _ in range(10):
        centri = np.array([x[gruppi == k].mean(0) for k in veri])
        centri /= np.maximum(np.linalg.norm(centri, axis=1, keepdims=True), 1e-9)
        nuovi = np.array(veri)[np.argmax(x @ centri.T, axis=1)]
        if np.array_equal(nuovi, gruppi):
            break
        gruppi = nuovi
        veri = [k for k in veri if np.any(gruppi == k)]

    # Due mucchi con la media quasi uguale sono la stessa persona in due
    # ambienti: dal vivo la voce di chi sta al microfono cambia quando sotto
    # parte la musica o urla il pubblico, e le sue finestre si dividono in due
    # mucchi vicini. Lasciati separati, ogni suo discorso diventava un dialogo
    # fra due colori. Fra persone diverse, anche con voci simili, la
    # somiglianza fra le medie resta molto sotto (0,45 su un dialogo vero).
    while not n_parlanti and len(veri) > 1:
        centri = np.array([x[gruppi == k].mean(0) for k in veri])
        centri /= np.maximum(np.linalg.norm(centri, axis=1, keepdims=True), 1e-9)
        s = centri @ centri.T
        np.fill_diagonal(s, -1)
        a, b = np.unravel_index(np.argmax(s), s.shape)
        if s[a, b] < SOGLIA_STESSA_PERSONA:
            break
        gruppi[gruppi == veri[b]] = veri[a]
        veri.pop(b)
    centri = np.array([x[gruppi == k].mean(0) for k in veri])
    return centri / np.maximum(np.linalg.norm(centri, axis=1, keepdims=True), 1e-9)


# ── Cosa si dice ─────────────────────────────────────────────────────────────

def cosa_si_dice(campioni: np.ndarray, lingua: str | None = None,
                 modello: str = MODELLO_WHISPER
                 ) -> tuple[list[tuple[float, float, str]], str]:
    """Le parole pronunciate, ognuna coi suoi tempi: ``[(inizio, fine, parola)]``,
    e la lingua in cui sono dette (quella chiesta, o quella che Whisper ha
    riconosciuto).

    La parola conserva lo spazio iniziale che Whisper le mette davanti: e'
    cosi' che si rimettono insieme senza indovinare dove vanno gli spazi.

    Niente filtro del parlato (VAD) davanti a Whisper. Il filtro scarta come
    rumore proprio quello che in un video caotico conta di piu': le frasi
    urlate sopra la musica e il pubblico. Su un concerto dal vivo, di un
    minuto di urla ne teneva tre secondi. Whisper le sente, e chi guarda le
    vuole leggere. Il prezzo e' che sulla musica sola Whisper a volte si
    inventa frasi: le si riconosce dal suo stesso giudizio (vedi
    ``_inventato``) e si buttano.

    Le urla del pubblico che restano senza testo non si ripescano: riascoltati
    da soli, i buchi di un concerto dal vivo (35 tratti, 68 secondi) hanno
    dato tre frasi credibili e per il resto urla indecifrabili e frasi
    inventate, al prezzo di sei minuti in piu'.
    """
    from faster_whisper import WhisperModel

    whisper = WhisperModel(
        modello, device='cpu', compute_type='int8',
        cpu_threads=os.cpu_count() or 4,
        download_root=os.path.join(_cartella_modelli(), 'whisper'))
    segmenti, info = whisper.transcribe(
        campioni, language=lingua or None, word_timestamps=True,
        vad_filter=False, beam_size=5,
        # Senza, un errore di Whisper si ricopia nella frase dopo e da li'
        # nelle successive: e' l'origine delle ripetizioni a catena.
        condition_on_previous_text=False,
        # Salta i silenzi lunghi quando sospetta di stare inventando.
        hallucination_silence_threshold=2.0,
        # Quando non e' sicuro, Whisper riprova lo stesso pezzo a
        # «temperature» crescenti, di serie fino a sei volte: sopra la musica
        # succede di continuo, e la trascrizione durava il doppio del video.
        # Un secondo tentativo basta a recuperare le frasi urlate; il solo
        # primo le perdeva. Misurato su un concerto: 38% di tempo in meno.
        temperature=[0.0, 0.4])
    log.info('Lingua riconosciuta: %s (%.0f%%)', info.language,
             info.language_probability * 100)
    parole: list[tuple[float, float, str]] = []
    scartati = 0
    for seg in segmenti:
        if _inventato(seg):
            scartati += 1
            log.debug('Scartato come inventato: %s', seg.text)
            continue
        for p in seg.words or []:
            # «l'» e «unedì», «c» e «'è»: Whisper spezza le parole
            # sull'apostrofo, e un pezzo senza spazio davanti e' la
            # continuazione di quello prima. Rimesse insieme, non c'e' il
            # rischio di tagliare un turno o una riga a meta' parola.
            if parole and not p.word.startswith(' ') and p.start - parole[-1][1] < 0.3:
                a, _, testo = parole[-1]
                parole[-1] = (a, p.end, testo + p.word)
            else:
                parole.append((p.start, p.end, p.word))
    if scartati:
        log.info('Trascrizione: %d pezzi scartati come inventati', scartati)
    return parole, lingua or info.language


def _alla_voce(parole: list[tuple[float, float, str]], voci: Voci
               ) -> list[tuple[float, float, str]]:
    """Ogni parola comincia quando comincia davvero la voce.

    Whisper fa partire spesso le parole troppo presto: dopo una pausa o
    sopra la musica la prima parola si prende anche il silenzio che la
    precede, e il sottotitolo compariva prima che qualcuno aprisse bocca. Il
    segmentatore sa invece, a 17 millesimi, quando una voce c'e': la parola
    si sposta al primo istante in cui si sente parlare. Solo in avanti, mai
    indietro; e se dentro la parola il segmentatore non sente nessuno (una
    frase urlata che non ha riconosciuto come voce) resta com'e'.
    """
    attiva = voci.parla > 0.5
    uscita = []
    for a, b, parola in parole:
        f0 = int(a / _PASSO)
        f1 = max(f0 + 1, int(np.ceil(b / _PASSO)))
        dentro = np.flatnonzero(attiva[f0:f1])
        if len(dentro) and dentro[0] > 0:
            a = min((f0 + int(dentro[0])) * _PASSO, b - 0.05)
        uscita.append((a, b, parola))
    return uscita


# Le frasi che Whisper «sente» nel silenzio e nella musica: sono i titoli di
# coda dei sottotitoli con cui e' stato addestrato.
_FANTASMI = ('sottotitoli', 'amara.org', 'qtss', 'grazie per la visione',
             'iscriviti', 'grazie a tutti per la visione', 'subtitles',
             'thanks for watching', 'www.', '.com')


def _inventato(seg) -> bool:
    """True se un pezzo di trascrizione e' quasi certamente inventato.

    Tre segni: Whisper stesso pensa che li' non si parli e ha poca fiducia in
    quello che ha scritto; il testo si ripete in cerchio (comprime troppo
    bene); oppure e' una delle frasi fantasma.
    """
    testo = seg.text.strip().lower()
    if not testo:
        return True
    if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8:
        return True
    if seg.compression_ratio > 2.4:
        return True
    if seg.avg_logprob < -1.2:
        return True
    return any(f in testo for f in _FANTASMI)


# ── L'incastro ───────────────────────────────────────────────────────────────

def _chi_dice(parole: list[tuple[float, float, str]], voci: Voci,
              campioni: np.ndarray) -> list[tuple[int | None, bool]]:
    """Per ogni parola: la persona che la dice, e se lo si sa con sicurezza.

    Se in quel momento parla una persona sola e' lei. Se ne parlano due, si
    prende l'impronta di un secondo e mezzo attorno alla parola e la si
    confronta con quelle due soltanto: fra due voci gia' note la scelta e'
    molto piu' facile che fra tutte.
    """
    estrattore = None
    esito: list[tuple[int | None, bool]] = []
    for a, b, _ in parole:
        f0 = int(a / _PASSO)
        f1 = max(f0 + 1, int(np.ceil(b / _PASSO)))
        att = voci.attivo[f0:f1].mean(0) if voci.persone else np.zeros(0)
        candidati = [p for p in range(voci.persone) if att[p] > 0.5]
        if not candidati and voci.persone:
            # Nessuno attivo proprio li': Whisper e il segmentatore non
            # tagliano allo stesso centesimo. Si guarda mezzo secondo attorno.
            g0, g1 = max(0, f0 - 30), f1 + 30
            att = voci.attivo[g0:g1].mean(0)
            if att.max() > 0:
                candidati = [int(att.argmax())]
        if not candidati:
            esito.append((None, False))
        elif len(candidati) == 1:
            p = candidati[0]
            esito.append((p, bool(voci.sicuro[f0:f1, p].mean() > 0.5)))
        else:
            if estrattore is None:
                estrattore = _estrattore()
            centro = (a + b) / 2
            i0 = max(0, int((centro - 0.75) * FREQUENZA))
            i1 = min(len(campioni), int((centro + 0.75) * FREQUENZA))
            somiglia = voci.centri[candidati] @ _impronta(estrattore, campioni[i0:i1])
            ordine = np.argsort(-somiglia)
            p = candidati[int(ordine[0])]
            esito.append((p, bool(somiglia[ordine[0]] - somiglia[ordine[1]] >= 0.1)))
    return _certezze(parole, esito)


def _corse(etichette: list) -> list[list[int]]:
    """Gli intervalli ``[inizio, fine)`` di etichette uguali consecutive."""
    corse: list[list[int]] = []
    for i, e in enumerate(etichette):
        if corse and etichette[corse[-1][0]] == e:
            corse[-1][1] = i + 1
        else:
            corse.append([i, i + 1])
    return corse


def _staccate(parole, prima: list[int], dopo: list[int]) -> bool:
    """True se fra due corse consecutive c'e' una pausa vera."""
    return parole[dopo[0]][0] - parole[prima[1] - 1][1] > PAUSA_MAX


def _certezze(parole: list[tuple[float, float, str]],
              esito: list[tuple[int | None, bool]]) -> list[tuple[int | None, bool]]:
    """Toglie i cambi di un istante, e decide dove la persona e' sicura.

    Una o due parole attribuite a un altro nel mezzo di un discorso sono
    quasi sempre un errore dell'impronta: a schermo diventerebbero un colore
    che lampeggia e sparisce. Una corsa piu' corta di un secondo, non
    staccata da pause su entrambi i lati, prende la persona di chi le sta
    attaccato.

    Poi la sicurezza: un tratto incerto fra due tratti sicuri della stessa
    persona e' sicuro; mezzo secondo incerto attaccato a un tratto sicuro
    della stessa voce anche; e al rovescio, una parola «sicura» in mezzo a un
    lungo tratto incerto della stessa voce e' un'isola, e torna incerta. I
    tratti incerti che restano sono quelli da guardare piu' da vicino (vedi
    ``_turni``).
    """
    chi = [p for p, _ in esito]
    certo = [s for _, s in esito]
    corse = _corse(chi)
    for n, (i, j) in enumerate(corse):
        if len(corse) == 1 or parole[j - 1][1] - parole[i][0] >= 1.0:
            continue
        prima = corse[n - 1] if n > 0 else None
        dopo = corse[n + 1] if n + 1 < len(corse) else None
        stacca_prima = prima is None or _staccate(parole, prima, [i, j])
        stacca_dopo = dopo is None or _staccate(parole, [i, j], dopo)
        if stacca_prima and stacca_dopo:
            continue
        vicino = prima if not stacca_prima else dopo
        for k in range(i, j):
            chi[k], certo[k] = chi[vicino[0]], certo[vicino[0]]

    etichetta = [p if s else None for p, s in zip(chi, certo)]
    corse = _corse(etichetta)
    for n, (i, j) in enumerate(corse):
        if etichetta[i] is not None or n == 0 or n + 1 == len(corse):
            continue
        prima, dopo = etichetta[corse[n - 1][0]], etichetta[corse[n + 1][0]]
        if prima is not None and prima == dopo and all(chi[k] == prima for k in range(i, j)):
            for k in range(i, j):
                etichetta[k] = prima

    corse = _corse(etichetta)
    for n, (i, j) in enumerate(corse):
        if etichetta[i] is not None or parole[j - 1][1] - parole[i][0] >= 1.0:
            continue
        for m in (n - 1, n + 1):
            if not 0 <= m < len(corse):
                continue
            vicino = etichetta[corse[m][0]]
            staccato = (_staccate(parole, corse[m], [i, j]) if m < n
                        else _staccate(parole, [i, j], corse[m]))
            if vicino is not None and not staccato and all(chi[k] == vicino for k in range(i, j)):
                for k in range(i, j):
                    etichetta[k] = vicino
                break

    corse = _corse(etichetta)
    for n, (i, j) in enumerate(corse):
        if etichetta[i] is None or parole[j - 1][1] - parole[i][0] >= 1.0:
            continue
        for m in (n - 1, n + 1):
            if not 0 <= m < len(corse) or etichetta[corse[m][0]] is not None:
                continue
            a, b = corse[m]
            staccato = (_staccate(parole, corse[m], [i, j]) if m < n
                        else _staccate(parole, [i, j], corse[m]))
            if not staccato and chi[a] == chi[i] and parole[b - 1][1] - parole[a][0] >= 1.0:
                for k in range(i, j):
                    etichetta[k] = None
                break
    return [(p, e is not None) for p, e in zip(chi, etichetta)]


# ── I tratti incerti: dove cambia voce, e chi e' ─────────────────────────────
#
# Dove il segmentatore non sa separare le voci - due persone con voci simili
# che si rispondono in fretta - i cambi di turno lasciano comunque tre segni,
# e nessuno basta da solo:
#
#   il calo      fra due turni la probabilita' che qualcuno parli scende,
#                anche quando la pausa e' troppo breve per Whisper;
#   l'affiorare  nel cambio una seconda voce affiora per un istante, anche
#                quando la decisione netta non la vede;
#   lo scarto    la voce del secondo e mezzo prima somiglia poco a quella del
#                secondo e mezzo dopo (in media su tre lunghezze, perche' da
#                una sola misura e' troppo nervosa).
#
# Misurati su un dialogo vero: nei cambi veri il punteggio combinato supera
# quasi sempre 0,37; dentro la frase di una persona resta sotto.

_TRATTO_INCERTO = 2.0   # secondi: un'incertezza piu' corta non si indaga
_CONTESTI = (1.0, 1.5, 2.0)
_SOGLIA_CAMBIO = 0.37
_RAGGIO_CAMBIO = 0.8    # secondi: un cambio e' il punteggio piu' alto nel suo intorno
_TURNO_MINIMO = 0.6     # secondi di voce: un turno piu' corto non si stacca
_DINAMICA_RUMORE = 13.0  # dB fra voci e pause: sotto, il fondo copre le pause


def _audio_parole(campioni: np.ndarray, parole, indici) -> np.ndarray:
    return np.concatenate([campioni[int(parole[k][0] * FREQUENZA):
                                    int(parole[k][1] * FREQUENZA)] for k in indici])


def _voce(parole, indici) -> float:
    return sum(parole[k][1] - parole[k][0] for k in indici)


def _scarto(parole, k: int, i: int, j: int, campioni, estrattore) -> float | None:
    """Quanto la voce prima della parola ``k`` e' diversa da quella dopo."""
    valori = []
    for contesto in _CONTESTI:
        sinistra, destra = [], []
        m = k - 1
        while m >= i and _voce(parole, sinistra) < contesto:
            sinistra.append(m)
            m -= 1
        m = k
        while m < j and _voce(parole, destra) < contesto:
            destra.append(m)
            m += 1
        if _voce(parole, sinistra) < 0.4 or _voce(parole, destra) < 0.4:
            continue
        a = _impronta(estrattore, _audio_parole(campioni, parole, sinistra[::-1]))
        b = _impronta(estrattore, _audio_parole(campioni, parole, destra))
        valori.append(1.0 - float(a @ b))
    return float(np.mean(valori)) if valori else None


def _rumoroso(audio: np.ndarray) -> bool:
    """True se sotto le voci c'e' un fondo che non si ferma mai.

    Si confronta il volume dei momenti piu' forti con quello dei piu' deboli,
    a pezzi di un decimo di secondo. Dove si parla nel silenzio le pause sono
    molto piu' basse delle voci (15 dB e oltre, misurati in studio); sopra la
    musica e il pubblico di un concerto la differenza restava sotto gli 11.
    """
    pezzo = FREQUENZA // 10
    if len(audio) < 10 * pezzo:
        return False
    rms = np.sqrt((audio[:len(audio) // pezzo * pezzo].reshape(-1, pezzo) ** 2).mean(1))
    db = 20 * np.log10(rms + 1e-9)
    return float(np.percentile(db, 90) - np.percentile(db, 10)) < _DINAMICA_RUMORE


def _punti_di_cambio(parole, i: int, j: int, voci: Voci, campioni: np.ndarray,
                     estrattore) -> list[int]:
    """Gli indici delle parole, fra ``i`` e ``j``, con cui comincia un turno."""
    def fot(t: float) -> int:
        return max(0, min(len(voci.parla) - 1, int(t / _PASSO)))

    scarti = {k: _scarto(parole, k, i, j, campioni, estrattore)
              for k in range(i + 1, j)}
    cali, affiorano = {}, {}
    for k in range(i + 1, j):
        g0, g1 = parole[k - 1][1] - 0.05, parole[k][0] + 0.05
        cali[k] = 1.0 - float(voci.parla[fot(g0):fot(g1) + 1].min())
        affiorano[k] = float(voci.seconda[fot(g0 - 0.25):fot(g1 + 0.25) + 1].max())

    # Lo scarto conta per quanto sporge dal suo livello tipico nel tratto. Nel
    # rumore - una sala piena, col pubblico che urla e la musica sotto - anche
    # il calo e la seconda voce: li' una «seconda voce» c'e' sempre, e senza
    # questa correzione ogni pausa diventava un cambio di persona. Nel
    # silenzio no: su un dialogo in studio il livello tipico era gia' quello
    # di un cambio, e toglierlo cancellava i cambi veri.
    def livello(valori: dict) -> float:
        noti = [v for v in valori.values() if v is not None]
        return float(np.median(noti)) if noti else 0.0

    tipico_scarto = livello(scarti)
    if _rumoroso(campioni[int(parole[i][0] * FREQUENZA):int(parole[j - 1][1] * FREQUENZA)]):
        tipico_calo, tipico_affiora = livello(cali), livello(affiorano)
    else:
        tipico_calo = tipico_affiora = 0.0
    punteggio = {}
    for k in range(i + 1, j):
        scarto = scarti[k] - tipico_scarto if scarti[k] is not None else 0.0
        punteggio[k] = (0.5 * scarto + 0.6 * (cali[k] - tipico_calo)
                        + (affiorano[k] - tipico_affiora))

    presi: list[int] = []
    for k in sorted(punteggio, key=lambda k: -punteggio[k]):
        p = punteggio[k]
        if p < _SOGLIA_CAMBIO:
            break
        t = parole[k][0]
        if any(punteggio[h] > p for h in punteggio
               if abs(parole[h][0] - t) <= _RAGGIO_CAMBIO):
            continue
        confini = sorted(presi + [k])
        pezzi = zip([i] + confini, confini + [j])
        if all(_voce(parole, range(a, b)) >= _TURNO_MINIMO for a, b in pezzi):
            presi.append(k)
    return sorted(presi)


def _due_voci(impronte: np.ndarray) -> list[int]:
    """Divide i turni di un tratto fra due voci.

    Ogni confine fra due turni e' un cambio di voce appena misurato, quindi
    il punto di partenza e' l'alternanza - A, B, A, B - che e' la forma di
    quasi ogni scambio fra due persone. Poi si prova a spostare un turno alla
    volta dall'altra parte, e lo spostamento resta se le somiglianze fra i
    turni lo sostengono piu' di quanto l'alternanza lo sconsigli.
    """
    n = len(impronte)
    if n < 2:
        return [0] * n
    s = impronte @ impronte.T
    s = s - s[np.triu_indices(n, 1)].mean()
    # Il peso dell'alternanza e' alto di proposito: si arriva qui proprio
    # perche' le impronte non bastavano a distinguere le voci, e su un dialogo
    # vero le somiglianze fra i turni si contraddicevano (A somigliava a C ma
    # non a E, E somigliava ad A ma non a C). Spostano un turno solo quando
    # sono concordi.
    vicinato = 0.6

    def punteggio(g: list[int]) -> float:
        tot = 0.0
        for a in range(n):
            for b in range(a + 1, n):
                tot += s[a, b] if g[a] == g[b] else -s[a, b]
        tot += vicinato * sum(1 if g[a] != g[a + 1] else -1 for a in range(n - 1))
        return tot

    gruppi = [a % 2 for a in range(n)]
    migliore = punteggio(gruppi)
    migliorato = True
    while migliorato:
        migliorato = False
        for a in range(n):
            prova = gruppi.copy()
            prova[a] = 1 - prova[a]
            p = punteggio(prova)
            if p > migliore + 1e-6:
                gruppi, migliore, migliorato = prova, p, True
    return gruppi


def _riconosci(medie: list[np.ndarray], centri: np.ndarray,
               nuovi: list[np.ndarray]) -> list[int]:
    """A quale persona appartiene ogni voce di un tratto incerto.

    Alla piu' simile fra quelle gia' note; se non somiglia a nessuna, e' una
    voce nuova - gia' incontrata in un altro tratto incerto, o mai sentita, e
    allora prende un colore suo. Due voci dello stesso tratto sono per forza
    due persone diverse.
    """
    tutte = list(centri) + nuovi
    somiglia = [np.array([float(m @ c) for c in tutte]) if tutte else np.zeros(0)
                for m in medie]
    scelte: dict[int, int] = {}
    # Sceglie per prima la voce che somiglia di piu' a qualcuno: e' la piu'
    # facile da riconoscere. Lei si accontenta di una somiglianza discreta; la
    # seconda, che trova il posto migliore gia' preso, deve somigliare
    # chiaramente a un'altra persona nota, altrimenti e' una persona nuova.
    # Su un dialogo vero le due voci di una scena somigliavano entrambe alla
    # stessa persona nota: senza questa regola la seconda finiva sul colore di
    # uno che in quella scena non c'era.
    for n in sorted(range(len(medie)),
                    key=lambda n: -(somiglia[n].max() if len(somiglia[n]) else 0)):
        soglia = 0.4 if not scelte else 0.55
        scelta = None
        for p in np.argsort(-somiglia[n]):
            p = int(p)
            if p not in scelte.values() and somiglia[n][p] >= soglia:
                scelta = p
                break
        if scelta is None:
            nuovi.append(medie[n])
            tutte.append(medie[n])
            scelta = len(tutte) - 1
        scelte[n] = scelta
    return [scelte[n] for n in range(len(medie))]


def _turni(parole: list[tuple[float, float, str]],
           chi: list[tuple[int | None, bool]], voci: Voci,
           campioni: np.ndarray) -> list[tuple[int, int]]:
    """Per ogni parola: la persona (mai «non si sa») e il turno.

    Dove la persona e' sicura, il turno cambia quando cambia la persona. Nei
    tratti incerti di almeno due secondi si cercano i punti in cui la voce
    cambia, si dividono i turni fra due voci e si riconosce chi sono. Il
    numero del turno serve a chi impagina: anche quando due turni finiscono
    con lo stesso colore - voci che non si sono potute distinguere - restano
    due battute separate, con la lineetta.
    """
    n = len(parole)
    persona = [p for p, _ in chi]
    certo = [c for _, c in chi]
    # Chi non ha nessuno attorno prende la persona piu' vicina.
    for k in range(n):
        if persona[k] is None:
            vicini = [h for h in range(n) if persona[h] is not None]
            persona[k] = (min(vicini, key=lambda h: abs(parole[h][0] - parole[k][0]))
                          if vicini else 0)
    nuovi: list[np.ndarray] = []
    cambi: set[int] = set()
    estrattore = None
    for i, j in _corse(certo):
        if certo[i] or parole[j - 1][1] - parole[i][0] < _TRATTO_INCERTO:
            continue
        if estrattore is None:
            estrattore = _estrattore()
        tagli = _punti_di_cambio(parole, i, j, voci, campioni, estrattore)
        confini = [i] + tagli + [j]
        pezzi = list(zip(confini, confini[1:]))
        impronte = np.array([_impronta(estrattore, _audio_parole(campioni, parole, range(a, b)))
                             for a, b in pezzi])
        gruppi = _due_voci(impronte)
        medie = []
        for g in sorted(set(gruppi)):
            m = impronte[[x == g for x in gruppi]].mean(0)
            medie.append(m / max(float(np.linalg.norm(m)), 1e-9))
        chi_gruppo = _riconosci(medie, voci.centri, nuovi)
        ordine = sorted(set(gruppi))
        for (a, b), g in zip(pezzi, gruppi):
            for k in range(a, b):
                persona[k] = chi_gruppo[ordine.index(g)]
        cambi.update(tagli)
        log.info('Tratto incerto %.1f-%.1f s: %d turni, persone %s',
                 parole[i][0], parole[j - 1][1], len(pezzi), chi_gruppo)

    # Un turno di una o due parole e meno di un secondo scarso - «– mi»,
    # «– ma» da soli a schermo - in un video pulito e' quasi sempre un errore,
    # in uno rumoroso lo e' sempre: si attacca al turno vicino da cui non lo
    # separa una pausa, e ne prende la persona.
    def spezza() -> list[list[int]]:
        confini = [0] + [k for k in range(1, n)
                         if persona[k] != persona[k - 1] or k in cambi] + [n]
        return [[a, b] for a, b in zip(confini, confini[1:])]

    cambiato = True
    while cambiato:
        cambiato = False
        pezzi = spezza()
        for m, (a, b) in enumerate(pezzi):
            if len(pezzi) == 1 or b - a > 2 or _voce(parole, range(a, b)) >= 0.8:
                continue
            distanze = []
            if m > 0:
                distanze.append((parole[a][0] - parole[a - 1][1], pezzi[m - 1]))
            if m + 1 < len(pezzi):
                distanze.append((parole[b][0] - parole[b - 1][1], pezzi[m + 1]))
            pausa, vicino = min(distanze, key=lambda d: d[0])
            if pausa > PAUSA_MAX:
                continue
            for k in range(a, b):
                persona[k] = persona[vicino[0]]
            # Sparisce il confine verso il vicino; quello dall'altra parte
            # resta, anche se ora le persone ai due lati coincidessero.
            verso_dopo = vicino[0] > a
            cambi.discard(b if verso_dopo else a)
            altro = a if verso_dopo else b
            if 0 < altro < n:
                cambi.add(altro)
            cambiato = True
            break

    esito = []
    turno = 0
    for k in range(n):
        if k and (persona[k] != persona[k - 1] or k in cambi):
            turno += 1
        esito.append((int(persona[k]), turno))
    return esito


# ── L'impaginazione ──────────────────────────────────────────────────────────
#
# Le regole sono quelle dei sottotitoli fatti bene (linee guida della BBC e
# dei sottotitolatori): al piu' due righe, spezzate nei punti naturali; una
# frase non si divide fra due sottotitoli, se si puo' evitare; ogni
# sottotitolo resta a schermo abbastanza da leggerlo; la maiuscola a inizio
# frase; le parole restano quelle dette, errori e parolacce compresi.

# Le parole che non chiudono mai una riga ne' un sottotitolo: articoli,
# preposizioni, congiunzioni. «vedere il sangue che scorre dalle braccia e
# poi una» / «donna» si legge male; «... dalle braccia» / «e poi una donna»
# bene.
_DEBOLI = frozenset("""
    il lo la i gli le un uno una l' un' di a da in con su per tra fra e ed o
    od ma che se non del dello della dei degli delle al allo alla ai agli
    alle dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul
    sullo sulla sui sugli sulle col mi ti si ci vi ne cui come quando
    perché anche poi più molto è
    the a an of to in on at for and or but with from by
""".split())

_FINE_FRASE = '.?!…'
_INCISO = ',;:'


def _nudo(parola: str) -> str:
    return parola.strip().lower().strip('«»"()[]')


def _costo_taglio(parola: str) -> float:
    """Quanto costa chiudere un sottotitolo dopo questa parola."""
    p = parola.strip()
    if p[-1:] in _FINE_FRASE:
        return 0.0
    if p[-1:] in _INCISO:
        return 2.0
    if _nudo(p) in _DEBOLI:
        return 12.0
    return 6.0


def _tagli_frase(parole, i: int, j: int) -> list[tuple[int, int]]:
    """Divide le parole ``[i, j)``, dette di fila da una persona, in
    sottotitoli.

    Fra tutti i modi possibili si sceglie quello che costa meno: ogni
    sottotitolo in piu' costa, tagliare a fine frase non costa niente, a una
    virgola poco, a meta' frase di piu', dopo un «di» o un «che» moltissimo.
    Nessun sottotitolo supera RIGHE_MAX righe ne' DURATA_MAX; uno di due righe
    che contiene la fine di una frase e l'inizio della successiva paga un
    supplemento, perche' la frase dopo resta spezzata.
    """
    n = j - i
    migliore = [0.0] + [float('inf')] * n
    da = [0] * (n + 1)
    for e in range(1, n + 1):
        for s in range(e - 1, -1, -1):
            testo = ''.join(p[2] for p in parole[i + s:i + e]).strip()
            durata = parole[i + e - 1][1] - parole[i + s][0]
            # Il limite di durata vale per i sottotitoli pieni; uno corto
            # puo' restare di piu', fino a due secondi: mostra poche parole
            # in anticipo, e chi parla lentamente sopra la musica non finisce
            # spezzato in «vorrei» / «regalare a voi» / «una perla».
            limite = DURATA_MAX + 2.0 * max(0.0, 1 - len(testo) / RIGA_MAX)
            if e - s > 1 and (len(testo) > RIGHE_MAX * RIGA_MAX
                              or durata > limite):
                break
            # Due righe da 40 non bastano sempre a 80 caratteri: dipende da
            # dove cadono gli spazi. E si tiene posto per la lineetta dei
            # dialoghi, che qui non si sa ancora se ci sara'.
            righe = _due_righe(testo, RIGA_MAX - 2) if RIGHE_MAX > 1 else [testo]
            if e - s > 1 and max(map(len, righe)) > RIGA_MAX - 2:
                continue
            costo = migliore[s] + 3.0
            if e < n:
                costo += _costo_taglio(parole[i + e - 1][2])
            if len(testo) < 15:
                costo += 4.0
            if len(testo) > RIGA_MAX:
                costo += 3.0 * sum(1 for p in parole[i + s:i + e - 1]
                                   if p[2].strip()[-1:] in _FINE_FRASE)
            if costo < migliore[e]:
                migliore[e], da[e] = costo, s
    tagli, e = [], n
    while e > 0:
        tagli.append((i + da[e], i + e))
        e = da[e]
    return tagli[::-1]


def _maiuscola(parola: str) -> str:
    for n, c in enumerate(parola):
        if c.isalpha():
            return parola[:n] + c.upper() + parola[n + 1:]
    return parola


def battute(parole: list[tuple[float, float, str]],
            turni: list[tuple[int, int]]) -> list[Battuta]:
    """Le parole raggruppate in battute: stesso turno, niente pause lunghe,
    non piu' di RIGHE_MAX righe ne' DURATA_MAX secondi, e tagliate dove la
    frase lo permette (vedi ``_tagli_frase``)."""
    corse: list[list[int]] = []
    for k in range(len(parole)):
        if (k and turni[k][1] == turni[k - 1][1]
                and parole[k][0] - parole[k - 1][1] <= PAUSA_MAX):
            corse[-1][1] = k + 1
        else:
            corse.append([k, k + 1])
    uscita: list[Battuta] = []
    for i, j in corse:
        for a, b in _tagli_frase(parole, i, j):
            uscita.append(Battuta(parole[a][0], parole[b - 1][1], turni[a][0],
                                  [p[2] for p in parole[a:b]], turno=turni[a][1]))

    # Un frammento di mezzo secondo («Ah,») da solo a schermo lampeggia e non
    # lo legge nessuno: si attacca alla battuta vicina dello stesso turno, se
    # non c'e' una pausa in mezzo e se ci sta.
    unite: list[Battuta] = []
    for b in uscita:
        breve = b.fine - b.inizio < 0.6 and len(b.parole) <= 2
        prima = unite[-1] if unite else None
        if (breve and prima is not None and prima.turno == b.turno
                and b.inizio - prima.fine <= PAUSA_MAX
                and len(prima.testo) + len(b.testo) <= RIGHE_MAX * RIGA_MAX):
            prima.parole += b.parole
            prima.fine = b.fine
            continue
        unite.append(b)

    # Se non ci stava con quella prima, e quella dopo parte subito, il
    # frammento e' quasi sempre l'inizio della frase dopo che l'impronta ha
    # dato a un altro: «– il» / «– volume, un po' meno volume», «– di» /
    # «– Cristo». Va con la frase dopo, e ne prende persona e turno. Si misura
    # in lettere e non in secondi: sopra la musica Whisper allunga le parole,
    # e un «mi» arrivava a durare quattro secondi. Per lo stesso motivo la
    # frase unita comincia poco prima della sua fine, non al suo inizio.
    for n in range(len(unite) - 2, -1, -1):
        b, dopo = unite[n], unite[n + 1]
        if (len(b.testo) <= 4 and dopo.inizio - b.fine < 0.35
                and len(b.testo) + len(dopo.testo) <= RIGHE_MAX * RIGA_MAX):
            dopo.parole = b.parole + dopo.parole
            dopo.inizio = max(b.inizio, b.fine - 0.6)
            del unite[n]

    # Una battuta che apre o chiude uno scambio veloce porta la lineetta: e'
    # il segno che parla un altro, e si legge anche quando i colori non
    # bastano a dirlo.
    for n, b in enumerate(unite):
        for m in (n - 1, n + 1):
            if 0 <= m < len(unite) and unite[m].turno != b.turno:
                a, c = (unite[m], b) if m < n else (b, unite[m])
                if c.inizio - a.fine < 1.0:
                    b.scambio = True

    # La maiuscola a inizio frase. Whisper, che qui trascrive ogni pezzo
    # senza ricordare il precedente, comincia spesso in minuscolo: «è viva!».
    # Una frase comincia dopo un punto, o quando parla un altro dopo una
    # pausa: se l'altro attacca senza respiro, continua la frase del primo
    # («questa chitarra» / «posseduta questa chitarra»).
    for n, b in enumerate(unite):
        prima = unite[n - 1] if n else None
        if (prima is None or prima.testo[-1:] in _FINE_FRASE
                or (prima.turno != b.turno and b.inizio - prima.fine >= 0.3)):
            b.parole[0] = _maiuscola(b.parole[0])
    return unite


def tradotte(lista: list[Battuta], da: str, a: str) -> list[Battuta]:
    """Le battute in un'altra lingua, con gli stessi tempi e gli stessi colori.

    Si traducono frasi intere, non sottotitoli (vedi ``traduzione``): le
    battute consecutive di un turno si rimettono insieme fino alla fine della
    frase. La traduzione si ridivide poi con ``_tagli_frase``, dando a ogni
    parola tradotta l'istante in cui l'originale era arrivato allo stesso
    punto della frase, misurato in lettere.
    """
    from server.video import traduzione

    frasi: list[list[Battuta]] = []
    for b in lista:
        if (frasi and frasi[-1][-1].turno == b.turno
                and frasi[-1][-1].testo[-1:] not in _FINE_FRASE
                and b.inizio - frasi[-1][-1].fine <= 2 * PAUSA_MAX):
            frasi[-1].append(b)
        else:
            frasi.append([b])
    testi = [' '.join(b.testo for b in f) for f in frasi]
    versioni = traduzione.traduci(testi, da, a, os.path.join(_cartella_modelli(), 'traduzione'))

    uscita: list[Battuta] = []
    for frase, testo, versione in zip(frasi, testi, versioni):
        # Il tempo in cui l'originale arriva a ogni frazione della frase: a
        # pezzi, battuta per battuta, lettera per lettera.
        punti, lette = [(0.0, frase[0].inizio)], 0
        for b in frase:
            lette += len(b.testo) + 1
            punti.append((lette / (len(testo) + 1), b.fine))

        def quando(f: float) -> float:
            for (f0, t0), (f1, t1) in zip(punti, punti[1:]):
                if f <= f1:
                    return t0 + (t1 - t0) * (f - f0) / max(f1 - f0, 1e-9)
            return punti[-1][1]

        parole_tr, pos = [], 0
        for p in versione.split():
            a0 = quando(pos / max(len(versione), 1))
            pos += len(p) + 1
            parole_tr.append((a0, quando(min(pos, len(versione)) / max(len(versione), 1)), ' ' + p))
        if not parole_tr:
            continue
        for n, (i, j) in enumerate(_tagli_frase(parole_tr, 0, len(parole_tr))):
            uscita.append(Battuta(parole_tr[i][0], parole_tr[j - 1][1], frase[0].parlante,
                                  [p[2] for p in parole_tr[i:j]], turno=frase[0].turno,
                                  scambio=frase[0].scambio and n == 0))
    log.info('Tradotte %d frasi in %s', len(frasi), traduzione.NOMI.get(a, a))
    return uscita


def etichette_tradotte(lista: list[Battuta], a: str) -> list[Battuta]:
    """Le etichette dei suoni nella lingua della traduzione."""
    from server.video import traduzione

    nomi = traduzione.ETICHETTE.get(a, {})
    uscita = []
    for b in lista:
        nome = b.testo.strip('[]')
        uscita.append(Battuta(b.inizio, b.fine, b.parlante, [f'[{nomi.get(nome, nome)}]'],
                              turno=b.turno))
    return uscita


def riquadri(lista: list[Battuta], tagli_scena: list[float] | None = None
             ) -> list[Riquadro]:
    """Quello che va a schermo, istante per istante.

    Due battute di turni diversi che si rincorrono - la seconda comincia
    prima che la prima finisca, o subito dopo - e che stanno in una riga
    ciascuna diventano un dialogo a elenco: la prima compare da sola, e
    quando parte la seconda questa compare sotto, mentre la prima resta. Se
    ne arriva una terza, la seconda sale e la terza va sotto.
    """
    uscita: list[Riquadro] = []
    i = 0
    while i < len(lista):
        b = lista[i]
        catena = [b]
        while (i + len(catena) < len(lista)
               and _si_rincorrono(catena[-1], lista[i + len(catena)])):
            catena.append(lista[i + len(catena)])
        if len(catena) == 1:
            righe = _due_righe(b.testo, RIGA_MAX - 2 if b.scambio else RIGA_MAX)
            uscita.append(Riquadro(b.inizio, b.fine,
                                   [(b.parlante, r, b.scambio and n == 0)
                                    for n, r in enumerate(righe)]))
        else:
            # La prima da sola, poi a coppie: (1,2), (2,3), ...
            primo = catena[0]
            if catena[1].inizio - primo.inizio >= 0.3:
                uscita.append(Riquadro(primo.inizio, catena[1].inizio,
                                       [(primo.parlante, primo.testo, True)]))
            for sopra, sotto in zip(catena, catena[1:]):
                fine = max(sotto.fine, sopra.fine)
                uscita.append(Riquadro(sotto.inizio, fine,
                                       [(sopra.parlante, sopra.testo, True),
                                        (sotto.parlante, sotto.testo, True)]))
        i += len(catena)
    _tempi(uscita, sorted(tagli_scena or []))
    return [r for r in uscita if r.fine > r.inizio]


# Quanto si legge: dodici parole in quattro secondi, circa 17 caratteri al
# secondo. Un sottotitolo resta a schermo almeno il tempo di leggerlo, e mai
# meno di un secondo e mezzo, se lo spazio prima del successivo lo permette.
CARATTERI_AL_SECONDO = 17.0
DURATA_MINIMA = 1.5
# Un sottotitolo non scavalca un cambio di scena: se comincia poco prima del
# taglio parte col taglio, se finisce poco dopo si chiude sul taglio.
_AGGANCIO_SCENA = 0.5


def _tempi(uscita: list[Riquadro], tagli: list[float]) -> None:
    """Inizio e fine a schermo di ogni riquadro: il tempo di leggerlo, senza
    scavalcare il successivo ne' un cambio di scena."""
    def taglio_in(a: float, b: float) -> float | None:
        dentro = [t for t in tagli if a < t < b]
        return dentro[0] if dentro else None

    for r in uscita:
        t = taglio_in(r.inizio, r.inizio + _AGGANCIO_SCENA)
        if t is not None and t < r.fine:
            r.inizio = t
    for n, r in enumerate(uscita):
        seguente = uscita[n + 1].inizio if n + 1 < len(uscita) else float('inf')
        lettere = sum(len(testo) for _, testo, _ in r.righe)
        parlato = r.fine
        fine = max(parlato, r.inizio + max(DURATA_MINIMA,
                                           lettere / CARATTERI_AL_SECONDO))
        # Il tempo in piu' per leggere si ferma al cambio di scena; e se il
        # parlato finisce appena dopo un taglio, si chiude sul taglio.
        t = taglio_in(parlato, fine)
        if t is not None:
            fine = max(parlato, t - 0.02)
        t = taglio_in(parlato - _AGGANCIO_SCENA, parlato)
        if t is not None and t - r.inizio >= 1.0:
            fine = t - 0.02
        if seguente > r.inizio:
            fine = min(fine, seguente - 0.02)
        r.fine = fine


def _si_rincorrono(a: Battuta, b: Battuta) -> bool:
    return (a.turno != b.turno
            and ETICHETTA not in (a.parlante, b.parlante)
            and b.inizio - a.fine < 0.6
            and len(a.testo) <= RIGA_MAX - 2 and len(b.testo) <= RIGA_MAX - 2)


def _due_righe(testo: str, larghezza: int = RIGA_MAX) -> list[str]:
    """Spezza una battuta in (al piu') due righe, nel punto piu' naturale:
    dopo un segno di punteggiatura se c'e', mai dopo un articolo, una
    preposizione o una congiunzione, e con le due righe di lunghezza simile.
    ``larghezza`` e' lo spazio per il testo: due caratteri in meno quando
    davanti va la lineetta."""
    if len(testo) <= larghezza - 2:
        return [testo]
    parole = testo.split(' ')
    migliore, costo_min = [testo], float('inf')
    for i in range(1, len(parole)):
        a, b = ' '.join(parole[:i]), ' '.join(parole[i:])
        costo = abs(len(a) - len(b))
        if max(len(a), len(b)) > larghezza:
            costo += 100
        if a[-1:] in _FINE_FRASE + _INCISO:
            costo -= 20
        if _nudo(parole[i - 1]) in _DEBOLI:
            costo += 20
        if costo < costo_min:
            migliore, costo_min = [a, b], costo
    return migliore


# ── I suoni e le scene ───────────────────────────────────────────────────────
#
# Un buon sottotitolo non trascrive solo le parole: dice anche quello che si
# sente e non si vede, tra parentesi quadre - [musica], [applausi], [il
# pubblico urla]. Qui lo dice CED (un modello addestrato su AudioSet, via
# sherpa-onnx), che a ogni secondo di audio da' la probabilita' di 527
# classi di suoni. Le etichette vanno solo dove non c'e' gia' testo a
# schermo: sopra una battuta coprirebbero piu' di quanto aggiungono.
#
# Si usa CED «mini»: su un concerto dal vivo e' l'unico dei due provati che
# sente il pubblico (0,8 contro 0,3 del «tiny»), e su un dialogo pulito non
# segna niente. Un video di dieci minuti costa mezzo minuto.

_SUONI = (f'{_GITHUB}/audio-tagging-models/'
          'sherpa-onnx-ced-mini-audio-tagging-2024-04-19.tar.bz2')
_SUONI_FINESTRA = 2.0   # secondi ascoltati per ogni giudizio
_SUONI_PASSO = 1.0      # un giudizio al secondo

# Le classi che interessano, e sopra quale probabilita' contano. I nomi sono
# quelli di AudioSet.
_CANTO = ('Singing', 'Male singing', 'Female singing', 'Choir', 'Opera')
_CLASSI = ('Music', 'Speech', 'Crowd', 'Cheering', 'Applause', 'Clapping',
           'Laughter') + _CANTO

# Un'etichetta resta a schermo al piu' cosi': dice che il suono comincia, non
# lo accompagna fino alla fine.
_ETICHETTA_MAX = 3.0
# La stessa etichetta non si ripete nello stesso silenzio, e fra un
# silenzio e l'altro solo a distanza: sei [voci incomprensibili] in venti
# secondi dicono meno di una. [musica] ancora meno spesso: sotto un discorso
# fatto sopra la musica basta ricordarlo ogni tanto.
_RIPETI_DOPO = 10.0
_RIPETI_MUSICA_DOPO = 30.0


def _modello_suoni() -> tuple[str, str]:
    cartella = _cartella_modelli()
    modello = os.path.join(cartella, 'ced-mini-audio-tagging.int8.onnx')
    etichette = os.path.join(cartella, 'ced-mini-audio-tagging.labels.csv')
    if not (os.path.isfile(modello) and os.path.isfile(etichette)):
        with tarfile.open(fileobj=io.BytesIO(_scarica(_SUONI))) as tar:
            for membro in tar.getmembers():
                if membro.name.endswith('/model.int8.onnx'):
                    _salva(modello, tar.extractfile(membro).read())
                elif membro.name.endswith('/class_labels_indices.csv'):
                    _salva(etichette, tar.extractfile(membro).read())
    return modello, etichette


def suoni(campioni: np.ndarray) -> dict[str, np.ndarray]:
    """Per ogni classe di ``_CLASSI``, la probabilita' secondo per secondo:
    il valore ``k`` riguarda i secondi da ``k`` a ``k + 2``."""
    import sherpa_onnx

    modello, etichette = _modello_suoni()
    tag = sherpa_onnx.AudioTagging(sherpa_onnx.AudioTaggingConfig(
        model=sherpa_onnx.AudioTaggingModelConfig(
            ced=modello, num_threads=max(1, min(4, os.cpu_count() or 1))),
        labels=etichette, top_k=527))
    passo, finestra = int(_SUONI_PASSO * FREQUENZA), int(_SUONI_FINESTRA * FREQUENZA)
    uscita: dict[str, list[float]] = {c: [] for c in _CLASSI}
    for s in range(0, max(1, len(campioni) - finestra + 1), passo):
        flusso = tag.create_stream()
        flusso.accept_waveform(FREQUENZA, campioni[s:s + finestra])
        p = {e.name: e.prob for e in tag.compute(flusso)}
        for c in _CLASSI:
            uscita[c].append(p.get(c, 0.0))
    return {c: np.array(v, np.float32) for c, v in uscita.items()}


def _suono(s: dict[str, np.ndarray], t: float, parla: float) -> str | None:
    """Cosa si sente attorno all'istante ``t``, se vale un'etichetta.

    ``parla`` e' quanto il segmentatore sente voci li': voci senza parole
    trascritte sono urla che Whisper non ha capito. In sala le urla sono del
    pubblico; altrove si dice solo che non si capiscono.
    """
    k = max(0, min(len(s['Music']) - 1, int(round(t - _SUONI_FINESTRA / 2))))
    v = {c: float(s[c][k]) for c in s}
    # Il pubblico si sente a ondate: per dire di chi sono le voci si guarda
    # anche il secondo prima e quello dopo.
    folla = max(float(s['Crowd'][max(0, k - 1):k + 2].max()),
                2 * float(s['Cheering'][max(0, k - 1):k + 2].max()))
    if max(v['Applause'], v['Clapping']) >= 0.3:
        return 'applausi'
    if v['Laughter'] >= 0.3:
        return 'risate'
    if v['Cheering'] >= 0.35:
        return 'il pubblico esulta'
    if parla >= 0.5:
        if folla >= 0.15:
            return 'il pubblico urla'
        return 'voci incomprensibili'
    if v['Crowd'] >= 0.3:
        return 'brusio del pubblico'
    if max(v[c] for c in _CANTO) >= 0.3:
        return 'canto'
    if v['Music'] >= 0.5 and v['Speech'] < 0.5:
        return 'musica'
    return None


def etichette(lista: list[Battuta], s: dict[str, np.ndarray], voci: Voci,
              durata: float) -> list[Battuta]:
    """Le etichette dei suoni, nei vuoti fra le battute lunghi almeno quanto
    serve a leggerle. Cominciano quando comincia il suono, mai prima: un
    [applausi] che anticipa gli applausi rovina il momento."""
    uscita: list[Battuta] = []
    # Una battuta occupa lo schermo anche dopo l'ultima parola, finche' non
    # la si e' letta (vedi ``_tempi``): l'etichetta non gliela deve rubare.
    occupato = [(b.inizio, max(b.fine, b.inizio + max(
        DURATA_MINIMA, len(b.testo) / CARATTERI_AL_SECONDO))) for b in lista]
    vuoti, t = [], 0.0
    for a, b in sorted(occupato):
        if a - t >= DURATA_MINIMA:
            vuoti.append((t, a))
        t = max(t, b)
    if durata - t >= DURATA_MINIMA:
        vuoti.append((t, durata))

    def parla(t: float) -> float:
        f0, f1 = int(t / _PASSO), int((t + 1.0) / _PASSO)
        return float((voci.parla[f0:f1] > 0.5).mean()) if f1 > f0 else 0.0

    ultima: dict[str, float] = {}
    for g0, g1 in vuoti:
        dette: set[str] = set()
        t = g0 + 0.1
        while g1 - t >= DURATA_MINIMA:
            nome = _suono(s, t, parla(t))
            distanza = _RIPETI_MUSICA_DOPO if nome == 'musica' else _RIPETI_DOPO
            if (nome is None or nome in dette
                    or t - ultima.get(nome, -distanza) < distanza):
                t += 0.5
                continue
            # Fin dove continua lo stesso suono, entro il vuoto.
            fine = t + 1.0
            while (fine < min(g1, t + _ETICHETTA_MAX)
                   and _suono(s, fine, parla(fine)) == nome):
                fine += 0.5
            fine = min(g1 - 0.1, max(fine, t + DURATA_MINIMA))
            uscita.append(Battuta(t, fine, ETICHETTA, [f'[{nome}]'],
                                  turno=-1 - len(uscita)))
            dette.add(nome)
            ultima[nome] = t
            t = fine + 0.5
    if uscita:
        log.info('Suoni: %s', ', '.join(f'{b.testo} a {b.inizio:.0f} s'
                                         for b in uscita))
    return uscita


def canto(lista: list[Battuta], s: dict[str, np.ndarray]) -> None:
    """Le parole cantate hanno la nota davanti: ♪ come nei sottotitoli per
    chi non sente, cosi' si sa che e' una canzone e non un discorso."""
    for b in lista:
        k0 = max(0, int(b.inizio - _SUONI_FINESTRA / 2))
        k1 = max(k0 + 1, int(np.ceil(b.fine - _SUONI_FINESTRA / 2)))
        cantato = np.max([s[c][k0:k1] for c in _CANTO], axis=0)
        if len(cantato) and float(np.mean(cantato >= 0.3)) > 0.5:
            b.parole[0] = ' ♪ ' + b.parole[0].lstrip()


def tagli_di_scena(video: str) -> list[float]:
    """Gli istanti in cui cambia l'inquadratura. Il video si guarda
    rimpicciolito: per vedere un taglio bastano 256 punti di larghezza, e
    si fa molto prima."""
    uscita = subprocess.run(
        ['ffmpeg', '-v', 'info', '-nostdin', '-i', video, '-an', '-sn',
         '-vf', "scale=256:-2,select='gt(scene,0.35)',showinfo", '-f', 'null', '-'],
        capture_output=True, text=True, errors='replace')
    return [float(t) for t in re.findall(r'pts_time:([\d.]+)', uscita.stderr)]


# ── Il formato ───────────────────────────────────────────────────────────────

def _tempo_ass(s: float) -> str:
    cs = int(round(s * 100))
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def _colore_ass(rgb: str) -> str:
    """#RRGGBB -> &HBBGGRR&: ASS scrive i colori al contrario."""
    r, g, b = rgb[1:3], rgb[3:5], rgb[5:7]
    return f'&H{b}{g}{r}&'


def scrivi_ass(lista: list[Riquadro], percorso: str, colori: dict[int, str],
               larghezza: int = 1920, altezza: int = 1080) -> None:
    """ASS: in basso al centro, lettere col contorno scuro, un colore per
    persona (bianco solo se la persona e' una sola). Niente riquadro nero
    dietro il testo, anche se la BBC lo chiede: copre il video, e a chi
    guarda non piace."""
    # Si disegna su una tela alta 1080 con le proporzioni del video, e libass
    # la riporta alla misura vera: cosi' le lettere hanno la stessa grandezza
    # relativa su un 240p del 2005 e su un 4K. Il corpo e' il piu' grande che
    # lascia stare RIGA_MAX caratteri in una riga, fino al 5% dell'altezza.
    tela_y = 1080
    tela_x = round(tela_y * larghezza / altezza) if altezza else 1920
    margine = round(tela_x * 0.06)
    corpo = round(min(tela_y * 0.05, (tela_x - 2 * margine) / (RIGA_MAX * 0.58)))
    bordo = max(2, corpo // 16)
    intestazione = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {tela_x}
PlayResY: {tela_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{corpo},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{bordo},{max(1, bordo // 2)},2,{margine},{margine},{round(tela_y * 0.05)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    eventi = []
    for r in lista:
        pezzi = []
        for persona, testo, lineetta in r.righe:
            testo = testo.replace('{', '(').replace('}', ')')
            if lineetta:
                testo = '– ' + testo
            colore = colori.get(persona, BIANCO)
            pezzi.append('{\\c' + _colore_ass(colore) + '}' + testo)
        eventi.append(f'Dialogue: 0,{_tempo_ass(r.inizio)},{_tempo_ass(r.fine)},'
                      f'Default,,0,0,0,,' + r'\N'.join(pezzi))
    with open(percorso, 'w', encoding='utf-8-sig') as f:
        f.write(intestazione + '\n'.join(eventi) + '\n')


def _tempo_srt(s: float) -> str:
    ms = int(round(s * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def scrivi_srt(lista: list[Riquadro], percorso: str, colori: dict[int, str]) -> None:
    """SRT: gli stessi riquadri dell'ASS, in un file di testo che si apre e si
    corregge con qualunque editor. I colori vanno nei tag ``<font>``, che VLC,
    mpv e i lettori delle TV capiscono; chi non li capisce li ignora, e restano
    le lineette."""
    blocchi = []
    for n, r in enumerate(lista, 1):
        righe = []
        for persona, testo, lineetta in r.righe:
            if lineetta:
                testo = '– ' + testo
            colore = colori.get(persona)
            righe.append(f'<font color="{colore}">{testo}</font>' if colore else testo)
        blocchi.append(f'{n}\n{_tempo_srt(r.inizio)} --> {_tempo_srt(r.fine)}\n'
                       + '\n'.join(righe))
    with open(percorso, 'w', encoding='utf-8-sig') as f:
        f.write('\n\n'.join(blocchi) + '\n')


def _dimensioni(video: str) -> tuple[int, int]:
    """Larghezza e altezza come si vedono, cioe' con i pixel non quadrati gia'
    raddrizzati: e' su quelle proporzioni che va misurato il testo."""
    uscita = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=width,height,sample_aspect_ratio', '-of', 'csv=p=0:s=x', video],
        capture_output=True, text=True)
    try:
        parti = uscita.stdout.strip().split('x')
        w, h = int(parti[0]), int(parti[1])
        if len(parti) > 2 and ':' in parti[2]:
            n, d = (int(v) for v in parti[2].split(':'))
            if n and d:
                w = round(w * n / d)
        return w, h
    except (ValueError, IndexError):
        return 1920, 1080


# ── Dentro il file ───────────────────────────────────────────────────────────

def ha_sottotitoli(video: str) -> bool:
    """True se il video ha gia' la traccia messa da un giro precedente."""
    uscita = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 's', '-show_entries',
         'stream_tags', '-of', 'json', video],
        capture_output=True, text=True)
    try:
        flussi = json.loads(uscita.stdout or '{}').get('streams', [])
    except ValueError:
        return False
    # Il .mkv conserva il titolo; il .mp4 lo butta e tiene solo il nome del
    # «gestore» della traccia, che per questo si scrive uguale.
    return any(TITOLO_TRACCIA in ((f.get('tags') or {}).get('title', ''),
                                  (f.get('tags') or {}).get('handler_name', ''))
               for f in flussi)


def nome_impresso(video: str) -> str:
    """Dove finisce la copia coi sottotitoli impressi: nella sottocartella
    Sottotitolati accanto al video, cosi' originali e copie non si mescolano."""
    cartella, nome = os.path.split(video)
    stem, ext = os.path.splitext(nome)
    return os.path.join(cartella, paths.SOTTOTITOLATI, f'{stem} (sottotitolato){ext}')


def nome_srt(video: str, lingua: str | None = None) -> str:
    """Il .srt accanto al video, con lo stesso nome: i lettori lo trovano da
    soli. Quello di una traduzione ha la lingua prima dell'estensione
    (``video.en.srt``), come vogliono VLC e mpv per proporla fra le tracce."""
    stem = os.path.splitext(video)[0]
    return f'{stem}.{lingua}.srt' if lingua else f'{stem}.srt'


# ── Dopo: correggere a mano ──────────────────────────────────────────────────
#
# Il .srt accanto al video e' la fonte: chi corregge un sottotitolo corregge
# quello, e da li' si rifanno la traccia nel file e, a richiesta, la copia
# impressa. Niente si ritrascrive: e' solo testo e tempi.

def _secondi_srt(t: str) -> float:
    h, m, resto = t.strip().split(':')
    s, ms = resto.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def leggi_srt(percorso: str) -> tuple[list[Riquadro], dict[int, str]]:
    """I riquadri di un .srt scritto da ``scrivi_srt``, coi colori: a ogni
    colore diverso una persona. Una riga senza colore e' bianca (una persona
    sola, o un'etichetta dei suoni)."""
    colori: dict[int, str] = {}
    lista: list[Riquadro] = []
    testo = open(percorso, encoding='utf-8-sig').read().replace('\r\n', '\n')
    for blocco in testo.strip().split('\n\n'):
        righe = blocco.split('\n')
        if len(righe) < 2 or '-->' not in righe[1]:
            continue
        a, b = righe[1].split('-->')
        uscita = []
        for r in righe[2:]:
            m = re.match(r'<font color="(#[0-9A-Fa-f]{6})">(.*)</font>$', r.strip())
            colore, parole = (m.group(1).upper(), m.group(2)) if m else (None, r.strip())
            persona = _chi_riga(colore, parole, colori)
            lineetta = parole.startswith('– ')
            uscita.append((persona, parole[2:] if lineetta else parole, lineetta))
        lista.append(Riquadro(_secondi_srt(a), _secondi_srt(b), uscita))
    return lista, colori


def srt_del_video(video: str) -> list[tuple[str | None, str]]:
    """I .srt accanto al video: ``[(lingua, percorso)]``, prima l'originale
    (lingua ``None``) e poi le traduzioni (``video.en.srt``)."""
    stem = os.path.splitext(video)[0]
    uscita = [(None, stem + '.srt')] if os.path.isfile(stem + '.srt') else []
    cartella, base = os.path.split(stem)
    for nome in sorted(os.listdir(cartella or '.')):
        m = re.fullmatch(re.escape(base) + r'\.([a-z]{2,3})\.srt', nome)
        if m:
            uscita.append((m.group(1), os.path.join(cartella, nome)))
    return uscita


def _lingua_traccia(video: str) -> str | None:
    """La lingua della prima traccia di sottotitoli nel file, se c'e'."""
    uscita = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 's:0', '-show_entries',
         'stream_tags=language', '-of', 'csv=p=0', video],
        capture_output=True, text=True)
    codice = uscita.stdout.strip()
    inverso = {'ita': 'it', 'eng': 'en', 'fra': 'fr', 'deu': 'de', 'spa': 'es',
               'por': 'pt', 'jpn': 'ja', 'rus': 'ru', 'zho': 'zh'}
    return inverso.get(codice) if codice else None


def _ritradotti(lista: list[Riquadro], colori: dict[int, str], da: str, a: str
                ) -> list[Riquadro]:
    """La traduzione dei riquadri corretti a mano. Ogni riga torna una
    battuta, le righe di fila dello stesso colore sono un turno, e da li' la
    traduzione segue la strada di sempre (vedi ``tradotte``)."""
    parlate, suoni_qui, turno, prima = [], [], 0, None
    for r in lista:
        for persona, testo, lineetta in r.righe:
            b = Battuta(r.inizio, r.fine, persona, [testo], scambio=lineetta)
            if persona == ETICHETTA:
                b.turno = -1 - len(suoni_qui)
                suoni_qui.append(b)
                continue
            if prima is not None and (persona != prima or lineetta):
                turno += 1
            b.turno, prima = turno, persona
            parlate.append(b)
    versione = tradotte(parlate, da, a) if parlate else []
    return riquadri(sorted(versione + etichette_tradotte(suoni_qui, a),
                           key=lambda b: b.inizio))


def _tempo_vtt(s: float) -> str:
    return _tempo_srt(s).replace(',', '.')


def scrivi_vtt(lista: list[Riquadro], percorso: str, colori: dict[int, str]) -> None:
    """WebVTT: il formato dei sottotitoli sul web. I colori non ci sono - in
    un VTT li decide la pagina che lo mostra - ma chi parla resta scritto:
    ogni riga colorata porta l'etichetta ``<v Voce N>``, che i lettori usano
    per distinguere le voci."""
    ordine = {persona: n for n, persona in enumerate(sorted(colori), 1)}
    blocchi = ['WEBVTT']
    for n, r in enumerate(lista, 1):
        righe = []
        for persona, testo, lineetta in r.righe:
            if lineetta:
                testo = '– ' + testo
            righe.append(f'<v Voce {ordine[persona]}>{testo}' if persona in ordine else testo)
        blocchi.append(f'{n}\n{_tempo_vtt(r.inizio)} --> {_tempo_vtt(r.fine)}\n'
                       + '\n'.join(righe))
    with open(percorso, 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(blocchi) + '\n')


def riquadri_da_pagina(riquadri_pagina: list[dict]) -> tuple[list[Riquadro], dict[int, str]]:
    """I riquadri come li manda l'editor - ``{inizio, fine, righe: [{testo,
    colore, lineetta}]}``, gia' in ordine o no - nella forma di ``leggi_srt``."""
    colori: dict[int, str] = {}
    lista = []
    for r in sorted(riquadri_pagina, key=lambda r: float(r['inizio'])):
        righe = []
        for riga in r.get('righe') or []:
            testo = str(riga.get('testo', '')).replace('\n', ' ').strip()
            if not testo:
                continue
            colore = (riga.get('colore') or '').upper() or None
            persona = _chi_riga(colore, testo, colori)
            righe.append((persona, testo, bool(riga.get('lineetta'))))
        if righe and float(r['fine']) > float(r['inizio']):
            lista.append(Riquadro(float(r['inizio']), float(r['fine']), righe))
    return lista, colori


def riscrivi(video: str, impressa: bool = True) -> dict:
    """Dopo una correzione a mano: dal .srt accanto al video rifa' tutto il
    resto. La traduzione (se c'era) si rifa' dal testo corretto, cosi' le
    due lingue dicono la stessa cosa; le tracce tornano nel file; la copia
    impressa si ridisegna, nella lingua originale.

    Senza ``impressa`` la copia coi sottotitoli nell'immagine non si rifa': e'
    la parte che costa minuti, e chi sta ancora correggendo puo' rimandarla."""
    from server.video import traduzione

    srt = srt_del_video(video)
    originale_srt = next((p for lingua, p in srt if lingua is None), None)
    if not originale_srt:
        raise RuntimeError("Accanto al video non c'e' il .srt")
    lista, colori = leggi_srt(originale_srt)
    lingua = _lingua_traccia(video) or 'it'
    for codice, percorso in srt:
        if codice and traduzione.disponibile(lingua, codice):
            scrivi_srt(_ritradotti(lista, colori, lingua, codice), percorso, colori)

    larghezza, altezza = _dimensioni(video)
    with tempfile.TemporaryDirectory(prefix='pica_sub_') as tmp:
        tracce = []
        for n, (codice, percorso) in enumerate(srt_del_video(video)):
            lista_n, colori_n = leggi_srt(percorso)
            ass = os.path.join(tmp, f'sottotitoli{n}.ass')
            scrivi_ass(lista_n, ass, colori_n, larghezza, altezza)
            tracce.append((ass, codice or lingua))
        _incorpora(video, tracce)
        impresso = imprimi(video, tracce[0][0]) if impressa else ''
    return {'tracce': len(tracce), 'impresso': impresso}


def scrivi_riquadri(percorso: str, riquadri_pagina: list[dict]) -> None:
    """Il .srt dai riquadri come li manda l'editor."""
    lista, colori = riquadri_da_pagina(riquadri_pagina)
    scrivi_srt(lista, percorso, colori)


def _incorpora(video: str, tracce: list[tuple[str, str | None]]) -> None:
    """Aggiunge al video le tracce di sottotitoli ``[(file, lingua)]``, senza
    ricodificare niente. La prima e' la lingua di chi parla ed e' la
    predefinita: si accende da sola aprendo il file; le traduzioni vengono
    dopo, da scegliere nel lettore. Le tracce messe da un giro precedente
    vengono sostituite, non duplicate."""
    base, ext = os.path.splitext(video)
    temporaneo = f'{base}.sub-tmp{ext}'
    codec = 'ass' if ext.lower() == '.mkv' else 'mov_text'
    comando = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', video]
    for file, _ in tracce:
        comando += ['-i', file]
    comando += ['-map', '0', '-map', '-0:s']
    for n in range(len(tracce)):
        comando += ['-map', f'{n + 1}:0']
    comando += ['-c', 'copy', '-c:s', codec]
    for n, (_, lingua) in enumerate(tracce):
        # Il .mp4 butta il titolo e tiene il nome del «gestore»: e' da li'
        # che ``ha_sottotitoli`` riconosce le tracce nostre.
        titolo = TITOLO_TRACCIA if n == 0 else f'{TITOLO_TRACCIA} ({lingua})'
        comando += [f'-disposition:s:{n}', 'default' if n == 0 else '0',
                    f'-metadata:s:s:{n}', f'title={titolo}',
                    f'-metadata:s:s:{n}', f'handler_name={titolo}']
        if lingua:
            comando += [f'-metadata:s:s:{n}', f'language={_iso639_2(lingua)}']
    subprocess.run(comando + [temporaneo], check=True, capture_output=True)
    os.replace(temporaneo, video)


def _iso639_2(lingua: str) -> str:
    """I contenitori vogliono il codice a tre lettere: 'it' -> 'ita'."""
    return {'it': 'ita', 'en': 'eng', 'fr': 'fra', 'de': 'deu', 'es': 'spa',
            'pt': 'por', 'ja': 'jpn', 'ru': 'rus', 'zh': 'zho'}.get(lingua[:2], 'und')


# Sotto quest'altezza il video si ingrandisce prima di scriverci sopra. Le
# lettere disegnate su un 360p sono fatte di 360 righe e restano sfocate
# quanto il video; a 1080 sono nitide, e il video sotto non peggiora.
ALTEZZA_IMPRESSI = 1080


def imprimi(video: str, ass: str) -> str:
    """Una copia del video coi sottotitoli disegnati nell'immagine.

    FFmpeg si lancia dalla cartella del file perche' il filtro ``subtitles``
    vuole il percorso dentro una stringa di filtro, dove i ':' e i '\\' di
    un percorso Windows andrebbero protetti due volte. Col nome nudo non c'e'
    niente da proteggere.
    """
    cartella, nome = os.path.split(video)
    uscita = os.path.join(paths.SOTTOTITOLATI, os.path.basename(nome_impresso(video)))
    os.makedirs(os.path.join(cartella, paths.SOTTOTITOLATI), exist_ok=True)
    appoggio = 'pica-sottotitoli.ass'
    shutil.copyfile(ass, os.path.join(cartella, appoggio))
    _, altezza = _dimensioni(video)
    filtri = f'subtitles={appoggio}'
    if altezza < ALTEZZA_IMPRESSI:
        filtri = (f'scale=-2:{ALTEZZA_IMPRESSI}:flags=lanczos,setsar=1,' + filtri)
    try:
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', nome,
             '-vf', filtri, '-map', '0:v:0', '-map', '0:a?',
             '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast',
             '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-sn',
             '-movflags', '+faststart', uscita],
            cwd=cartella or None, check=True, capture_output=True)
    finally:
        try:
            os.remove(os.path.join(cartella, appoggio))
        except OSError:
            pass
    return os.path.join(cartella, uscita)


# ── Il mestiere intero ───────────────────────────────────────────────────────

def sottotitola(video: str, lingua: str | None = None,
                n_parlanti: int | None = None, incorpora: bool = True,
                impressi: bool = False, modello: str = MODELLO_WHISPER,
                traduci: str | None = None, on_fase=None) -> dict:
    """Trascrive il video, riconosce chi parla e ne scrive i sottotitoli.

    Con ``traduci`` (per ora ``'en'``) fa anche i sottotitoli tradotti: un
    secondo .srt (``video.en.srt``) e una seconda traccia nel file. La copia
    impressa resta nella lingua di chi parla: e' quella che si corregge dalla
    sezione Sottotitoli, e la traduzione si sceglie nel lettore.

    Restituisce ``{'impresso', 'parlanti', 'riquadri', 'tradotto'}``. Ogni
    persona ha il suo colore, sempre lo stesso per tutto il video e in tutte
    le lingue; con una voce sola il testo resta bianco.
    """
    from server.video import traduzione

    def fase(nome: str) -> None:
        if on_fase:
            on_fase(nome)

    fase('audio')
    campioni = estrai_audio(video)
    if not len(campioni):
        raise RuntimeError('Il video non ha una traccia audio')

    fase('parlanti')
    voci = chi_parla(campioni, n_parlanti)
    fase('trascrizione')
    parole, lingua = cosa_si_dice(campioni, lingua, modello)
    parole = _alla_voce(parole, voci)
    turni = _turni(parole, _chi_dice(parole, voci, campioni), voci, campioni)
    originale = battute(parole, turni)

    versione: list[Battuta] = []
    if traduci and lingua[:2] != traduci[:2]:
        if traduzione.disponibile(lingua, traduci):
            fase('traduzione')
            versione = tradotte(originale, lingua, traduci)
        else:
            log.warning('Traduzione da %s a %s non disponibile', lingua, traduci)

    fase('suoni')
    s = suoni(campioni)
    canto(originale, s)
    canto(versione, s)
    suoni_qui = etichette(originale, s, voci, len(campioni) / FREQUENZA)
    tagli = tagli_di_scena(video)
    lista = riquadri(sorted(originale + suoni_qui, key=lambda b: b.inizio), tagli)
    lista_tr = (riquadri(sorted(versione + etichette_tradotte(suoni_qui, traduci),
                                key=lambda b: b.inizio), tagli)
                if versione else [])

    # I colori si danno nell'ordine in cui le persone entrano in scena, e solo
    # se ce n'e' piu' d'una: un monologo resta bianco.
    ordine: list[int] = []
    for p, _ in turni:
        if p not in ordine:
            ordine.append(p)
    colori = ({p: COLORI[n % len(COLORI)] for n, p in enumerate(ordine)}
              if len(ordine) > 1 else {})
    log.info('Sottotitoli: %d riquadri, %d persone, %d turni - %s',
             len(lista), len(ordine), turni[-1][1] + 1 if turni else 0,
             os.path.basename(video))

    fase('scrittura')
    larghezza, altezza = _dimensioni(video)
    with tempfile.TemporaryDirectory(prefix='pica_sub_') as tmp:
        ass = os.path.join(tmp, 'sottotitoli.ass')
        scrivi_ass(lista, ass, colori, larghezza, altezza)
        scrivi_srt(lista, nome_srt(video), colori)
        tracce = [(ass, lingua)]
        if lista_tr:
            ass_tr = os.path.join(tmp, f'sottotitoli.{traduci}.ass')
            scrivi_ass(lista_tr, ass_tr, colori, larghezza, altezza)
            scrivi_srt(lista_tr, nome_srt(video, traduci), colori)
            tracce.append((ass_tr, traduci))
        if incorpora:
            _incorpora(video, tracce)
        impresso = ''
        if impressi:
            fase('imprimo')
            impresso = imprimi(video, tracce[0][0])

    return {'impresso': impresso, 'parlanti': len(ordine), 'riquadri': len(lista),
            'tradotto': traduci if lista_tr else ''}
