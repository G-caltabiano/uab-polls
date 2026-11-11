# Portabilitat i migració

L'aplicació no depèn de Pomodoro. El codi, la base SQLite i els fitxers de
desplegament estan separats.

## Elements que cal moure

1. El repositori de l'aplicació.
2. El directori persistent `data/` (especialment `uab_polls.sqlite3`).
3. La configuració d'entorn del servidor, sense publicar secrets.

## Desplegament Docker

```bash
cp .env.example .env
# Ajusta UAB_POLLS_ROOT_PATH i el proveïdor de correu.
docker compose up -d --build
```

El proxy invers del servidor nou ha d'enviar el prefix públic al port local
`8096`. La base de dades queda al volum `./data`.

## Còpia de seguretat consistent

```bash
sqlite3 data/uab_polls.sqlite3 ".backup 'uab_polls_backup.sqlite3'"
```

## Correu

- A Pomodoro s'utilitza `gog` amb l'OAuth de `fridaygc.bot@gmail.com`.
- En un altre servidor es pot instal·lar/configurar `gog`, o canviar
  `UAB_POLLS_EMAIL_PROVIDER=smtp` i utilitzar un relay SMTP autoritzat.
- Les credencials mai formen part del repositori.

