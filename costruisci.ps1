<#
    Costruisce Pica-Setup.exe, dall'inizio alla fine.

        .\costruisci.ps1
        .\costruisci.ps1 -Versione 1.2.0
        .\costruisci.ps1 -SoloInstallatore      (riusa dist\, salta PyInstaller)
        .\costruisci.ps1 -Forza                 (nessuna domanda: per la CI)

    I due passaggi, e perche' sono due
        PyInstaller trasforma il programma in una cartella che si puo' eseguire
        senza avere Python. Inno Setup prende quella cartella e ne fa un
        installatore: un .exe solo, che mette le cose al loro posto, crea le
        scorciatoie, si registra in "Installazione applicazioni" e sa
        disinstallarsi.

        Sono due strumenti diversi perche' risolvono due problemi diversi, e
        nessuno dei due sa fare il lavoro dell'altro.

    Cosa serve, una volta sola
        winget install JRSoftware.InnoSetup
        winget install Gyan.FFmpeg          (facoltativo: vedi il passo 0)

    Niente ambiente virtuale
        Si usa il python che si trova. E' una scelta: chi costruisce lo fa
        dalla stessa macchina su cui sviluppa, e un venv qui dentro vorrebbe
        dire installare una seconda volta ottanta megabyte di dipendenze che
        sono gia' li'.
#>

[CmdletBinding()]
param(
    [string] $Versione = '2.0',
    [switch] $SoloInstallatore,
    [switch] $Forza
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Radice = $PSScriptRoot
$Dist   = Join-Path $Radice 'dist\Pica'
$Spec   = Join-Path $Radice 'Pica.spec'
$Iss    = Join-Path $Radice 'installer\Pica.iss'
$Uscita = Join-Path $Radice 'installer\output'

function Titolo($t)  { Write-Host "`n$t" -ForegroundColor Cyan }
function Nota($t)    { Write-Host "    $t" -ForegroundColor DarkGray }
function Allarme($t) { Write-Host "    $t" -ForegroundColor Yellow }

# ── Passo 0: c'e' tutto quello che serve? ────────────────────────────────────

Titolo 'Passo 0/4  Controlli'

if (-not (Test-Path $Spec)) { throw "Manca $Spec" }
if (-not (Test-Path $Iss))  { throw "Manca $Iss" }

# FFmpeg non viene impacchettato (vedi il commento in Pica.spec), quindi la
# sua assenza qui non impedisce di costruire niente: si avvisa e si tira
# dritto. Serve pero' a chi costruisce, per provare il risultato.
if ($null -eq (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Allarme 'ffmpeg non e'' nel PATH: il pacchetto si costruisce lo stesso,'
    Allarme 'ma non potrai provarlo. Installalo con: winget install Gyan.FFmpeg'
}

# ISCC.exe, il compilatore di Inno Setup. Si guarda nei quattro posti in cui
# puo' stare: nel PATH, e nelle tre cartelle in cui l'installatore di Inno lo
# mette a seconda che sia stato installato per tutti o per un utente solo.
$Iscc = $null
foreach ($candidato in @(
    'iscc',
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)) {
    $trovato = Get-Command $candidato -ErrorAction SilentlyContinue
    if ($null -ne $trovato) { $Iscc = $trovato.Source; break }
}
if ($null -eq $Iscc) {
    throw @'
ISCC.exe non trovato: senza Inno Setup non si puo' fare l'installatore.

    winget install JRSoftware.InnoSetup

Poi riapri il terminale e rilancia questo script.
'@
}
Nota "Inno Setup: $Iscc"
Nota "Versione da costruire: $Versione"

# ── Passo 1: PyInstaller ─────────────────────────────────────────────────────

Titolo 'Passo 1/4  PyInstaller'

if ($SoloInstallatore) {
    Nota 'Saltato: si riusa quello che c''e'' in dist\'
    if (-not (Test-Path $Dist)) { throw "Non c''e'' niente da riusare: $Dist non esiste." }
}
else {
    # Si invoca come MODULO e non con il comando 'pyinstaller': pip mette
    # quello shim dentro una cartella Scripts\ che spesso non e' nel PATH, e
    # cercarlo li' porterebbe a reinstallare PyInstaller a ogni costruzione
    # credendo che manchi.
    python -m PyInstaller --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Nota 'PyInstaller non trovato, lo installo...'
        python -m pip install --upgrade pyinstaller
        if ($LASTEXITCODE -ne 0) { throw 'Installazione di PyInstaller fallita.' }
    }

    python -m PyInstaller $Spec --noconfirm `
        --distpath (Join-Path $Radice 'dist') `
        --workpath (Join-Path $Radice 'build')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller ha fallito.' }

    $esebuilt = Join-Path $Dist 'Pica.exe'
    if (-not (Test-Path $esebuilt)) { throw "PyInstaller e'' andato a buon fine ma $esebuilt non c''e''." }
}

# ── Passo 2: togliere i propri dati da dist\ ─────────────────────────────────

Titolo 'Passo 2/4  Pulizia di dist\'

# Pica scrive accanto a se stesso. Chi costruisce, di solito, ha appena
# provato l'eseguibile dalla cartella dist\: e li' dentro sono rimasti i suoi
# brani scaricati, i suoi log, il suo database. Inno li spedirebbe dentro
# l'installatore senza chiedere niente a nessuno.
$Intrusi = @('risultati', 'logs', 'Database_Globale')
$Trovati = @()
foreach ($nome in $Intrusi) {
    $p = Join-Path $Dist $nome
    if (Test-Path $p) { $Trovati += $p }
}

if ($Trovati.Count -eq 0) {
    Nota 'Niente di personale qui dentro.'
}
else {
    Allarme 'In dist\ ci sono dei tuoi dati:'
    foreach ($p in $Trovati) { Allarme "  $(Split-Path $p -Leaf)" }
    $risposta = if ($Forza) { 's' } else { Read-Host '    Cancellarli? [S/n]' }
    if ($risposta -eq '' -or $risposta -match '^[sSyY]') {
        foreach ($p in $Trovati) { Remove-Item $p -Recurse -Force }
        Nota 'Fatto.'
    }
    else {
        throw 'Interrotto: con quei file dentro, l''installatore spedirebbe i tuoi dati.'
    }
}

# ── Passo 3: Inno Setup ──────────────────────────────────────────────────────

Titolo 'Passo 3/4  Inno Setup'

# La versione entra come define da riga di comando: e' l'unico posto in cui va
# scritta, e da li' finisce nel nome visualizzato, nelle proprieta' del file e
# in "Installazione applicazioni".
& $Iscc "/DVersione=$Versione" $Iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup ha fallito.' }

# ── Passo 4: il risultato ────────────────────────────────────────────────────

Titolo 'Passo 4/4  Fatto'

$Prodotto = Join-Path $Uscita 'Pica-Setup.exe'
if (-not (Test-Path $Prodotto)) { throw "Inno Setup e'' andato a buon fine ma $Prodotto non c''e''." }

$mb     = [math]::Round((Get-Item $Prodotto).Length / 1MB, 1)
$impronta = (Get-FileHash $Prodotto -Algorithm SHA256).Hash

Write-Host ''
Write-Host "    $Prodotto" -ForegroundColor Green
Write-Host "    $mb MB"
Write-Host "    SHA256  $impronta"
Write-Host ''
# Le virgolette doppie, non il +. Chiamando una funzione, PowerShell legge
# `Nota 'a' + $b + 'c'` come TRE argomenti posizionali invece che come una
# concatenazione: arrivava solo il primo, e la riga stampata finiva con
# "git tag v" senza il numero.
Nota "Per pubblicarlo:  git tag v$Versione  &&  git push --tags"
