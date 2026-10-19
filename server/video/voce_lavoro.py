"""Il lavoratore della voce: gira nell'ambiente separato, non in Pica.

Chatterbox (e PyTorch sotto) vuole versioni di librerie che Pica usa gia'
in altre versioni, e pesa un giga: sta in un ambiente Python suo (vedi
``doppiaggio.ambiente``), e questo file e' l'unica cosa che ci gira dentro.
Non importa niente di Pica: riceve un lavoro in JSON, genera le frasi, e
racconta a che punto e' su stdout, una riga JSON per evento.

    {"riferimenti": {"<persona>": "voce.wav"}, "lingua": "it",
     "frasi": [{"testo": "...", "persona": "<persona>", "uscita": "f.wav"}]}

Il modello si carica una volta sola per tutte le frasi: caricarlo costa
minuti, e rifarlo a ogni battuta moltiplicherebbe l'attesa.
"""
import json
import os
import sys
import time


def dici(**evento):
    print(json.dumps(evento, ensure_ascii=False), flush=True)


def main():
    lavoro = json.load(open(sys.argv[1], encoding='utf-8'))
    import soundfile
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    torch.set_num_threads(os.cpu_count() or 4)
    dici(fase='caricamento')
    t0 = time.time()
    modello = ChatterboxMultilingualTTS.from_pretrained(device='cpu')
    dici(fase='caricato', secondi=round(time.time() - t0))

    frasi = lavoro['frasi']
    for n, frase in enumerate(frasi):
        t0 = time.time()
        onda = modello.generate(frase['testo'], language_id=lavoro.get('lingua', 'it'),
                                audio_prompt_path=lavoro['riferimenti'][frase['persona']])
        dati = onda.squeeze(0).numpy()
        soundfile.write(frase['uscita'], dati, modello.sr)
        dici(fase='frase', n=n + 1, totale=len(frasi),
             secondi=round(time.time() - t0, 1), durata=round(len(dati) / modello.sr, 2))
    dici(fase='fine')


if __name__ == '__main__':
    main()
