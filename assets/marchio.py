# -*- coding: utf-8 -*-
"""Il marchio di Pica, montato una volta sola e messo nei posti in cui serve.

    python assets/marchio.py

Da dove viene
    Da ``assets/icona-originale.png``: una gazza ladra in volo con un CD nel
    becco, a incisione, inchiostro nero su fondo verde piatto. E' un quadrato
    pieno, senza angoli e senza bordo: quelli li mette questo file, cosi' sono
    identici su tutti i sistemi e per cambiarli non si rifa' il disegno.

Cosa gli si fa
    Lo si ritaglia in un quadrato dagli angoli tondi e gli si passa attorno un
    filo scuro, che lo stacca tanto da un desktop chiaro quanto da uno scuro.

Dove finisce
    - ``assets/Pica.ico``: l'eseguibile, la finestra e l'installatore su
      Windows.
    - ``assets/Pica.icns``: l'applicazione su macOS. Li' le icone non
      toccano i bordi della tela: il disegno occupa l'ottanta per cento e il
      resto e' margine vuoto, come vuole il sistema.
    - ``assets/Pica.png``: Linux, e l'icona della pagina.
    - ``client/marchio.png``: la barra laterale e il velo di avvio. Qui non
      c'e' il quadrato: solo la gazza, scontornata, sul nero della finestra.

Come si toglie il verde
    L'inchiostro e la carta sono grigi, cioe' hanno rosso, verde e blu uguali;
    il fondo no. Quanto fondo c'e' in un punto lo dice quindi la differenza fra
    verde e rosso, e una volta saputo lo si sottrae: sui bordi dei tratti, dove
    i due si mescolano, non resta nessun alone verde.

    Ali e coda nell'originale escono dal riquadro, e senza il quadrato attorno
    finirebbero con un taglio netto: verso i bordi la gazza sfuma.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(QUI)
ORIGINALE = os.path.join(QUI, 'icona-originale.png')
ICO = os.path.join(QUI, 'Pica.ico')
ICNS = os.path.join(QUI, 'Pica.icns')
PNG = os.path.join(QUI, 'Pica.png')
PAGINA = os.path.join(RADICE, 'client', 'marchio.png')

# Tutto e' pensato su 1024 punti di lato, la misura piu' grande che un sistema
# chieda (macOS); le altre si ricavano rimpicciolendo.
LATO = 1024
RAGGIO = 228                          # degli angoli
BORDO = 10                            # lo spessore del filo scuro
INCHIOSTRO = (21, 21, 19, 255)

# Pillow non ammorbidisce i bordi delle forme che disegna: le si disegna
# quattro volte piu' grandi e le si rimpicciolisce.
LISCIO = 4

# Le misure che Windows si aspetta dentro un .ico. La piu' piccola e' quella
# della barra delle applicazioni, la piu' grande quella delle anteprime grandi
# di Esplora risorse.
MISURE_ICO = [16, 24, 32, 48, 64, 128, 256]
LATO_PNG = 512
LATO_PAGINA = 400                     # nella pagina non supera i 170 punti
PIENO_MAC = 824                       # il lato del disegno dentro i 1024 di macOS

# Lo scontorno. Sotto ALFA_VIA un punto e' fondo e sparisce, sopra ALFA_PIENO
# e' disegno pieno: la grana del verde sta tutta sotto la prima soglia.
ANGOLO = 40                           # il lato dei riquadri da cui si legge il fondo
ALFA_VIA, ALFA_PIENO = .10, .88
SFUMA = 44                            # la fascia lungo i bordi in cui la gazza svanisce


def icona() -> Image.Image:
    """L'originale dentro il quadrato dagli angoli tondi, col suo filo."""
    img = Image.open(ORIGINALE).convert('RGBA').resize((LATO, LATO), Image.LANCZOS)
    g = LATO * LISCIO

    sagoma = Image.new('L', (g, g), 0)
    ImageDraw.Draw(sagoma).rounded_rectangle((0, 0, g - 1, g - 1), RAGGIO * LISCIO, fill=255)

    filo = Image.new('RGBA', (g, g), (0, 0, 0, 0))
    meta = BORDO * LISCIO // 2
    ImageDraw.Draw(filo).rounded_rectangle(
        (meta, meta, g - 1 - meta, g - 1 - meta), RAGGIO * LISCIO - meta,
        outline=INCHIOSTRO, width=BORDO * LISCIO)

    img = Image.alpha_composite(img, filo.resize((LATO, LATO), Image.LANCZOS))
    img.putalpha(sagoma.resize((LATO, LATO), Image.LANCZOS))
    return img


def gazza() -> Image.Image:
    """La gazza senza il fondo, stretta sul disegno."""
    a = np.asarray(Image.open(ORIGINALE).convert('RGB')).astype(np.float32)

    # Il verde del fondo: la mediana di tre angoli. Il quarto, in basso a
    # destra, e' occupato dalla coda.
    k = ANGOLO
    fondo = np.median(np.concatenate([a[:k, :k].reshape(-1, 3),
                                      a[:k, -k:].reshape(-1, 3),
                                      a[-k:, :k].reshape(-1, 3)]), axis=0)

    verde = np.clip((a[..., 1] - a[..., 0]) / (fondo[1] - fondo[0]), 0, 1)
    alfa = np.clip((1 - verde - ALFA_VIA) / (ALFA_PIENO - ALFA_VIA), 0, 1)
    colore = (a - verde[..., None] * fondo) / np.maximum(1 - verde[..., None], .05)

    alto, largo = alfa.shape
    y, x = np.mgrid[0:alto, 0:largo]
    dal_bordo = np.minimum(np.minimum(x, largo - 1 - x), np.minimum(y, alto - 1 - y))
    alfa *= np.clip(dal_bordo / SFUMA, 0, 1)

    img = Image.fromarray(
        np.dstack([np.clip(colore, 0, 255), alfa * 255]).astype(np.uint8), 'RGBA')
    return img.crop(img.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox())


def con_margine(i: Image.Image) -> Image.Image:
    """La stessa icona, rimpicciolita al centro di una tela vuota: per macOS."""
    tela = Image.new('RGBA', (LATO, LATO), (0, 0, 0, 0))
    scarto = (LATO - PIENO_MAC) // 2
    tela.paste(i.resize((PIENO_MAC, PIENO_MAC), Image.LANCZOS), (scarto, scarto))
    return tela


def scrivi() -> None:
    i = icona()
    g = gazza()
    g.thumbnail((LATO_PAGINA, LATO_PAGINA), Image.LANCZOS)
    g.save(PAGINA)
    i.resize((LATO_PNG, LATO_PNG), Image.LANCZOS).save(PNG)
    # Pillow ricampiona da solo le misure richieste, partendo dalla piu' grande.
    i.save(ICO, sizes=[(m, m) for m in MISURE_ICO])
    con_margine(i).save(ICNS)
    print('  {}  {}x{}'.format(PAGINA, *g.size))
    print('  {}  {}x{}'.format(PNG, LATO_PNG, LATO_PNG))
    print('  {}  {}'.format(ICO, ', '.join(str(m) for m in MISURE_ICO)))
    print('  {}'.format(ICNS))


if __name__ == '__main__':
    scrivi()
