"""Come si racconta un guasto a chi non l'ha causato.

Le frasi che ``server/utils/contract.py`` sceglie quando un lavoro cade. Sono
qui e non li' per una ragione pratica: i cataloghi vengono caricati tutti
insieme da ``server/config/strings/__init__.py``, e uno che stesse altrove
dovrebbe registrarsi per conto suo - cioe' sperare che qualcuno lo importi
prima che serva. E' successo: ``err.title`` compariva a schermo come
``err.title``, scritto cosi', dentro il titolo della finestra d'errore.

Come sono scritte
    Ognuna dice tre cose, in quest'ordine: cosa e' successo, perche', e cosa
    si puo' fare. La terza e' quella che conta - «manca FFmpeg» senza
    «installalo cosi'» e' solo un modo piu' gentile di non rispondere.
"""
from __future__ import annotations

TESTI: dict[str, str] = {
    'err.title':   'Non ce l\'ho fatta',
    'err.file':    'Su questo file',
    'err.detail':  'Cosa ha risposto',
    'err.unknown': 'È andato storto qualcosa, e il programma non sa dire cosa. '
                   'Il testo qui sotto è quello che ha risposto.',

    'err.ffmpeg':  'Manca FFmpeg. È lo strumento che converte, taglia e ricodifica: '
                   'senza, quasi niente di quello che fa Pica può funzionare. '
                   'Di solito si scarica da solo al primo avvio: controlla la '
                   'connessione e riapri il programma. In alternativa si installa '
                   'con «winget install Gyan.FFmpeg».',
    'err.spazio':  'Il disco è pieno. Libera spazio nella cartella di destinazione '
                   'e riprova: quello che era già stato scritto resta dov\'è.',
    'err.permessi': 'Windows non lascia scrivere in quella cartella. Succede dentro '
                    '«Programmi» e sulle cartelle di sistema: scegline un\'altra, '
                    'per esempio sul Desktop o in Documenti.',
    'err.manca_file': 'Quel file non c\'è più dove era. Può darsi che sia stato '
                      'spostato o rinominato dopo che l\'avevi scelto.',
    'err.illeggibile': 'Il file c\'è ma non si lascia leggere come filmato: o è '
                       'troncato, o non è quello che sembra dall\'estensione.',

    'err.rete':    'La rete non risponde. Controlla la connessione e riprova: '
                   'quello che era già stato scaricato non va perso.',
    'err.vietato': 'YouTube ha rifiutato la richiesta. Di solito è un video privato, '
                   'a pagamento, riservato agli adulti o non disponibile in questo '
                   'paese. Se invece è pubblico, spesso basta aggiornare yt-dlp: '
                   '«pip install -U yt-dlp».',
    'err.sparito': 'Il video non esiste più, o è stato reso privato.',

    'err.no_masterizzatore': 'Non ho trovato nessun masterizzatore. Se ce n\'è uno '
                             'esterno, collegalo e riapri il programma.',
    'err.no_disco': 'Non c\'è nessun disco nel masterizzatore, o è stato inserito '
                    'mentre il programma stava già guardando. Inseriscilo e '
                    'rifai la scansione.',
    'err.disco_pieno': 'Il disco non è vuoto e non si può riscrivere. Serve un CD-R '
                       'vergine, o un CD-RW da cancellare prima.',
    'err.imapi':   'La masterizzazione si è fermata a metà. Il disco, se era un '
                   'CD-R, è da buttare. Le cause più comuni sono una velocità '
                   'troppo alta e un supporto di bassa qualità: riprova a 8x o 16x '
                   'con un disco diverso.',
    'err.no_pywin32': 'Manca pywin32, la libreria con cui Windows lascia comandare '
                      'il masterizzatore. Si installa con «pip install pywin32».',

    'err.interrotto': 'Il lavoro è stato interrotto prima di finire.',
}
