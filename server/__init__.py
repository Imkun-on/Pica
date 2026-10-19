"""Il motore di Pica: tutto quello che sa fare, e niente di come si mostra.

Le cartelle, dal basso verso l'alto
    config/       le manopole, i testi, i percorsi. Non fa niente: risponde.
    utils/        gli attrezzi buoni per tutti: console, rete, FFmpeg, testo,
                  e la traduzione di un guasto in una frase italiana.
    sources/      da dove arriva la roba: YouTube, i testi delle canzoni, le
                  copertine.
    audio/        cosa si fa a un file audio: scaricarlo, taggarlo, misurarne
                  il volume, dividerlo in tracce.
    burn/         cosa si fa a un CD: l'aritmetica del Red Book, l'ordine
                  delle tracce, le unita', la scrittura via IMAPI2.
    video/        cosa si fa a un filmato: leggerlo, rimasterizzarlo,
                  tagliarlo, unirlo, ricavarne una GIF.
    state/        cio' che sopravvive al singolo gesto: il database dei
                  download, l'avanzamento, il posto di lavoro.
    services/     il direttore d'orchestra. Da solo non sa fare niente:
                  chiama gli altri nell'ordine giusto e gestisce gli imprevisti.
    controllers/  il filo con la pagina. Riceve una richiesta, chiama chi la
                  sa eseguire, traduce la risposta. Nessun lavoro vero.

La direzione delle dipendenze
    Va sempre verso il basso di quell'elenco. ``controllers`` puo' chiamare
    ``services``, ``services`` puo' chiamare tutti gli altri, e ``config`` non
    chiama nessuno. Al contrario mai: il giorno in cui ``burn`` importasse
    ``services`` si chiuderebbe un cerchio, e da quel momento non si potrebbe
    piu' leggere un modulo senza averne aperti altri due.

La regola che tiene insieme tutto
    ``server/`` non importa MAI niente da ``cli/``, e non sa che la pagina
    esiste. Il lavoro non sa chi lo sta guardando: per questo lo stesso motore
    serve la finestra e il terminale, e per questo aggiungere una terza
    interfaccia non vorrebbe dire riscrivere niente di quello che c'e' qui.
"""
