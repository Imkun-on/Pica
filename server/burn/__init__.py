"""Cosa serve per incidere un CD audio, e perche' e' piu' difficile di quanto sembri.

Un CD audio non e' una cartella di file: e' un flusso PCM a 44.1 kHz e 16 bit,
con una capienza misurata in minuti e non in megabyte, e con un vincolo che
nessun altro mestiere di Pica ha - un disco scritto male e' consumato
comunque. Per questo qui dentro c'e' tanta aritmetica e tanta diagnosi, e per
questo la conferma prima di incidere mostra tutto quello che mostra.

Cosa c'e' qui sotto
    ``redbook``  i numeri dello standard: settori, minuti, stacchi, velocita'.
    ``order``    in che ordine vanno le tracce, e quanto durano.
    ``encode``   da file compresso a PCM, col livellamento e la rifilatura.
    ``drives``   quali unita' ci sono e cosa hanno dentro.
    ``writer``   l'incisione, e la traduzione degli errori di IMAPI2.

La procedura che li mette in fila - scegliere, confermare, decodificare,
incidere - non sta qui ma in ``server/services/burn.py``, perche' e' l'unica
cosa di BurnDex che cambia a seconda di chi sta guardando.

L'elenco qui sotto e' l'API pubblica dello strato: e' quello su cui la
finestra puo' contare. Prima arrivava a prendersi ``bd._ordina_tracce`` e
``bd._settori_totali`` - nomi che l'underscore dichiarava privati e che erano
invece il contratto vero.
"""

from server.burn.redbook import (        # noqa: F401
    SAFE_MINUTES,
    format_duration,
    sectors_to_minutes,
    settori_totali,
    velocita_x,
)
from server.burn.order import (          # noqa: F401
    durata_traccia,
    e_un_album,
    ordina_tracce,
)
from server.burn.drives import (         # noqa: F401
    _HAS_PYWIN32,
    elenca_unita,
    nome_unita,
)
