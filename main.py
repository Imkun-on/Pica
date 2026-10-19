"""Pica — quattro strumenti, una finestra sola.

Cosa fa questo file
    Apre la finestra, e nient'altro. Il lavoro sta tutto in ``server/``, che
    non sa nemmeno che esista un'interfaccia; cosa la pagina puo' chiedere sta
    in ``server/controllers/api.py``; il filo fra i due mondi in
    ``server/controllers/bridge.py``.

L'interfaccia e' una pagina web dentro una finestra di Windows
    Non c'e' nessun motore grafico da scaricare: WebView2 e' gia' nel sistema.
    Lo sfondo animato non e' un video da settantaquattro megabyte ma venti
    righe di CSS, e le cose che un'interfaccia deve fare - bagliori, sfocature,
    transizioni - sono esattamente cio' per cui il CSS e' nato.

Come parlano fra loro i due mondi
    In una sola direzione ciascuno, ed e' questo che tiene il tutto semplice:

      JavaScript -> Python   ``pywebview.api.nome(...)`` chiama direttamente un
                             metodo di ``Api``. Nessun protocollo, nessun
                             server, nessuna porta aperta.

      Python -> JavaScript   ``bridge.verso_pagina(...)`` esegue una funzione
                             della pagina. Serve per cio' che arriva quando
                             vuole lui: avanzamento, fine lavoro, errori.

Il lavoro lungo non blocca la finestra
    Ogni operazione che dura piu' di un istante gira in un thread suo e
    riferisce alla pagina mentre procede. La finestra resta viva: si vede a che
    punto e', e si puo' chiudere.

L'attesa dell'avvio sta dentro la pagina
    C'era anche una schermata disegnata da PyInstaller, un'immagine piccola al
    centro dello schermo, e se n'e' andata. Erano due schermate di caricamento
    per un caricamento solo: la prima compariva subito ma restava di
    quattrocento pixel, la seconda copriva la finestra ma arrivava dopo. Adesso
    ce n'e' una, dentro la pagina, e la finestra nasce massimizzata perche'
    quella copra tutto lo schermo.

    Il prezzo e' dichiarato: fra il doppio clic e la comparsa della finestra
    passano i secondi che servono a importare Rich e il ponte con WebView2, e
    in quei secondi sullo schermo non c'e' niente. Non si puo' fare di meglio
    senza rimettere la seconda schermata, perche' la finestra non puo' esistere
    prima di aver importato la libreria che la crea.
"""
from __future__ import annotations

import os

# Prima di tutto il resto: da qui in poi nessun ffmpeg, ffprobe o Python di
# servizio apre la sua finestra di terminale (vedi server/utils/nascosto.py).
from server.utils.nascosto import nascondi_console
nascondi_console()

from server.config.paths import risorsa as _risorsa
from server.controllers import bridge
from server.controllers.api import Api

import webview


def main() -> None:
    finestra = webview.create_window(
        'Pica',
        _risorsa('client', 'index.html'),
        js_api=Api(),
        # Massimizzata, non a schermo intero, e la differenza si vede subito.
        #
        # «Schermo intero» in pywebview vuol dire senza cornice: la finestra
        # copre tutto, compresa la barra delle applicazioni, e con la cornice
        # spariscono anche i tre pulsanti in alto a destra. Per un lettore
        # video va bene; per un programma con cui si lavora no, perche' per
        # chiuderlo o metterlo da parte bisogna sapere una scorciatoia da
        # tastiera.
        #
        # «Massimizzata» occupa lo stesso spazio ma resta una finestra normale:
        # barra del titolo, riduci a icona, ingrandisci, chiudi, e la barra
        # delle applicazioni sotto. Le misure qui sotto non sono un doppione,
        # sono quelle a cui torna quando la si rimpicciolisce.
        maximized=True,
        width=1180,
        height=780,
        min_size=(900, 620),
        # Il fondo della finestra prima che la pagina dipinga: il nero
        # verdastro del tema (--f1 in client/styles/style.css). Con qualunque
        # altro colore ogni avvio comincerebbe con un lampo di un tema che non
        # esiste piu'.
        background_color='#060b07',
        text_select=False,
        # Visibile subito. Prima restava nascosta perche' l'attesa la copriva
        # l'immagine disegnata da PyInstaller; adesso l'attesa e' dentro la
        # pagina, quindi la pagina deve vedersi. Il lampo bianco con cui
        # WebView2 dipinge se stesso prima di inizializzarsi non si vede lo
        # stesso, perche' il fondo della finestra e' gia' il nero del tema.
    )

    # Da adesso la finestra e' raggiungibile da chiunque debba parlare alla
    # pagina, senza che nessuno se la debba passare di mano in mano.
    bridge.imposta(finestra)

    # L'icona della finestra. Su Windows pywebview, se non gliela si passa, la
    # estrae dall'eseguibile: lanciando i sorgenti finirebbe quella di
    # python.exe, quindi gliela si indica sempre.
    icona = _risorsa('assets', 'Pica.ico')
    webview.start(icon=icona if os.path.isfile(icona) else None)


if __name__ == '__main__':
    main()
