"""Il doppiaggio: far dire a chi parla un testo nuovo, con la sua voce.

Si parte da un video che ha gia' i sottotitoli coi colori: il colore dice chi
e' ognuno, e le sue battute danno l'esempio della sua voce. Chi usa la
sezione scrive accanto alle battute che vuole cambiare il testo nuovo; il
resto resta com'e'.

    le battute       dal .srt accanto al video, rimesse insieme: un riquadro
                     di dialogo ripete la battuta di sopra, e qui conta una
                     volta sola (vedi ``battute``).
    la voce          Chatterbox Multilingual, in un ambiente Python a parte
                     (vedi ``ambiente``), imita una voce da pochi secondi di
                     esempio. Ogni audio che produce porta una filigrana
                     inudibile che lo fa riconoscere come sintetico.
    il montaggio     la frase nuova va dove cominciava quella vecchia, al
                     posto dell'audio originale; se e' piu' lunga si
                     accelera un poco, fino a un terzo, e oltre sborda.
    la copia         ``Doppiaggio/<video> (doppiato).mp4``, coi sottotitoli
                     del testo nuovo disegnati nell'immagine. Che le voci
                     sono generate lo dicono i metadati e la filigrana
                     inudibile di Chatterbox. L'originale non si tocca.

Quanto costa
    Su un portatile senza scheda video (Ryzen 5 3500U) il modello impiega
    quattro minuti a caricarsi e circa cinquanta secondi per ogni secondo di
    voce. Le frasi gia' generate si tengono da parte (``_CACHE``): cambiare
    una battuta e rifare il doppiaggio rigenera solo quella.

Il labiale non si tocca: la bocca continua a dire la frase di prima.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass

import numpy as np

from server.config import paths
from server.utils.console import setup_logger
from server.video import sottotitoli as st

log = setup_logger('audiodex', 'audiodex.log')

# L'ambiente della voce sta fuori dalla cartella del programma: pesa un giga,
# e dentro OneDrive o dentro Program Files si sincronizzerebbe o non si
# potrebbe scrivere. E' anche corto di proposito: i file di PyTorch hanno
# percorsi lunghi, e Windows si ferma a 260 caratteri.
_BASE = paths.locale()
AMBIENTE = os.path.join(_BASE, 'voce')
_MODELLI = os.path.join(_BASE, 'voce-modelli')
_CACHE = os.path.join(_BASE, 'voce-cache')

# Chatterbox senza le sue dipendenze, e poi queste a mano: spacy-pkuseg serve
# solo al cinese e non si compila su Python 3.14, gradio solo alla sua demo.
# setuptools<81 perche' la filigrana (perth) usa ancora pkg_resources;
# soundfile perche' torchaudio, per scrivere i file, ne vuole un'altra ancora.
_PACCHETTI = ['numpy>=2', 'librosa==0.11.0', 's3tokenizer', 'torch>=2.9.0',
              'torchaudio>=2.9.0', 'transformers==5.2.0', 'diffusers==0.29.0',
              'resemble-perth>=1.0.0', 'conformer==0.3.2', 'safetensors==0.5.3',
              'pykakasi==2.3.0', 'pyloudnorm', 'omegaconf', 'setuptools<81',
              'soundfile']

# Quanti secondi di voce servono per imitarla bene, e oltre quanti non serve
# andare: di piu' allunga solo il calcolo.
_ESEMPIO_MINIMO = 8.0
_ESEMPIO_MASSIMO = 18.0
_FREQ_ESEMPIO = 24000

# Quanto si puo' accelerare una frase per farla stare dove stava la vecchia:
# oltre un terzo la voce diventa quella di un cartone animato.
_ACCELERA_MAX = 1.33
_SFUMA = 0.03       # secondi di dissolvenza ai bordi di ogni sostituzione

# Per la stima del tempo: caricamento del modello, e secondi di calcolo per
# secondo di voce, misurati sul portatile qui sopra. Una frase italiana
# detta a voce va a circa 14 caratteri al secondo.
_CARICAMENTO = 240.0
_SECONDI_PER_SECONDO = 50.0
_CARATTERI_AL_SECONDO = 14.0

@dataclass
class Battuta:
    """Una battuta come la vede chi doppia: una volta sola, anche se sta in
    due riquadri di seguito (dialogo a elenco)."""
    id: int
    inizio: float
    fine: float
    persona: int
    colore: str
    testo: str


# ── Le battute ───────────────────────────────────────────────────────────────

def battute(lista: list[st.Riquadro], colori: dict[int, str]
            ) -> tuple[list[Battuta], dict[tuple[int, int], int]]:
    """Le battute del .srt, e per ogni riga di ogni riquadro ``(riquadro,
    riga)`` la battuta a cui appartiene. Una riga uguale a una del riquadro
    di prima e' la stessa battuta che continua; le etichette dei suoni non
    sono battute."""
    uscita: list[Battuta] = []
    dove: dict[tuple[int, int], int] = {}
    prima: dict[tuple[int, str], int] = {}
    for n, r in enumerate(lista):
        adesso: dict[tuple[int, str], int] = {}
        for k, (persona, testo, _) in enumerate(r.righe):
            if persona == st.ETICHETTA:
                continue
            chiave = (persona, testo)
            if chiave in prima:
                b = uscita[prima[chiave]]
                b.fine = max(b.fine, r.fine)
                indice = prima[chiave]
            else:
                indice = len(uscita)
                uscita.append(Battuta(indice, r.inizio, r.fine, persona,
                                      colori.get(persona, ''), testo))
            adesso[chiave] = indice
            dove[(n, k)] = indice
        prima = adesso
    return uscita, dove


def apri(video: str) -> dict:
    """Le battute del video per la pagina, e le riscritture salvate l'ultima
    volta, se ci sono."""
    lista, colori = st.leggi_srt(st.nome_srt(video))
    elenco, _ = battute(lista, colori)
    salvate = {}
    try:
        with open(_file_riscritture(video), encoding='utf-8') as f:
            salvate = json.load(f)
    except (OSError, ValueError):
        pass
    return {
        'battute': [{'id': b.id, 'inizio': b.inizio, 'fine': b.fine, 'colore': b.colore,
                     'testo': b.testo, 'nuovo': salvate.get(str(b.id), '')}
                    for b in elenco],
        'doppiato': nome_doppiato(video) if os.path.isfile(nome_doppiato(video)) else '',
    }


def nome_doppiato(video: str) -> str:
    stem = os.path.splitext(os.path.basename(video))[0]
    return os.path.join(paths.cartella_doppiaggio(), f'{stem} (doppiato).mp4')


def _file_riscritture(video: str) -> str:
    stem = os.path.splitext(os.path.basename(video))[0]
    return os.path.join(paths.cartella_doppiaggio(), f'{stem}.riscritture.json')


def stima(riscritture: dict[int, str], pronte: int = 0) -> float:
    """Secondi che ci vorranno, grosso modo."""
    caratteri = sum(len(t) for t in riscritture.values())
    if not caratteri:
        return 0.0
    return _CARICAMENTO + _SECONDI_PER_SECONDO * caratteri / _CARATTERI_AL_SECONDO


# ── L'ambiente della voce ────────────────────────────────────────────────────

def python_voce() -> str:
    cartella = 'Scripts' if os.name == 'nt' else 'bin'
    nome = 'python.exe' if os.name == 'nt' else 'python'
    return os.path.join(AMBIENTE, cartella, nome)


def ambiente_pronto() -> bool:
    if not os.path.isfile(python_voce()):
        return False
    prova = subprocess.run([python_voce(), '-c', 'import chatterbox.mtl_tts, soundfile, perth'],
                           capture_output=True)
    return prova.returncode == 0


def prepara_ambiente(avanza=None) -> None:
    """Crea l'ambiente della voce la prima volta: un Python a parte con
    Chatterbox e PyTorch dentro. Circa un giga da scaricare, una volta sola."""
    if ambiente_pronto():
        return
    if getattr(sys, 'frozen', False):
        raise RuntimeError('La voce ha bisogno di Python installato sul computer: '
                           'avvia Pica dai sorgenti per usarla la prima volta.')
    if avanza:
        avanza('preparo la voce (la prima volta, circa un giga)')
    os.makedirs(_BASE, exist_ok=True)
    if not os.path.isfile(python_voce()):
        subprocess.run([sys.executable, '-m', 'venv', AMBIENTE], check=True, capture_output=True)
    pip = [python_voce(), '-m', 'pip', 'install', '-q']
    subprocess.run(pip + ['--upgrade', 'pip'], check=True, capture_output=True)
    subprocess.run(pip + ['--no-deps', 'chatterbox-tts'], check=True, capture_output=True)
    subprocess.run(pip + _PACCHETTI, check=True, capture_output=True)
    if not ambiente_pronto():
        raise RuntimeError("L'ambiente della voce non si e' installato: vedi il log.")


# ── L'audio ──────────────────────────────────────────────────────────────────

def _leggi_audio(file: str, frequenza: int, canali: int, filtri: str = '') -> np.ndarray:
    comando = ['ffmpeg', '-v', 'error', '-nostdin', '-i', file, '-vn']
    if filtri:
        comando += ['-af', filtri]
    comando += ['-ac', str(canali), '-ar', str(frequenza), '-f', 'f32le', '-']
    uscita = subprocess.run(comando, capture_output=True, check=True)
    return np.frombuffer(uscita.stdout, dtype=np.float32).reshape(-1, canali).copy()


def _scrivi_wav(file: str, audio: np.ndarray, frequenza: int) -> None:
    """WAV a 16 bit, senza dipendere da librerie in piu'."""
    if audio.ndim == 1:
        audio = audio[:, None]
    dati = (np.clip(audio, -1, 1) * 32767).astype('<i2')
    with wave.open(file, 'wb') as w:
        w.setnchannels(dati.shape[1])
        w.setsampwidth(2)
        w.setframerate(frequenza)
        w.writeframes(dati.tobytes())


def _info_audio(video: str) -> tuple[int, int]:
    uscita = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
         'stream=sample_rate,channels', '-of', 'csv=p=0', video],
        capture_output=True, text=True)
    try:
        freq, canali = (int(v) for v in uscita.stdout.strip().split(',')[:2])
        return freq, min(canali, 2)
    except ValueError:
        return 44100, 2


def _esempi(video: str, elenco: list[Battuta], persone: set[int], cartella: str
            ) -> dict[int, str]:
    """Un esempio della voce di ogni persona: le sue battute, una dopo
    l'altra, finche' non bastano. Prima le piu' lunghe, che hanno meno
    pezzi di altri dentro."""
    audio = _leggi_audio(video, _FREQ_ESEMPIO, 1)[:, 0]
    pausa = np.zeros(int(0.25 * _FREQ_ESEMPIO), np.float32)
    uscita = {}
    for persona in persone:
        sue = sorted((b for b in elenco if b.persona == persona),
                     key=lambda b: -(b.fine - b.inizio))
        pezzi, durata = [], 0.0
        for b in sue:
            a, z = int(b.inizio * _FREQ_ESEMPIO), int(b.fine * _FREQ_ESEMPIO)
            pezzi += [audio[a:z], pausa]
            durata += b.fine - b.inizio
            if durata >= _ESEMPIO_MASSIMO:
                break
        if durata < _ESEMPIO_MINIMO:
            log.warning('Voce della persona %d: solo %.1f s di esempio', persona, durata)
        esempio = np.concatenate(pezzi)[:int(_ESEMPIO_MASSIMO * _FREQ_ESEMPIO)]
        # Il volume dell'esempio conta: troppo basso, e la voce imitata esce
        # sussurrata.
        picco = float(np.abs(esempio).max()) or 1.0
        file = os.path.join(cartella, f'esempio{persona}.wav')
        _scrivi_wav(file, esempio * (0.9 / picco), _FREQ_ESEMPIO)
        uscita[persona] = file
    return uscita


def _impronta_file(file: str) -> str:
    with open(file, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()[:16]


# ── Il mestiere intero ───────────────────────────────────────────────────────

def doppia(video: str, riscritture: dict[int, str], avanza=None) -> str:
    """Fa la copia doppiata: le battute in ``riscritture`` (id -> testo
    nuovo) dette con la voce di chi le diceva. Restituisce il percorso."""
    def dici(testo: str, fatte: int = 0, totale: int = 0) -> None:
        if avanza:
            avanza(testo, fatte, totale)

    lista, colori = st.leggi_srt(st.nome_srt(video))
    elenco, dove = battute(lista, colori)
    cambiate = {i: t.strip() for i, t in riscritture.items()
                if 0 <= i < len(elenco) and t.strip() and t.strip() != elenco[i].testo}
    with open(_file_riscritture(video), 'w', encoding='utf-8') as f:
        json.dump({str(i): t for i, t in cambiate.items()}, f, ensure_ascii=False, indent=1)
    if not cambiate:
        raise RuntimeError('Nessuna battuta riscritta: scrivi il testo nuovo accanto a quelle da cambiare.')

    prepara_ambiente(lambda t: dici(t))
    os.makedirs(_CACHE, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pica_voce_') as tmp:
        persone = {elenco[i].persona for i in cambiate}
        esempi = _esempi(video, elenco, persone, tmp)
        impronte = {p: _impronta_file(f) for p, f in esempi.items()}

        # Le frasi gia' fatte con lo stesso testo e la stessa voce non si
        # rifanno.
        uscite, da_fare = {}, []
        for i, testo in cambiate.items():
            p = elenco[i].persona
            chiave = hashlib.sha1(f'{impronte[p]}|{testo}'.encode('utf-8')).hexdigest()[:20]
            uscite[i] = os.path.join(_CACHE, chiave + '.wav')
            if not os.path.isfile(uscite[i]):
                da_fare.append({'testo': testo, 'persona': str(p), 'uscita': uscite[i]})

        if da_fare:
            _genera(video, esempi, da_fare, st._lingua_traccia(video) or 'it', dici)

        dici('monto le voci nuove')
        audio_nuovo = os.path.join(tmp, 'audio.wav')
        _monta(video, elenco, cambiate, uscite, audio_nuovo)

        dici('scrivo la copia')
        nuove = [st.Riquadro(r.inizio, r.fine, [
            (persona, cambiate.get(dove.get((n, k), -1), testo), lineetta)
            for k, (persona, testo, lineetta) in enumerate(r.righe)])
            for n, r in enumerate(lista)]
        uscita = nome_doppiato(video)
        st.scrivi_srt(nuove, os.path.splitext(uscita)[0] + '.srt', colori)
        ass = os.path.join(tmp, 'sottotitoli.ass')
        larghezza, altezza = st._dimensioni(video)
        st.scrivi_ass(nuove, ass, colori, larghezza, altezza)
        _imprimi_con_audio(video, ass, audio_nuovo, uscita)
    log.info('Doppiaggio: %d battute riscritte - %s', len(cambiate), os.path.basename(uscita))
    return uscita


def _genera(video, esempi, frasi, lingua, dici) -> None:
    """Fa girare il lavoratore nell'ambiente della voce e ne riporta
    l'avanzamento."""
    lavoro = {'riferimenti': {str(p): f for p, f in esempi.items()},
              'lingua': lingua[:2], 'frasi': frasi}
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(lavoro, f, ensure_ascii=False)
        file_lavoro = f.name
    ambiente = {**os.environ, 'HF_HOME': _MODELLI, 'PYTHONIOENCODING': 'utf-8'}
    lavoratore = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voce_lavoro.py')
    dici('carico il modello della voce', 0, len(frasi))
    # Lo stderr del lavoratore va in un file, non in un tubo: le barre di
    # avanzamento di Chatterbox ci scrivono di continuo, e un tubo che nessuno
    # legge si riempie in pochi secondi e ferma il lavoratore ad aspettare.
    # Cosi' era successo: venti minuti fermo, senza un errore.
    diario = file_lavoro + '.err'
    try:
        with open(diario, 'w', encoding='utf-8', errors='replace') as err:
            processo = subprocess.Popen([python_voce(), lavoratore, file_lavoro],
                                        stdout=subprocess.PIPE, stderr=err,
                                        text=True, encoding='utf-8', errors='replace',
                                        env=ambiente)
            for riga in processo.stdout:
                try:
                    evento = json.loads(riga)
                except ValueError:
                    continue
                if evento.get('fase') == 'frase':
                    dici('genero le voci', evento['n'], evento['totale'])
            codice = processo.wait()
        if codice != 0:
            errore = open(diario, encoding='utf-8', errors='replace').read()
            log.error('Lavoratore della voce: %s', errore[-2000:])
            raise RuntimeError('La generazione della voce non e\' riuscita: ' + errore.strip()[-300:])
    finally:
        for f in (file_lavoro, diario):
            try:
                os.remove(f)
            except OSError:
                pass


def _monta(video: str, elenco: list[Battuta], cambiate: dict[int, str],
           uscite: dict[int, str], dove: str) -> None:
    """L'audio del video con le frasi nuove al posto delle vecchie."""
    freq, canali = _info_audio(video)
    audio = _leggi_audio(video, freq, canali)
    sfuma = int(_SFUMA * freq)
    inizi = sorted(b.inizio for b in elenco)
    for i in sorted(cambiate):
        b = elenco[i]
        # Lo spazio che ha: fino alla battuta dopo, chiunque la dica.
        dopo = next((t for t in inizi if t > b.inizio + 0.05), b.fine + 1.0)
        spazio = max(dopo - b.inizio, b.fine - b.inizio, 0.5)
        durata = _durata_wav(uscite[i])
        velocita = min(max(durata / spazio, 1.0), _ACCELERA_MAX)
        filtri = f'atempo={velocita:.3f}' if velocita > 1.001 else ''
        nuova = _leggi_audio(uscite[i], freq, canali, filtri)
        a = int(b.inizio * freq)
        # Via la frase vecchia: tutta la battuta, e quanto sborda la nuova.
        z = min(len(audio), max(int(b.fine * freq), a + len(nuova)))
        if z <= a:
            continue
        rampa = np.linspace(1, 0, min(sfuma, z - a), dtype=np.float32)[:, None]
        audio[a:a + len(rampa)] *= rampa
        audio[a + len(rampa):z] = 0
        coda = min(sfuma, len(audio) - z)
        if coda > 0:
            audio[z:z + coda] *= np.linspace(0, 1, coda, dtype=np.float32)[:, None]
        pezzo = nuova[:len(audio) - a]
        audio[a:a + len(pezzo)] += pezzo
    _scrivi_wav(dove, audio, freq)


def _durata_wav(file: str) -> float:
    uscita = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'csv=p=0', file], capture_output=True, text=True)
    try:
        return float(uscita.stdout.strip())
    except ValueError:
        return 0.0


def _imprimi_con_audio(video: str, ass: str, audio: str, uscita: str) -> None:
    """Come ``sottotitoli.imprimi``, ma con l'audio nuovo al posto di quello
    del video. FFmpeg si lancia dalla cartella del file di sottotitoli per
    lo stesso motivo: il filtro vuole il nome nudo."""
    cartella = os.path.dirname(ass)
    _, altezza = st._dimensioni(video)
    filtri = 'subtitles=' + os.path.basename(ass)
    if altezza < st.ALTEZZA_IMPRESSI:
        filtri = f'scale=-2:{st.ALTEZZA_IMPRESSI}:flags=lanczos,setsar=1,' + filtri
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', os.path.abspath(video),
         '-i', os.path.abspath(audio), '-vf', filtri, '-map', '0:v:0', '-map', '1:a:0',
         '-c:v', 'libx264', '-crf', '20', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '192k', '-sn', '-movflags', '+faststart',
         '-metadata', 'comment=Voci generate con Pica (Chatterbox): non sono le voci originali',
         os.path.abspath(uscita)],
        cwd=cartella, check=True, capture_output=True)
