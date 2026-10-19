/* Sezione Audio: la libreria, le opzioni, il lettore.
 *
 * Come scorre il lavoro
 *     Si incolla un link e si preme Analizza: Python guarda cosa c'e' dietro e
 *     non scarica niente. Quello che ha trovato entra nella libreria come «in
 *     coda», spuntato. A destra si sceglie come lo si vuole - formato,
 *     qualita', metadati, dove - e «Scarica audio» scarica le righe spuntate.
 *     Quello che arriva resta nella libreria, e si ascolta dal lettore in
 *     basso.
 *
 * La libreria non comincia vuota
 *     All'apertura Python manda i brani gia' scaricati, presi dal suo registro
 *     e tenuti solo se il file c'e' ancora. Sono righe come le altre.
 *
 * Una riga e il suo numero
 *     Python conosce le tracce dell'ultimo link per numero d'ordine, e a quel
 *     numero riferisce l'avanzamento. Le righe venute da un link precedente
 *     quel numero non lo hanno piu': se erano ancora in coda spariscono,
 *     perche' Python le ha dimenticate e non saprebbe scaricarle.
 *
 * Gli eventi di Python (mostraScelta, tracciaFase, tracciaAvanza,
 * tracciaFinita) arrivano in audio.js, che per Audio li gira qui.
 */

const LIB = {
  righe: [],            // dalla piu' recente
  scelta: null,         // la riga di cui si vedono i dettagli
  suona: null,          // quella nel lettore
  linguetta: 'tutti',
  cerca: '',
  soloFatti: false,
  cartella: '',         // vuota: la cartella di Pica
  libero: 0,
  prossima: 1,
};

const SIGLE = { m4a: 'M4A', mp3: 'MP3', opus: 'OPUS', flac: 'FLAC', wav: 'WAV' };
// I formati senza perdita non hanno un bitrate da scegliere.
const SENZA_PERDITA = ['flac', 'wav'];

const L$ = (id) => document.getElementById(id);

/* ── Numeri scritti come li legge una persona ──────────────────────────── */

function pesoLeggibile(byte) {
  if (!byte) return '—';
  const mb = byte / 1048576;
  if (mb >= 1024) return (mb / 1024).toLocaleString('it-IT', { maximumFractionDigits: 1 }) + ' GB';
  return mb.toLocaleString('it-IT', { maximumFractionDigits: 1 }) + ' MB';
}

/* ── Le opzioni ────────────────────────────────────────────────────────── */

function opzioniAudio() {
  const formato = L$('a-formato').value;
  return {
    formato,
    bitrate: SENZA_PERDITA.includes(formato) ? 0 : +L$('a-qualita').value,
    frequenza: +L$('a-frequenza').value,
    mono: L$('a-mono').checked,
    normalizza: L$('a-normalizza').checked,
    metadati: L$('a-metadati').checked,
    copertina: L$('a-copertina').checked,
    cartella: LIB.cartella,
    cartella_playlist: L$('a-cartella-playlist').checked,
    // I testi si cercano sempre, e a quelli senza tempi i tempi si danno
    // ascoltando il brano.
    testi: true,
    sincronizza: true,
  };
}

/* Le opzioni che non hanno senso insieme si spengono da sole: un formato
 * senza perdita non ha una qualita' da scegliere, il WAV non ha posto per la
 * copertina, e senza metadati la copertina non c'e'. */
function aggiornaOpzioni() {
  const formato = L$('a-formato').value;
  const fissa = SENZA_PERDITA.includes(formato);
  const qualita = L$('a-qualita');
  qualita.disabled = fissa;
  qualita.closest('.gruppo').classList.toggle('spento', fissa);
  const copertina = L$('a-copertina');
  const senza = formato === 'wav' || !L$('a-metadati').checked;
  copertina.disabled = senza;
  copertina.closest('.interruttore').classList.toggle('spento', senza);
  // La colonna «Formato» delle righe in coda dice quello scelto adesso.
  LIB.righe.filter((r) => r.stato === 'coda').forEach(aggiornaNodo);
}

function nomeCartella() {
  L$('a-cartella-nome').textContent = LIB.cartella
    ? LIB.cartella.split(/[\\/]/).filter(Boolean).slice(-2).join(' / ')
    : window.t('opz.salva.solita');
  L$('a-cartella').title = LIB.cartella || '';
}

/* ── Le righe ──────────────────────────────────────────────────────────── */

function nuovaRiga(dati) {
  const r = {
    id: LIB.prossima++, indice: null, titolo: '', artista: '', album: '',
    durata: '', formato: '', peso: 0, stato: 'coda', frazione: 0, fase: '',
    url: '', testo: '', miniatura: '', spuntata: true, ...dati,
  };
  r.nodo = creaNodo(r);
  return r;
}

function creaNodo(r) {
  const nodo = window.el('div', 'brano');
  nodo.innerHTML =
    '<span class="col-spunta"><input type="checkbox"></span>' +
    '<div class="brano-info"><div class="copertina"></div>' +
      '<div class="brano-nomi"><div class="brano-titolo"><span></span>' +
        '<svg class="icona" viewBox="0 0 24 24"><use href="#i-onde"/></svg></div>' +
      '<div class="brano-artista"></div></div></div>' +
    '<span class="brano-durata"></span>' +
    '<div class="brano-formato"><b></b><span></span></div>' +
    '<span class="esito"></span>' +
    '<button class="bottone-icona" type="button">' +
      '<svg class="icona" viewBox="0 0 24 24"><use href="#i-puntini"/></svg></button>' +
    '<div class="filo"></div>';

  const spunta = nodo.querySelector('input');
  spunta.addEventListener('click', (e) => e.stopPropagation());
  spunta.addEventListener('change', () => { r.spuntata = spunta.checked; contaCoda(); });
  nodo.querySelector('.bottone-icona').title = window.t('lib.dettagli');
  nodo.querySelector('.bottone-icona').addEventListener('click', (e) => {
    e.stopPropagation(); scegli(r);
  });
  nodo.addEventListener('click', () => scegli(r));
  // Due clic e il brano parte, come in qualunque elenco di musica.
  nodo.addEventListener('dblclick', () => suona(r));
  return nodo;
}

function mettiCopertina(dove, r) {
  dove.innerHTML = '';
  if (!r || !r.miniatura) return;
  const img = new Image();
  img.alt = '';
  // Un'immagine che non arriva lascia il riquadro vuoto, non un'icona rotta.
  img.onerror = () => img.remove();
  img.src = r.miniatura;
  dove.appendChild(img);
}

function aggiornaNodo(r) {
  const n = r.nodo;
  n.className = 'brano stato-' + r.stato +
    (LIB.scelta === r ? ' scelto' : '') + (LIB.suona === r ? ' suona' : '');
  const spunta = n.querySelector('input');
  // Si spunta solo cio' che e' in coda: e' la scelta di cosa scaricare.
  spunta.checked = r.stato === 'coda' && r.spuntata;
  spunta.style.visibility = r.stato === 'coda' ? '' : 'hidden';

  // I titoli arrivano da YouTube: si scrivono come testo, mai come HTML.
  n.querySelector('.brano-titolo span').textContent = r.titolo;
  n.querySelector('.brano-artista').textContent = r.artista;
  n.querySelector('.brano-durata').textContent = r.durata || '—';
  if (r.miniatura && !n.querySelector('.copertina img')) mettiCopertina(n.querySelector('.copertina'), r);

  const formato = r.stato === 'fatto' ? r.formato : L$('a-formato').value;
  n.querySelector('.brano-formato b').textContent = SIGLE[formato] || formato.toUpperCase();
  n.querySelector('.brano-formato span').textContent = r.stato === 'fatto' ? pesoLeggibile(r.peso) : '';

  const esito = n.querySelector('.esito');
  const quota = Math.round(r.frazione * 100);
  const cosa = {
    fatto: ['i-spunta', window.t('lib.stato.fatto')],
    coda: ['', window.t('lib.stato.coda')],
    fallito: ['i-errore', window.t('lib.stato.fallito')],
    // Finche' scarica dice la percentuale; dopo, il passo in cui si trova.
    lavora: ['i-freccia-giu', r.fase && r.fase !== 'download'
      ? window.t('fase.' + r.fase) : window.t('lib.stato.scarico', { quota })],
  }[r.stato];
  esito.className = 'esito esito-' + r.stato;
  esito.innerHTML = cosa[0]
    ? '<svg class="icona" viewBox="0 0 24 24"><use href="#' + cosa[0] + '"/></svg><span></span>'
    : '<i class="punto"></i><span></span>';
  esito.querySelector('span').textContent = cosa[1];
  esito.title = r.errore || '';
  n.querySelector('.filo').style.width = r.stato === 'lavora' ? quota + '%' : '0';
}

/* Le righe della vista aperta. L'archivio tiene i brani scaricati in passato
 * (nelle sessioni prima, o prima di lasciare la sezione); le altre linguette
 * solo quelli di adesso, cosi' Audio si apre pulita e non mostra il lavoro di
 * ieri. */
function inVista() {
  const archivio = LIB.linguetta === 'archivio';
  return LIB.righe.filter((r) => Boolean(r.passato) === archivio);
}

function visibili() {
  const cerca = LIB.cerca.trim().toLowerCase();
  return inVista().filter((r) => {
    if (cerca && !(r.titolo + ' ' + r.artista).toLowerCase().includes(cerca)) return false;
    if (LIB.soloFatti && r.stato !== 'fatto') return false;
    if (LIB.linguetta === 'fatti') return r.stato === 'fatto';
    if (LIB.linguetta === 'coda') return r.stato !== 'fatto';
    return true;
  });
}

function disegnaLibreria() {
  const box = L$('a-risultati');
  const righe = visibili();
  righe.forEach(aggiornaNodo);
  if (righe.length) {
    box.replaceChildren(...righe.map((r) => r.nodo));
  } else {
    const vista = inVista();
    box.replaceChildren(window.statoVuoto(window.t(vista.length ? 'lib.vuota'
      : LIB.linguetta === 'archivio' ? 'lib.archivio.vuoto' : 'lib.vuota.inizio')));
  }
  L$('a-conta').textContent = String(inVista().length);
  const fatti = inVista().filter((r) => r.stato === 'fatto');
  L$('a-totali').textContent = window.t('lib.totali', {
    n: fatti.length, peso: pesoLeggibile(fatti.reduce((s, r) => s + (r.peso || 0), 0)),
  });
  L$('a-spazio').textContent = LIB.libero
    ? window.t('lib.libero', { spazio: pesoLeggibile(LIB.libero) }) : '';
  contaCoda();
}

/* Quante righe aspettano, e quante di queste sono spuntate: il numero sulla
 * linguetta e quello sul bottone. */
function contaCoda() {
  const inCoda = LIB.righe.filter((r) => r.stato !== 'fatto').length;
  const conta = L$('a-conta-coda');
  conta.hidden = !inCoda;
  conta.textContent = String(inCoda);

  const pronte = LIB.righe.filter((r) => r.stato === 'coda' && r.spuntata).length;
  const n = L$('a-avvia-n');
  n.hidden = !pronte;
  n.textContent = String(pronte);
  // Mentre un lavoro gira il bottone lo spegne il nucleo, e qui non lo si
  // riaccende: lo fara' ``riabilita`` a lavoro finito.
  if (!lavoroInCorso()) L$('a-avvia').disabled = !pronte;
  const tutte = LIB.righe.filter((r) => r.stato === 'coda');
  L$('a-tutti').checked = tutte.length > 0 && tutte.every((r) => r.spuntata);
}

function lavoroInCorso() {
  return Boolean(document.querySelector('.punto-stato.lavora'));
}

/* ── I dettagli della riga scelta ──────────────────────────────────────── */

function scegli(r) {
  LIB.scelta = r;
  LIB.righe.forEach((x) => x.nodo.classList.toggle('scelto', x === r));
  disegnaScelto();
}

let TESTO_RIGHE = [];
let TESTO_SINCRONO = false;

function disegnaScelto() {
  const box = L$('a-scelto');
  const r = LIB.scelta;
  box.innerHTML = '';
  TESTO_RIGHE = [];
  if (!r) {
    box.appendChild(window.el('p', 'nota-riga', window.t('opz.scelto.vuoto')));
    return;
  }
  const capo = window.el('div', 'scelto-capo');
  const copertina = window.el('div', 'copertina piccola');
  mettiCopertina(copertina, r);
  const nomi = window.el('div', 'brano-nomi');
  nomi.appendChild(window.el('strong', '', r.titolo));
  nomi.appendChild(window.el('span', '', r.artista));
  capo.append(copertina, nomi);
  box.appendChild(capo);

  const dati = window.el('dl', 'scheda-dati');
  const formato = r.stato === 'fatto' ? r.formato : L$('a-formato').value;
  [['opz.album', r.album || '—'], ['opz.durata', r.durata || '—'],
   ['opz.peso', pesoLeggibile(r.peso)], ['opz.formato', SIGLE[formato] || formato.toUpperCase()],
  ].forEach(([chiave, valore]) => {
    const riga = document.createElement('div');
    riga.appendChild(window.el('dt', '', window.t(chiave)));
    riga.appendChild(window.el('dd', '', valore));
    dati.appendChild(riga);
  });
  box.appendChild(dati);

  // Il testo, se il brano ce l'ha: la riga che si canta accesa, le altre in
  // penombra. Una riga si tocca e il brano salta li'.
  if (r.testo) {
    const letto = righeLrc(r.testo);
    TESTO_RIGHE = letto.righe;
    TESTO_SINCRONO = letto.sincronizzato;
    const pannello = window.el('div', 'testo-brano');
    pannello.id = 'a-testo';
    if (!TESTO_SINCRONO) {
      pannello.appendChild(window.el('div', 'testo-nota', window.t('lettore.senza_tempi')));
    }
    TESTO_RIGHE.forEach((riga) => {
      const nodo = window.el('div', 'testo-riga' + (riga.testo ? '' : ' pausa'), riga.testo || '♪');
      if (TESTO_SINCRONO) {
        nodo.addEventListener('click', () => {
          if (LIB.suona !== r) suona(r);
          AUDIO.currentTime = riga.t;
        });
      }
      riga.nodo = nodo;
      pannello.appendChild(nodo);
    });
    box.appendChild(pannello);
    seguiTesto(true);
  }
}

let TESTO_ATTUALE = -1;

function seguiTesto(subito) {
  const pannello = L$('a-testo');
  if (!pannello || !TESTO_SINCRONO || LIB.suona !== LIB.scelta) return;
  const adesso = AUDIO.currentTime + 0.15;
  let k = -1;
  for (let j = 0; j < TESTO_RIGHE.length && TESTO_RIGHE[j].t <= adesso; j++) k = j;
  if (k === TESTO_ATTUALE && !subito) return;
  TESTO_RIGHE.forEach((riga, j) => riga.nodo.classList.toggle('attuale', j === k));
  TESTO_ATTUALE = k;
  const nodo = TESTO_RIGHE[k] ? TESTO_RIGHE[k].nodo : null;
  // Scorre il solo riquadro del testo: la riga che si canta resta a un terzo
  // dall'alto, con le successive gia' in vista.
  const cima = nodo ? nodo.offsetTop - pannello.clientHeight / 3 : 0;
  pannello.scrollTo({ top: Math.max(cima, 0), behavior: subito ? 'auto' : 'smooth' });
}

/* ── Il lettore ────────────────────────────────────────────────────────── */

const AUDIO = new Audio();
AUDIO.preload = 'metadata';

function suona(r) {
  if (!r.url) { window.avvisa(window.t('lib.non_pronto')); return; }
  const prima = LIB.suona;
  if (prima !== r) {
    LIB.suona = r;
    AUDIO.src = r.url;
    if (prima) aggiornaNodo(prima);
    L$('a-s-titolo').textContent = r.titolo;
    L$('a-s-artista').textContent = r.artista;
    L$('a-s-formato').textContent = SIGLE[r.formato] || (r.formato || '').toUpperCase();
    mettiCopertina(L$('a-s-copertina'), r);
    L$('a-suonatore').classList.remove('fermo');
  }
  scegli(r);
  aggiornaNodo(r);
  const partenza = AUDIO.play();
  if (partenza) partenza.catch(() => {});
}

/* Il brano prima o dopo quello nel lettore, fra quelli che si vedono e si
 * possono ascoltare. In fondo all'elenco si ricomincia da capo. */
function vicino(passo) {
  const ascoltabili = visibili().filter((r) => r.url);
  if (!ascoltabili.length) return;
  const qui = ascoltabili.indexOf(LIB.suona);
  suona(ascoltabili[(qui + passo + ascoltabili.length) % ascoltabili.length]);
}

function disegnaLettore() {
  const tot = AUDIO.duration;
  const cerca = L$('a-s-cerca');
  if (isFinite(tot) && tot > 0) cerca.max = tot;
  cerca.value = AUDIO.currentTime;
  L$('a-s-ora').textContent = minuti(AUDIO.currentTime);
  seguiTesto(false);
}

function collegaLettore() {
  const play = L$('a-s-play');
  play.innerHTML = ICONA_PLAY;
  play.title = window.t('lettore.play');
  L$('a-s-prima').title = window.t('suona.precedente');
  L$('a-s-dopo').title = window.t('suona.successiva');
  L$('a-s-volume').title = window.t('suona.volume');
  L$('a-s-titolo').textContent = window.t('suona.niente');
  L$('a-suonatore').classList.add('fermo');

  play.addEventListener('click', () => {
    // Senza un brano nel lettore, play fa partire il primo che si puo'.
    if (!LIB.suona) { vicino(1); return; }
    if (AUDIO.paused) AUDIO.play(); else AUDIO.pause();
  });
  L$('a-s-prima').addEventListener('click', () => vicino(-1));
  L$('a-s-dopo').addEventListener('click', () => vicino(1));
  L$('a-s-cerca').addEventListener('input', (e) => {
    AUDIO.currentTime = +e.target.value;
    disegnaLettore();
  });
  const volume = L$('a-s-volume');
  AUDIO.volume = volume.value / 100;
  volume.addEventListener('input', () => { AUDIO.volume = volume.value / 100; });

  let giro = 0;
  const anima = () => { disegnaLettore(); if (!AUDIO.paused) giro = requestAnimationFrame(anima); };
  AUDIO.addEventListener('loadedmetadata', () => {
    L$('a-s-fine').textContent = minuti(AUDIO.duration);
    disegnaLettore();
  });
  AUDIO.addEventListener('play', () => {
    play.innerHTML = ICONA_PAUSA;
    play.title = window.t('lettore.pausa');
    anima();
  });
  AUDIO.addEventListener('pause', () => {
    cancelAnimationFrame(giro);
    play.innerHTML = ICONA_PLAY;
    play.title = window.t('lettore.play');
    disegnaLettore();
  });
  // Finito un brano parte il successivo, come ci si aspetta da una libreria.
  AUDIO.addEventListener('ended', () => vicino(1));
  AUDIO.addEventListener('seeked', disegnaLettore);
}

/* ── Dal link alla coda, dalla coda al disco ───────────────────────────── */

async function analizzaAudio() {
  const link = L$('a-link').value.trim();
  const esito = await window.pywebview.api.analizza(
    link, 'audio', { ...opzioniAudio(), attendi: true });
  if (!esito.ok) window.errore(esito.errore, 'audio');
}

/* Python ha guardato il link: quello che ha trovato entra in coda. */
function arrivaScelta(dati) {
  // La coda di prima Python non la ricorda piu', e le righe gia' lavorate
  // perdono il loro numero: adesso i numeri sono quelli del link nuovo.
  LIB.righe = LIB.righe.filter((r) => r.stato !== 'coda');
  LIB.righe.forEach((r) => { r.indice = null; });
  const voci = dati.voci || [];
  const nuove = voci.map((v, i) => nuovaRiga({
    indice: i, titolo: v.titolo || '', artista: v.canale || '',
    durata: v.durata || '', miniatura: v.miniatura || '',
    album: dati.playlist ? (dati.titolo || '') : '',
  }));
  LIB.righe = nuove.concat(LIB.righe);
  // Quello appena trovato si vede subito, anche se si stava guardando l'archivio.
  if (LIB.linguetta === 'archivio') {
    LIB.linguetta = 'tutti';
    L$('a-linguette').querySelectorAll('button').forEach((x) =>
      x.classList.toggle('attiva', x.dataset.l === 'tutti'));
  }
  L$('a-link').value = '';
  disegnaLibreria();
  if (nuove.length) scegli(nuove[0]);

  // Un video solo con la scaletta di un disco: si chiede subito se dividerlo.
  // La risposta torna da ``scaricaBrani`` con ``dividi`` deciso.
  if (dati.album) { sceltaAlbum('audio', voci[0] || {}, dati.album); return; }
  window.avvisa(window.t('lib.in_coda', { n: nuove.length }));
}

function scaricaCoda() {
  const indici = LIB.righe
    .filter((r) => r.stato === 'coda' && r.spuntata && r.indice !== null)
    .map((r) => r.indice).sort((a, b) => a - b);
  if (!indici.length) { window.avvisa(window.t('lib.niente'), 'fail'); return; }
  scaricaBrani(indici);
}

async function scaricaBrani(indici, extra) {
  const righe = LIB.righe.filter((r) => indici.includes(r.indice));
  righe.forEach((r) => {
    r.stato = 'lavora'; r.frazione = 0; r.fase = ''; r.errore = '';
    aggiornaNodo(r);
  });
  contaCoda();
  const esito = await window.pywebview.api.scarica({
    ...opzioniAudio(), ...(extra || {}), sezione: 'audio', scelti: indici,
  });
  if (!esito.ok) {
    righe.forEach((r) => { r.stato = 'coda'; aggiornaNodo(r); });
    contaCoda();
    window.errore(esito.errore, 'audio');
  }
}

const rigaNumero = (i) => LIB.righe.find((r) => r.indice === i);

function tracciaInFase(i, fase) {
  const r = rigaNumero(i);
  if (!r) return;
  r.stato = 'lavora';
  r.fase = fase;
  // Passato lo scarico, il resto del lavoro non ha una percentuale sua.
  if (fase !== 'download') r.frazione = 1;
  aggiornaNodo(r);
}

function tracciaAvanti(i, frazione) {
  const r = rigaNumero(i);
  if (!r) return;
  r.stato = 'lavora';
  r.frazione = Math.max(0, Math.min(1, frazione));
  aggiornaNodo(r);
}

function tracciaArrivata(i, d) {
  const r = rigaNumero(i);
  if (!r) return;
  r.stato = d.esito === 'fail' ? 'fallito' : 'fatto';
  r.errore = d.errore || '';
  r.url = d.url || '';
  r.testo = d.testo || '';
  r.peso = d.peso || 0;
  r.formato = d.formato || r.formato;
  // Una traccia caduta in mezzo a quarantanove riuscite non merita di fermare
  // tutto con una finestra: la riga e' gia' rossa e resta li' da vedere.
  if (d.esito === 'fail' && d.errore) window.avvisa(r.titolo + ' — ' + d.errore, 'fail');
  disegnaLibreria();
  if (LIB.scelta === r) disegnaScelto();
}

/* ── Avvio ─────────────────────────────────────────────────────────────── */

async function caricaLibreria() {
  let esito;
  try { esito = await window.pywebview.api.libreria(); } catch (_) { return; }
  if (!esito || !esito.ok) return;
  LIB.libero = esito.libero || 0;
  const gia = (esito.brani || []).map((b) => nuovaRiga({
    ...b, stato: 'fatto', spuntata: false, passato: true }));
  LIB.righe = LIB.righe.concat(gia);
  disegnaLibreria();
}

function initAudio() {
  L$('a-scarica').addEventListener('click', analizzaAudio);
  L$('a-link').addEventListener('keydown', (e) => { if (e.key === 'Enter') analizzaAudio(); });
  L$('a-avvia').addEventListener('click', scaricaCoda);

  L$('a-linguette').querySelectorAll('button').forEach((b) =>
    b.addEventListener('click', () => {
      LIB.linguetta = b.dataset.l;
      L$('a-linguette').querySelectorAll('button').forEach((x) =>
        x.classList.toggle('attiva', x === b));
      disegnaLibreria();
    }));
  L$('a-cerca').addEventListener('input', (e) => { LIB.cerca = e.target.value; disegnaLibreria(); });
  L$('a-filtro').addEventListener('click', () => {
    LIB.soloFatti = !LIB.soloFatti;
    L$('a-filtro').classList.toggle('attivo', LIB.soloFatti);
    disegnaLibreria();
  });
  L$('a-tutti').addEventListener('change', (e) => {
    LIB.righe.filter((r) => r.stato === 'coda').forEach((r) => { r.spuntata = e.target.checked; });
    disegnaLibreria();
  });

  ['a-formato', 'a-metadati'].forEach((id) => L$(id).addEventListener('change', () => {
    aggiornaOpzioni();
    if (LIB.scelta) disegnaScelto();
  }));
  L$('a-cartella').addEventListener('click', async () => {
    const e = await window.pywebview.api.scegli_cartella('audio');
    if (!e.ok) { window.avvisa(e.errore, 'fail'); return; }
    if (e.cartella) { LIB.cartella = e.cartella; nomeCartella(); }
  });
  L$('a-apri-cartella').addEventListener('click', async () => {
    const e = await window.pywebview.api.apri_cartella('audio', LIB.cartella);
    if (!e.ok) window.avvisa(e.errore, 'fail');
  });

  collegaLettore();
  disegnaLibreria();
  disegnaScelto();

  window.registraSezione('audio', {
    scorciatoia: analizzaAudio,
    // La libreria e il lettore restano: sono la schermata di Audio, non il
    // risultato di un'operazione. Se ne va il link e il brano aperto.
    azzera: () => {
      L$('a-link').value = '';
      // Quello che e' arrivato va in archivio; code e fallimenti se ne vanno.
      LIB.righe = LIB.righe.filter((r) => r.passato || r.stato === 'fatto' || r === LIB.suona);
      LIB.righe.forEach((r) => { if (r.stato === 'fatto') { r.passato = true; r.indice = null; } });
      LIB.linguetta = 'tutti';
      L$('a-linguette').querySelectorAll('button').forEach((x) =>
        x.classList.toggle('attiva', x.dataset.l === 'tutti'));
      if (LIB.scelta) scegli(null);
      disegnaLibreria();
    },
    // A lavoro finito il nucleo riaccende tutti i bottoni: questo torna a
    // dipendere da quante righe aspettano.
    riabilita: () => {
      // Un lavoro caduto prima di arrivare ai singoli brani non manda mai la
      // loro fine: senza questo restavano «in scarico» per sempre.
      const ferme = LIB.righe.filter((r) => r.stato === 'lavora');
      ferme.forEach((r) => { r.stato = 'fallito'; aggiornaNodo(r); });
      if (ferme.length) disegnaLibreria();
      contaCoda();
    },
    traduci: () => {
      L$('a-cerca').placeholder = window.t('lib.cerca');
      L$('a-filtro').title = window.t('lib.solo_fatti');
      nomeCartella();
      aggiornaOpzioni();
      disegnaLibreria();
      disegnaScelto();
    },
  });
  caricaLibreria();
}

/* Un link lasciato cadere sulla finestra: il nucleo ha gia' portato qui, a
 * questa sezione tocca riempire il campo e partire. */
window.audioAccettaLink = (testo) => {
  L$('a-link').value = testo;
  analizzaAudio();
};

window.libreria = {
  scelta: arrivaScelta,
  scarica: scaricaBrani,
  fase: tracciaInFase,
  avanza: tracciaAvanti,
  finita: tracciaArrivata,
};
window.initAudio = initAudio;
