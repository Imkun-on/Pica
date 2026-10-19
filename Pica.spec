# Istruzioni per costruire Pica con PyInstaller.
#
#     .\costruisci.ps1                 (e' lui che chiama questo file)
#     python -m PyInstaller Pica.spec --noconfirm
#
# A cartella, non a file unico
#     E' cambiato con l'installatore, e cambia due cose in meglio.
#
#     Il file unico si riestraeva in una cartella temporanea A OGNI AVVIO:
#     sessanta megabyte da scompattare ogni volta che si apre il programma,
#     otto secondi buoni prima che partisse una riga di Python. A cartella non
#     si scompatta niente: l'avvio e' quello che resta, cioe' il tempo di
#     importare Rich e il ponte con WebView2.
#
#     E l'aggiornamento diventa pulito. L'installatore spazza {app}\_internal
#     prima di ricopiare (vedi [InstallDelete] in installer/Pica.iss):
#     senza, le librerie di due versioni diverse si accumulerebbero nella
#     stessa cartella e Python ne caricherebbe un misto.
#
# Cosa entra e cosa no
#     Entra tutto il programma: gli strati di server/, la pagina di client/, e
#     l'interprete Python. Chi riceve l'installatore fa doppio clic: non
#     installa Python, non vede un file .py, non sa nemmeno che c'e' dentro.
#
#     NON entra FFmpeg. Adesso sarebbe possibile - a cartella non c'e' piu' il
#     costo di riestrarlo a ogni avvio - ma sono 400 MB che triplicherebbero il
#     peso dell'installatore. Il programma se ne accorge da solo se manca e lo
#     scarica al primo avvio (vedi server/utils/ffmpeg.py).
#
# Perche' un file .spec e non una riga di comando
#     Perche' le scelte qui dentro vanno spiegate, e una riga di comando lunga
#     duecento caratteri non ha posto per farlo.

import os
import sys

# yt-dlp carica gli estrattori uno per uno solo quando servono: PyInstaller,
# che guarda gli import scritti nel codice, non ne troverebbe nemmeno uno e
# l'eseguibile saprebbe scaricare da nessun sito.
from PyInstaller.utils.hooks import (
    collect_data_files, collect_dynamic_libs, collect_submodules)

# La cartella di questo file. PyInstaller la passa allo spec come SPECPATH ma
# la aggiunge a sys.path solo piu' avanti, dentro Analysis(): gli import qui
# sotto servono prima, quindi ce la si mette da soli. Senza, la costruzione
# fallirebbe con un ModuleNotFoundError su 'server' a seconda di da dove si e'
# lanciato il comando.
sys.path.insert(0, os.path.abspath(SPECPATH))

# Tutto server/, sottomodulo per sottomodulo.
#
# Elencarli a mano era un elenco di trenta righe da tenere allineato a una
# cartella che cambia: la prima volta che qualcuno ne avesse aggiunto uno senza
# aggiornare questa lista, l'eseguibile avrebbe perso una sezione intera - e
# non all'avvio, dove si sarebbe visto subito, ma al primo clic su quel
# bottone, perche' i motori si caricano quando servono.
nascosti = collect_submodules('server')

nascosti += [
    # pywebview parla con WinForms su Windows, che passa per pythonnet.
    'webview.platforms.winforms', 'clr_loader', 'pythonnet',
    # BurnDex comanda il masterizzatore via COM.
    'win32com', 'win32com.client', 'pythoncom', 'pywintypes',
    # mutagen scrive i tag nel contenitore MP4.
    'mutagen', 'mutagen.mp4',
    # requests parla SOCKS (Tor) solo se trova PySocks, e lo cerca a runtime.
    'socks', 'urllib3.contrib.socks',
]
nascosti += collect_submodules('yt_dlp')
# I sottotitoli coi parlanti: Whisper (ctranslate2) per il testo, sherpa-onnx
# per le impronte vocali, scipy per raggrupparle, sentencepiece per la
# traduzione. Si caricano solo quando servono, quindi PyInstaller da solo non
# li vedrebbe.
nascosti += ['faster_whisper', 'ctranslate2', 'ctranslate2.converters',
             'sherpa_onnx', 'onnxruntime', 'scipy.cluster.hierarchy',
             'sentencepiece']

dati = [
    # La pagina: e' l'interfaccia vera e propria.
    ('client', 'client'),
]
# L'icona della finestra: la stessa dell'eseguibile, ma pywebview la vuole
# come file, non incorporata nelle risorse del .exe.
for _risorsa in ('Pica.ico', 'Pica.png'):
    if os.path.exists(os.path.join('assets', _risorsa)):
        dati.append((os.path.join('assets', _risorsa), 'assets'))
dati += collect_data_files('yt_dlp')
# Il VAD di faster-whisper e' un modello .onnx dentro il pacchetto.
dati += collect_data_files('faster_whisper')

a = Analysis(
    ['main.py'],
    pathex=[os.path.abspath(SPECPATH)],
    binaries=collect_dynamic_libs('ctranslate2') + collect_dynamic_libs('sherpa_onnx'),
    datas=dati,
    hiddenimports=nascosti,
    hookspath=[],
    runtime_hooks=[],
    # Fuori cio' che non serve: sono decine di megabyte che non verrebbero
    # mai eseguiti.
    #
    # setuptools NON si puo' escludere, per quanto sembri inutile in un
    # programma finito: qualcosa nella catena carica ``pkg_resources``, che e'
    # parte di setuptools e si porta dietro le proprie dipendenze interne.
    # Toglierlo faceva morire l'eseguibile all'avvio, prima ancora di aprire
    # la finestra, con un ModuleNotFoundError su 'jaraco'.
    #
    # tkinter adesso SI puo' escludere, e sono una decina di megabyte. Finche'
    # c'era la schermata di caricamento di PyInstaller non si poteva: quella e'
    # disegnata da Tcl/Tk. Tolta lei, qui dentro non resta una riga che apra
    # una finestra che non sia WebView2.
    #
    # Qt e IPython pesavano insieme 52 MB su 165, e non ne veniva eseguita
    # una riga:
    #   PySide6  pywebview sa parlare con piu' motori grafici e PyInstaller
    #            li impacchetta tutti. Su Windows si usa winforms, quello di
    #            sistema; Qt era 45 MB per niente.
    #   IPython  rich, per capire se sta scrivendo dentro un notebook, prova
    #            a importarlo dentro un try. PyInstaller vede l'import e si
    #            porta dietro IPython, jedi e traitlets: qui non c'e' nessun
    #            notebook, e il try regge benissimo l'assenza.
    excludes=['unittest', 'pydoc', 'doctest', 'test',
              'tkinter', '_tkinter', 'Tkinter',
              # numpy invece resta: serve ai sottotitoli.
              'matplotlib', 'sklearn', 'torch', 'whisper',
              'PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'qtpy', 'shiboken6',
              'IPython', 'jedi',
              # nltk arriva da transformers (un tokenizer che qui non si usa)
              # e il suo aggancio d'avvio vuole pydoc, escluso qui sopra:
              # l'eseguibile moriva prima di aprire la finestra.
              'nltk'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── Il manifest: la scala dello schermo e i percorsi lunghi, dichiarati SUBITO ─
#
# E' il manifest predefinito di PyInstaller con due righe in piu'.
#
# <dpiAware> toglie un difetto che si vede a occhio nudo. pywebview, quando
# avvia la finestra, chiama SetProcessDPIAware(): da quel momento il programma
# dichiara di sapersi disegnare da se' alla scala dello schermo. Finche' non lo
# dichiara, e' Windows a stirargli le finestre, quindi su uno schermo al 125%
# la finestra nasce ingrandita e sfocata, e nell'istante della
# dichiarazione SCATTA alla misura vera ri-centrandosi - un ridimensionamento
# improvviso in mezzo all'avvio. Dichiarandolo qui vale dal primo istante,
# prima ancora che esista un interprete Python: lo stato finale e' lo stesso,
# cambia solo quando viene raggiunto.
#
# <longPathAware> serve a Pica piu' che ad altri: i nomi delle cartelle
# vengono dai titoli delle playlist di YouTube, e fra artista, album e nome
# della traccia i 260 caratteri si superano senza sforzo.
MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"></supportedOS>
      <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"></supportedOS>
      <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"></supportedOS>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"></supportedOS>
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"></supportedOS>
    </application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>
    </windowsSettings>
  </application>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"></assemblyIdentity>
    </dependentAssembly>
  </dependency>
</assembly>
"""

exe = EXE(
    pyz,
    a.scripts,
    [],
    # A cartella: i binari e i dati non entrano nell'eseguibile, li raccoglie
    # COLLECT qui sotto dentro _internal/.
    exclude_binaries=True,
    name='Pica',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # comprimere allunga l'avvio e insospettisce gli antivirus
    # Senza finestra di terminale alle spalle: e' un programma con
    # un'interfaccia, non uno script.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=MANIFEST,
    # Il marchio: la gazza col CD nel becco, generata da assets/marchio.py.
    # Senza questa riga Windows mostra l'icona di ripiego di
    # PyInstaller, che non c'entra niente con il programma.
    icon=os.path.join('assets', 'Pica.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Pica',
)
