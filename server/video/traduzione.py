"""La traduzione dei sottotitoli, su questo computer.

Il modello e' Opus-MT dell'Universita' di Helsinki, uno per ogni coppia di
lingue, scaricato dal loro server nella forma originale (Marian) e convertito
la prima volta per CTranslate2 - lo stesso motore di Whisper, gia' installato.
Niente account e niente PyTorch: la conversione chiede solo numpy.

Perche' Opus-MT e non NLLB di Meta, che conosce duecento lingue: NLLB da 1,3
miliardi di parametri, su un portatile con un Ryzen 5 3500U, impiegava tre
secondi a frase, dieci minuti per un live di dieci minuti. Opus-MT e' circa
diciassette volte piu' piccolo. E la sua licenza (CC-BY) permette anche l'uso
commerciale, quella di NLLB no.

Come si traduce un sottotitolo
    Mai sottotitolo per sottotitolo: tradotta da sola, mezza frase diventa un
    parola-per-parola senza senso. Si rimettono insieme le frasi intere di
    ogni persona, si traducono, e la traduzione si ridivide in righe con le
    stesse regole dell'originale (vedi ``sottotitoli._tagli_frase``). I tempi
    vengono dall'originale: la parola tradotta che sta a meta' della frase va
    a schermo quando chi parla e' a meta' della frase.
"""
from __future__ import annotations

import io
import re
import os
import shutil
import tempfile
import zipfile

from server.utils.console import setup_logger

log = setup_logger('audiodex', 'audiodex.log')

_OPUS = 'https://object.pouta.csc.fi/OPUS-MT-models'
# Le coppie disponibili: (da, a) -> il pacchetto sul server di Helsinki.
MODELLI = {
    ('it', 'en'): f'{_OPUS}/it-en/opus-2019-12-18.zip',
}

# I nomi delle lingue, per il log e per le etichette dei suoni.
NOMI = {'en': 'inglese', 'it': 'italiano'}

# Le etichette dei suoni non passano dal traduttore: sono poche, e tradotte
# da sole diventavano altro («[voci incomprensibili]» -> «[incomprehensible
# voices]» va, ma «[canto]» -> «[corner]» no).
ETICHETTE = {
    'en': {
        'musica': 'music', 'applausi': 'applause', 'risate': 'laughter',
        'il pubblico esulta': 'crowd cheering',
        'il pubblico urla': 'crowd shouting',
        'voci incomprensibili': 'indistinct voices',
        'brusio del pubblico': 'crowd murmuring', 'canto': 'singing',
    },
}


def disponibile(da: str, a: str) -> bool:
    return (da[:2], a[:2]) in MODELLI


def _cartella(da: str, a: str, radice: str) -> str:
    """Il modello convertito, pronto per CTranslate2: lo prepara la prima
    volta. Si converte in una cartella di passaggio e si rinomina solo a fine
    corsa, cosi' un download interrotto non lascia un modello a meta'."""
    import ctranslate2
    import requests

    cartella = os.path.join(radice, f'opus-mt-{da}-{a}')
    if os.path.isfile(os.path.join(cartella, 'model.bin')):
        return cartella
    url = MODELLI[(da, a)]
    log.info('Scarico il modello di traduzione: %s', url)
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    with tempfile.TemporaryDirectory(prefix='pica_opus_') as tmp:
        originale = os.path.join(tmp, 'marian')
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(originale)
        parziale = cartella + '.part'
        shutil.rmtree(parziale, ignore_errors=True)
        ctranslate2.converters.OpusMTConverter(originale).convert(
            parziale, quantization='int8', force=True)
        for spm in ('source.spm', 'target.spm'):
            shutil.copyfile(os.path.join(originale, spm), os.path.join(parziale, spm))
        os.replace(parziale, cartella)
    return cartella


def traduci(frasi: list[str], da: str, a: str, radice: str) -> list[str]:
    """Le frasi tradotte, nello stesso ordine."""
    import ctranslate2
    import sentencepiece

    if not frasi:
        return []
    cartella = _cartella(da[:2], a[:2], radice)
    sorgente = sentencepiece.SentencePieceProcessor(
        model_file=os.path.join(cartella, 'source.spm'))
    arrivo = sentencepiece.SentencePieceProcessor(
        model_file=os.path.join(cartella, 'target.spm'))
    traduttore = ctranslate2.Translator(
        cartella, device='cpu', compute_type='int8',
        intra_threads=os.cpu_count() or 4)
    # Opus-MT e' addestrato su frasi singole: a «È viva! Fermi tutti! È una
    # cosa guardabile!» rispondeva «She's alive!» e basta. Ogni frase va
    # tradotta da sola, e le traduzioni si rimettono insieme.
    pezzi = [re.findall(r'[^.!?…]+[.!?…]*', f) or [f] for f in frasi]
    tutte = [p.strip() for ps in pezzi for p in ps if p.strip()]
    uscita = traduttore.translate_batch(
        [sorgente.encode(p, out_type=str) + ['</s>'] for p in tutte],
        beam_size=2, max_batch_size=16)
    tradotte = iter(arrivo.decode(u.hypotheses[0]).strip() for u in uscita)
    return [' '.join(next(tradotte) for p in ps if p.strip()) for ps in pezzi]
