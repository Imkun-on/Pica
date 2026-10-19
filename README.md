<p align="center">
  <img src="assets/Pica.png" alt="Pica: una gazza ladra in volo con un CD nel becco" width="170">
</p>

<h1 align="center">Pica</h1>

<p align="center">
  <b>Tutto l'audio e il video, in un solo spazio.</b><br>
  Scarica, converti, migliora, sottotitola, doppia e monta: uno studio multimediale<br>
  che gira sul tuo computer, senza account e senza telemetria.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/stato-in_sviluppo-f59e0b" alt="Stato: in sviluppo">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows11&logoColor=white" alt="Windows 10 e 11">
  <img src="https://img.shields.io/badge/FFmpeg-007808?logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/yt--dlp-FF0000?logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/licenza-PolyForm_NC_1.0-1fa55a" alt="Licenza PolyForm Noncommercial 1.0.0">
</p>

<p align="center">
  <a href="#uno-sguardo-allapp">Uno sguardo</a> ·
  <a href="#a-cosa-serve">A cosa serve</a> ·
  <a href="#perché-pica">Perché</a> ·
  <a href="#avvio-rapido">Avvio rapido</a> ·
  <a href="#download">Download</a> ·
  <a href="#licenza-e-crediti">Licenza</a>
</p>

<br>

> [!NOTE]
> Pica oggi gira su **Windows**. I pacchetti per macOS e Linux sono in lavorazione:
> l'interfaccia è già la stessa su tutti e tre i sistemi, manca la parte che scarica
> FFmpeg e Tor per ciascuno. La masterizzazione dei CD resterà solo su Windows.

## Uno sguardo all'app

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="assets/schermate/audio.png" alt="La sezione Audio: libreria, opzioni di uscita e lettore" width="100%">
      <sub><b>Audio.</b> Incolli un link, scegli formato e qualità, e i brani finiscono in libreria con tag, copertina e testo. Si ascoltano dal lettore in basso.</sub>
    </td>
    <td width="50%" valign="top">
      <img src="assets/schermate/migliora.png" alt="La sezione Migliora qualità: confronto prima e dopo con la linea da trascinare" width="100%">
      <sub><b>Migliora qualità.</b> Toglie i difetti della compressione e ingrandisce. A lavoro finito trascini la linea e confronti prima e dopo sullo stesso fotogramma.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="assets/schermate/montaggio.png" alt="La sezione Montaggio: anteprima, timeline con le maniglie di taglio e opzioni di uscita" width="100%">
      <sub><b>Montaggio.</b> Due maniglie sulla timeline decidono lo spezzone. Esce come video, GIF o WebP; più file si uniscono in uno.</sub>
    </td>
    <td width="50%" valign="top">
      <img src="assets/schermate/sottotitoli.png" alt="La sezione Sottotitoli: video con i sottotitoli sopra e l'elenco dei segmenti" width="100%">
      <sub><b>Sottotitoli.</b> Il parlato trascritto, un colore per ogni voce. Correggi una riga e la vedi cambiare sul video mentre scrivi.</sub>
    </td>
  </tr>
</table>

<sub>Nelle schermate i brani e il video sono contenuti di esempio.</sub>

## A cosa serve

Pica mette in una finestra sola i lavori che di solito chiedono sei programmi
diversi e una riga di comando. Ogni sezione fa un mestiere, dall'inizio alla fine.

| Sezione | Cosa fa |
|---|---|
| 🎧 **Audio** | Da un link di YouTube (brano, playlist o album) ricava l'audio in M4A, MP3, FLAC, WAV o Opus. Scrive tag e copertina, cerca il testo sincronizzato, e a richiesta converte in mono o livella il volume. Un album caricato come video unico si divide in tracce. |
| 💿 **Masterizzazione** | Trasforma una cartella di brani in un CD audio, di quelli che legge qualunque autoradio. Sceglie l'ordine, livella il volume e dice se ci sta. |
| 🎬 **Video** | Da un link ricava il video in MP4, singolo o di un'intera playlist. A richiesta con i sottotitoli, anche tradotti in inglese. |
| ✨ **Migliora qualità** | Analizza un video, dice cosa c'è da sistemare e lo ripulisce: quadretti, bande, rumore. Ingrandisce fino al 4K, anche con l'AI, e stabilizza l'immagine. |
| 💬 **Sottotitoli** | Trascrive il parlato e riconosce chi parla. Si correggono testi, tempi e voci guardando il video, e si esportano in SRT o WebVTT. |
| 🗣 **Doppiaggio AI** | Riscrivi una battuta e la fa dire a chi parla, con la sua voce, in una copia nuova del video. |
| ✂ **Montaggio** | Taglia uno spezzone, unisce più file, ricava GIF e WebP animati. Scegli contenitore, codec e risoluzione, oppure copia senza ricodificare. |

## Perché Pica

- **Resta tutto sul tuo computer.** Nessun account, nessun caricamento su server di altri, nessuna telemetria. I modelli per trascrivere e tradurre girano in locale.
- **Non mostra il tuo indirizzo a YouTube.** Ogni richiesta passa da Tor. Se Tor non parte, Pica non scarica: meglio un download fallito che uno a viso scoperto.
- **Dice le cose come stanno.** La stessa riga che ti offre il 4K ti dice, quando è il caso, che da quel video non aggiunge un solo dettaglio vero. Scegliere 320 kbps su una sorgente da 128 ingrandisce il file e basta, e c'è scritto.
- **Non spreca qualità.** Dove può, copia invece di ricodificare: l'audio che YouTube serve già in AAC non viene compresso una seconda volta, e uno spezzone tagliato in copia esce in un istante e identico all'originale.
- **Un lavoro si segue.** Ogni sezione ha la sua barra, che dice un numero vero. Se qualcosa va storto si apre una finestra con la causa in italiano e il testo tecnico sotto.
- **Non c'è niente da preparare.** Al primo avvio scarica da solo FFmpeg e Tor. Il resto arriva la prima volta che lo usi.

## Avvio rapido

Serve [Python 3.12](https://www.python.org/downloads/) o successivo e [Git](https://git-scm.com/).

```sh
git clone https://github.com/Imkun-on/Pica
cd Pica
pip install -r requirements.txt    # le dipendenze, una volta sola
python main.py                     # apre la finestra
```

Al primo avvio la finestra ci mette qualche minuto in più: sta scaricando FFmpeg e Tor
in `%LOCALAPPDATA%\Pica`. I modelli per i sottotitoli e per l'AI arrivano la prima
volta che apri quelle sezioni, e possono pesare qualche centinaio di megabyte.

Per costruire l'installatore di Windows serve anche [Inno Setup](https://jrsoftware.org/isinfo.php):

```sh
winget install JRSoftware.InnoSetup
.\costruisci.ps1                   # produce installer\output\Pica-Setup.exe
```

L'icona e il marchio escono da un solo script. Se cambi `assets/icona-originale.png`:

```sh
python assets/marchio.py           # rifà .ico, .icns, .png e il marchio della finestra
```

## Com'è fatto

```
main.py          apre la finestra, e nient'altro
client/          l'interfaccia: una pagina HTML, CSS e JavaScript, senza framework
  features/      una sezione per file: audio, montaggio, sottotitoli...
server/          il lavoro vero, che non sa che esista un'interfaccia
  controllers/   quello che la pagina può chiedere a Python
  audio/ video/ burn/   i motori di ciascun mestiere
assets/          icona e marchio
installer/       lo script di Inno Setup
```

La finestra è una pagina web dentro il WebView del sistema ([pywebview](https://pywebview.flowrl.com/)):
non c'è nessun motore grafico da distribuire. La pagina chiama Python direttamente,
senza server e senza porte aperte verso l'esterno.

## Download

| Sistema | File | Note |
|---|---|---|
| **Windows** 10 e 11 | [`Pica-Setup.exe`](https://github.com/Imkun-on/Pica/releases/latest/download/Pica-Setup.exe) | L'installatore. Non servono Python né permessi di amministratore. |
| **Windows** 10 e 11 | [`Pica-Windows-portable.zip`](https://github.com/Imkun-on/Pica/releases/latest/download/Pica-Windows-portable.zip) | Senza installare: scompatta e lancia `Pica.exe`. Dalla prossima versione. |
| **macOS** | in arrivo | `.dmg` |
| **Linux** | in arrivo | `.AppImage` |

Le impronte SHA256 di ogni file sono in `SHA256SUMS.txt`, nella stessa
[release](https://github.com/Imkun-on/Pica/releases).

### Se Windows chiede se il file è sicuro

Pica non è firmato: una firma costa qualche centinaio di euro l'anno. Per
questo Windows non lo riconosce e avvisa che il file «non viene scaricato di
frequente». Non vuol dire che sia pericoloso: vuol dire che lo hanno scaricato in pochi.

- **Il browser ferma il download.** In Edge apri l'elenco dei download, passa sul file,
  poi **⋯** → **Conserva** → **Mostra altro** → **Conserva comunque**. Oppure scarica lo
  zip portabile, che di norma non viene fermato.
- **All'avvio compare «Windows ha protetto il PC».** Scegli **Ulteriori informazioni** →
  **Esegui comunque**. Succede una volta sola.

Se preferisci controllare prima, confronta l'impronta del file con quella pubblicata:

```powershell
Get-FileHash .\Pica-Setup.exe -Algorithm SHA256
```

## Licenza e crediti

Pica è rilasciato sotto **[PolyForm Noncommercial License 1.0.0](LICENSE)**: puoi
usarlo, studiarlo e modificarlo per scopi non commerciali.

È pensato per uso **personale**: usalo solo con contenuti di cui hai il diritto di
fruire, nel rispetto dei [Termini di Servizio di YouTube](https://www.youtube.com/t/terms)
e del diritto d'autore.

Sta in piedi grazie a [yt-dlp](https://github.com/yt-dlp/yt-dlp),
[FFmpeg](https://ffmpeg.org/), [pywebview](https://pywebview.flowrl.com/),
[Tor](https://www.torproject.org/), [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Opus-MT](https://github.com/Helsinki-NLP/Opus-MT), [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN),
[LRCLIB](https://lrclib.net/) e [mutagen](https://github.com/quodlibet/mutagen).
Il carattere dell'interfaccia è [Manrope](https://github.com/sharanda/manrope), con
licenza SIL Open Font 1.1.
