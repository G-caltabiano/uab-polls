# Disponibilitat · Medicina UAB

Aplicació web en català per crear enquestes de disponibilitat tipus Doodle.

## Funcions

- Calendari setmanal amb durades de 30, 60 o 90 minuts.
- Enllaç públic per enquesta.
- Respostes `sí`, `potser` o `no` amb nom i correu.
- Resultats visibles per nom; el correu només és visible per als administradors.
- Tauler d'administració, tancament/reobertura, eliminació segura de les enquestes
  tancades i classificació de les millors opcions.
- Exportació Excel amb matriu i resum.
- Comptes administradors addicionals mitjançant invitacions d'un sol ús.
- Registre de notificacions per correu.

## Primera entrada

Obre `/horario/enquestes/admin/setup`. Mentre no hi hagi cap administrador, només es pot
crear el compte `gianluigi.caltabiano@uab.cat`. La contrasenya es defineix al
formulari i mai no s'escriu als fitxers de desplegament.

## Correu

En el servidor Pomodoro, l'app usa per defecte l'OAuth Gmail ja configurat amb
`gog`: il mittente è `fridaygc.bot@gmail.com` e ogni amministratore attivo
riceve una mail con le disponibilità inviate e il link ai risultati.

Per un altro server è disponibile anche SMTP tramite queste variabili:

Les notificacions s'envien quan es configuren aquestes variables d'entorn:

- `UAB_POLLS_SMTP_HOST`
- `UAB_POLLS_SMTP_PORT` (per defecte: `587`)
- `UAB_POLLS_SMTP_USERNAME`
- `UAB_POLLS_SMTP_PASSWORD`
- `UAB_POLLS_SMTP_FROM`
- `UAB_POLLS_SMTP_STARTTLS` (per defecte: `true`)

Les credencials no s'han d'afegir al repositori. Consulta
[`docs/PORTABILITY.md`](docs/PORTABILITY.md) per moure l'aplicació.

## Verificació

```bash
PYTHONPATH=/home/gian/UAB-Polls .venv/bin/pytest -q
curl http://127.0.0.1:8096/health
```
