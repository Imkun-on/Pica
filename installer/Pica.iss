; Installatore di Pica.
;
; Non si compila a mano: lo chiama costruisci.ps1, che prima costruisce
; dist\Pica\ con PyInstaller e poi passa di qui con la versione giusta.
;
;     .\costruisci.ps1 -Versione 2.0
;
; Cosa fa, in ordine
;   1. controlla se WebView2 c'e' gia'; se no lo scarica (e se il download
;      fallisce va avanti lo stesso: vedi [Code]);
;   2. spazza il vecchio _internal, per non mescolare librerie di due versioni;
;   3. copia dist\Pica\ in %LOCALAPPDATA%\Programs\Pica;
;   4. crea le scorciatoie, installa WebView2 se serviva, e offre di aprire;
;   5. alla disinstallazione chiede prima di cancellare i file prodotti.

; Fino alla 2.0 il programma si chiamava MediaDex (cartella, eseguibile) e
; MediaFlow (quello che si vedeva). L'AppId qui sotto e' rimasto lo stesso,
; quindi chi aggiorna resta nella cartella che aveva - Inno la ricorda - e
; [InstallDelete] toglie l'eseguibile e le scorciatoie col nome vecchio.
#define NomeApp        "Pica"
#define NomeVisibile   "Pica"
#define Autore         "Imkun-on"
#define SitoApp        "https://github.com/Imkun-on/Pica"
#define EseguibileApp  "Pica.exe"
#define Sorgente       "..\dist\Pica"

; La versione arriva da costruisci.ps1 come /DVersione=1.2.0. Il ripiego serve
; solo a chi compila questo file a mano per prova.
#ifndef Versione
  #define Versione     "2.0"
#endif

[Setup]
; Questo GUID identifica Pica per sempre, ed e' quello che permette a una
; versione nuova di riconoscere e sostituire quella vecchia invece di
; installarsi accanto. Non va MAI cambiato, e non va MAI copiato da un altro
; programma: due installatori con lo stesso AppId si disinstallano a vicenda.
AppId={{6779E9EE-5B17-4F90-ACC5-F1949A9874D5}
AppName={#NomeVisibile}
AppVersion={#Versione}
AppVerName={#NomeVisibile} {#Versione}
AppPublisher={#Autore}
AppPublisherURL={#SitoApp}
AppSupportURL={#SitoApp}/issues
AppUpdatesURL={#SitoApp}/releases
VersionInfoVersion={#Versione}

; Installazione per utente, senza UAC.
;
; Non e' una scorciatoia per evitare la finestra dei permessi: e' l'unica
; collocazione in cui Pica funziona. Il programma scrive ACCANTO A SE
; STESSO - risultati\, logs\, Database_Globale\ - e dentro
; "Programmi" un utente normale non ha permesso di scrivere. Installato li',
; il primo download fallirebbe con un errore di permessi che nessuno saprebbe
; interpretare.
;
; Con PrivilegesRequired=lowest, {autopf} si risolve in
; %LOCALAPPDATA%\Programs, che e' di chi installa e dove si puo' scrivere.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#NomeApp}
DefaultGroupName={#NomeVisibile}
; Il gruppo del menu Start si chiamava MediaFlow: senza questa riga Inno
; riuserebbe quello, e le scorciatoie nuove finirebbero sotto il nome vecchio.
UsePreviousGroup=no
DisableProgramGroupPage=yes
DisableDirPage=auto

OutputDir=output
; Senza il numero di versione nel nome, di proposito: cosi' l'indirizzo
; https://github.com/Imkun-on/Pica/releases/latest/download/Pica-Setup.exe
; resta valido per sempre e si puo' mettere nel README senza doverlo
; aggiornare a ogni pubblicazione.
OutputBaseFilename={#NomeVisibile}-Setup

SetupIconFile=..\assets\Pica.ico
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WebView2 esiste da Windows 10 in poi, e BurnDex usa API che prima non c'erano.
MinVersion=10.0

WizardStyle=modern
ShowLanguageDialog=auto
UninstallDisplayIcon={app}\{#EseguibileApp}
UninstallDisplayName={#NomeVisibile} {#Versione}

[Languages]
Name: "italiano"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english";  MessagesFile: "compiler:Default.isl"

[CustomMessages]
italiano.CreaIconaDesktop=Crea un collegamento sul desktop
english.CreaIconaDesktop=Create a desktop shortcut

italiano.ApriRisultati=Apri la cartella dei risultati
english.ApriRisultati=Open the results folder

italiano.AvviaOra=Avvia {#NomeVisibile}
english.AvviaOra=Launch {#NomeVisibile}

italiano.WebView2Titolo=Componente mancante
english.WebView2Titolo=Missing component

italiano.WebView2Testo={#NomeVisibile} disegna la propria interfaccia con WebView2, che su questo computer non risulta installato. Lo scarico da Microsoft: sono pochi megabyte.
english.WebView2Testo={#NomeVisibile} draws its interface with WebView2, which does not appear to be installed on this computer. It will be downloaded from Microsoft: it is a few megabytes.

italiano.WebView2Installo=Installazione di WebView2...
english.WebView2Installo=Installing WebView2...

italiano.WebView2Fallito=Non sono riuscito a scaricare WebView2. L'installazione prosegue: se {#NomeVisibile} non si apre, installa "Microsoft Edge WebView2 Runtime" e riprova.
english.WebView2Fallito=WebView2 could not be downloaded. Setup will continue: if {#NomeVisibile} does not open, install "Microsoft Edge WebView2 Runtime" and try again.

italiano.RimuoviDati=Vuoi cancellare anche i file che hai scaricato e le tue impostazioni?%n%n%1%n%nRispondendo No restano dove sono, e li ritrovi se reinstalli.
english.RimuoviDati=Do you also want to delete the files you downloaded and your settings?%n%n%1%n%nAnswering No leaves them where they are, and you get them back if you reinstall.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreaIconaDesktop}"; \
    GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Via il vecchio _internal PRIMA di copiare il nuovo.
;
; PyInstaller mette li' dentro le librerie con nomi che cambiano da una
; versione all'altra di Python e dei pacchetti. Senza questa riga, aggiornando
; Pica le librerie vecchie resterebbero accanto alle nuove e Python ne
; caricherebbe un misto: guasti che non somigliano a niente e che spariscono
; disinstallando e reinstallando.
;
; Non tocca niente dei dati di chi usa il programma: quelli stanno in {app},
; non in {app}\_internal.
Type: filesandordirs; Name: "{app}\_internal"

; Quello che resta del nome vecchio (vedi in cima): l'eseguibile, il gruppo
; nel menu Start e la scorciatoia sul desktop. I dati non c'entrano.
Type: files; Name: "{app}\MediaDex.exe"
Type: filesandordirs; Name: "{autoprograms}\MediaFlow"
Type: files; Name: "{autodesktop}\MediaFlow.lnk"

[Dirs]
; Creata vuota cosi' la scorciatoia "Apri la cartella dei risultati" e il
; bottone dentro il programma hanno qualcosa da aprire al primo avvio.
Name: "{app}\risultati"

[Files]
; Tutta la cartella prodotta da PyInstaller.
;
; Gli Excludes sono la seconda rete: la prima e' il passo 2 di costruisci.ps1,
; che quei file li cancella. Sono elencati qui lo stesso perche' una rete sola
; su "non spedire i dati personali di chi costruisce" e' poca. La barra
; rovesciata davanti al nome ancora il confronto alla radice della sorgente,
; altrimenti escluderebbe anche eventuali file omonimi piu' in basso.
Source: "{#Sorgente}\*"; DestDir: "{app}"; \
    Excludes: "\risultati,\logs,\Database_Globale"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Le icone puntano al .ico impacchettato dentro _internal e non a quello
; dell'eseguibile: cosi' restano nitide anche alle misure grandi, dove Windows
; altrimenti stira la piu' piccola delle icone incorporate.
Name: "{group}\{#NomeVisibile}"; Filename: "{app}\{#EseguibileApp}"; \
    IconFilename: "{app}\_internal\assets\Pica.ico"
Name: "{group}\{cm:ApriRisultati}"; Filename: "{app}\risultati"
Name: "{autodesktop}\{#NomeVisibile}"; Filename: "{app}\{#EseguibileApp}"; \
    IconFilename: "{app}\_internal\assets\Pica.ico"; Tasks: desktopicon

[Run]
; WebView2 per primo: se manca, Pica si apre su una finestra bianca.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
    StatusMsg: "{cm:WebView2Installo}"; Flags: waituntilterminated; Check: ServeWebView2
Filename: "{app}\{#EseguibileApp}"; Description: "{cm:AvviaOra}"; \
    Flags: nowait postinstall skipifsilent

[Code]
var
  WebView2Assente: Boolean;
  ScaricoRiuscito: Boolean;
  PaginaScarico: TDownloadWizardPage;

{ C'e' gia' WebView2 su questo computer?

  Si guarda la chiave di Evergreen, che e' quella che il runtime scrive quando
  si installa. Va cercata in tre posti: su un Windows a 64 bit
  l'installazione per tutti finisce sotto WOW6432Node, quella per il solo
  utente in HKCU, e ci sono macchine in cui c'e' l'una e non l'altra.

  Una versione vuota o '0.0.0.0' vale come assente: e' quello che resta quando
  il runtime e' stato disinstallato male, e la chiave rimane senza il
  programma dietro. }
function WebView2Installato(): Boolean;
var
  clienti, versione: String;
begin
  clienti := 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result :=
    (RegQueryStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\WOW6432Node\' + clienti, 'pv', versione)
       and (versione <> '') and (versione <> '0.0.0.0')) or
    (RegQueryStringValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\' + clienti, 'pv', versione)
       and (versione <> '') and (versione <> '0.0.0.0')) or
    (RegQueryStringValue(HKEY_CURRENT_USER, 'SOFTWARE\' + clienti, 'pv', versione)
       and (versione <> '') and (versione <> '0.0.0.0'));
end;

function ServeWebView2(): Boolean;
begin
  Result := WebView2Assente and ScaricoRiuscito;
end;

function AvanzamentoScarico(const Url, NomeFile: String; const Progresso, Totale: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  WebView2Assente := not WebView2Installato();
  ScaricoRiuscito := False;
  PaginaScarico := CreateDownloadPage(
    ExpandConstant('{cm:WebView2Titolo}'),
    ExpandConstant('{cm:WebView2Testo}'),
    @AvanzamentoScarico);
end;

{ Lo scaricamento avviene dopo il riepilogo e prima della copia dei file:
  e' l'ultimo momento in cui si puo' ancora annullare tutto senza aver
  toccato niente.

  Un fallimento NON e' fatale, ed e' importante che non lo sia: chi sta
  installando potrebbe essere senza rete, o dietro un proxy aziendale, e
  fermare l'installazione per un componente che magari ha gia' sarebbe
  sproporzionato. Si avvisa e si prosegue. }
function NextButtonClick(IdPaginaCorrente: Integer): Boolean;
begin
  Result := True;
  if (IdPaginaCorrente = wpReady) and WebView2Assente then
  begin
    PaginaScarico.Clear;
    PaginaScarico.Add(
      'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
      'MicrosoftEdgeWebview2Setup.exe', '');
    PaginaScarico.Show;
    try
      try
        PaginaScarico.Download;
        ScaricoRiuscito := True;
      except
        ScaricoRiuscito := False;
        MsgBox(ExpandConstant('{cm:WebView2Fallito}'), mbInformation, MB_OK);
      end;
    finally
      PaginaScarico.Hide;
    end;
  end;
end;

{ Alla disinstallazione si chiede prima di cancellare i dati.

  I brani scaricati sono l'unica cosa di Pica che non si puo' rifare
  premendo un bottone: possono essere ore di download. Cancellarli senza
  chiedere, dentro una disinstallazione che qualcuno sta facendo magari solo
  per reinstallare, sarebbe il danno peggiore che questo programma possa
  fare.

  E quando non c'e' nessuno a cui chiedere, non si cancella.

  In modalita' silenziosa - `unins000.exe /VERYSILENT`, che e' come disinstalla
  uno strumento di distribuzione automatica - una MsgBox non compare affatto:
  Inno risponde al posto tuo con il pulsante predefinito, che per MB_YESNO e'
  «Si'». Il risultato era che una disinstallazione silenziosa portava via la
  musica senza che nessuno l'avesse mai chiesto. L'ho scoperto provando
  l'installatore per davvero e guardando cosa restava: non restava niente.

  Adesso il silenzio vale come «no». Chi vuole cancellare anche i dati ha
  sempre la disinstallazione normale, dove la domanda compare. }
procedure CurUninstallStepChanged(PassoCorrente: TUninstallStep);
var
  cartella: String;
begin
  if PassoCorrente = usPostUninstall then
  begin
    if UninstallSilent then
      Exit;

    cartella := ExpandConstant('{app}');
    if DirExists(cartella) then
      if MsgBox(FmtMessage(ExpandConstant('{cm:RimuoviDati}'), [cartella]),
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(cartella, True, True, True);
  end;
end;
