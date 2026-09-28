# Transición propuesta; no ejecutada

El usuario pidió autorización previa a la recreación necesaria para añadir persistencia. No es posible incorporar un montaje al contenedor ya creado con su configuración actual. El plan conserva ese contenedor y sus datos; no incluye `docker rm`, `prune`, eliminación de volúmenes ni eliminación de colecciones.

## Recursos exactos

- Original: `amazing_wilbur`, ID `901710a1e47b5c390f53f2394057b7c3f234f9171f156758463cbd8c9a1a60b5`.
- Imagen existente: `sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` (Qdrant 1.19.1).
- Nuevo contenedor: `auditoria-qdrant-persistente`.
- Named volume nuevo: `auditoria_qdrant_data_v1` → `/qdrant/storage`.
- API: `127.0.0.1:6333` → puerto 6333 del contenedor; ya no expuesto a todas las interfaces.
- Respaldo montado de solo lectura en `/restore`.
- Colección restaurada con el mismo nombre `auditoria_iso_ley`; la colección V2 se creará en otra fase.

La transición interrumpe brevemente el servicio. No debe haber otros procesos escribiendo ni ejecutarse `rag_auditor.py` durante ella: el script antiguo borra la colección. Si cambió cualquier ID, payload o vector desde el respaldo, el procedimiento se detiene antes de parar el servicio y exige un respaldo actualizado. También se detiene si aparecieron más colecciones o aliases.

## Comandos que ejecutará el script después de la aprobación

El script `persistencia_pendiente.ps1` contiene precondiciones y verificaciones. Estas son las operaciones de infraestructura que realizará, con sus valores actuales:

```powershell
$backup = 'C:\Users\jhast\Documents\Codex\2026-09-28\files-mentioned-by-the-user-requirements\outputs\fase0_1\backup-20260928T211750Z'
docker volume create auditoria_qdrant_data_v1
docker stop amazing_wilbur
docker run -d --name auditoria-qdrant-persistente --restart unless-stopped --publish 127.0.0.1:6333:6333 --mount type=volume,source=auditoria_qdrant_data_v1,target=/qdrant/storage --mount "type=bind,source=$backup,target=/restore,readonly" sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10
```

Luego restaurará el snapshot **en el nuevo servidor** mediante esta petición local:

```powershell
$body = @{
  location = 'file:///restore/auditoria_iso_ley-465272179526703-2026-09-28-21-17-51.snapshot'
  priority = 'snapshot'
  checksum = 'b98a8a7299fa514cf114d22a293386f6998cfc9b5ba3e93a0a2044d0ec84abec'
} | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:6333/collections/auditoria_iso_ley/snapshots/recover?wait=true' -Method Put -ContentType application/json -Body $body -TimeoutSec 120
```

Se comprobarán configuración vectorial, IDs, payloads y vectores contra el export. Después:

```powershell
docker restart auditoria-qdrant-persistente
```

Se repetirá la misma comparación tras el reinicio. Esto probará restauración y conservación de datos al reiniciar. No se usa `--snapshot` como comando permanente del contenedor, porque un intento de restauración repetido sobre una colección existente puede impedir el siguiente arranque.

La llamada integral, **solo después de autorizarla**, será:

```powershell
& 'C:\Users\jhast\Documents\Codex\2026-09-28\files-mentioned-by-the-user-requirements\outputs\fase0_1\persistencia_pendiente.ps1' -AutorizadoPorUsuario
```

## Reversión

Ante fallo posterior a la detención del original, el script conserva los recursos nuevos para diagnóstico y reactiva el servicio original:

```powershell
docker stop auditoria-qdrant-persistente
docker start amazing_wilbur
```

No borra nada. La reversión reexpone la configuración original de puertos. Su éxito también debe comprobarse antes de informar servicio restaurado. Si el equipo se apaga a mitad del procedimiento, estas instrucciones permiten recuperar el contenedor anterior manualmente.

## Comprobado y pendiente

Comprobado: snapshot, tamaño, SHA-256 de servidor, lectura del tar, 249 vectores exportados, igualdad con el servidor actual y sintaxis PowerShell del script. El rechazo por falta de autorización también fue probado.

Pendiente: crear volumen y contenedor, restaurar, probar arranque/reinicio persistente y observar rollback real si resultara necesario. No se afirma que estas operaciones ya hayan pasado una prueba de integración.
