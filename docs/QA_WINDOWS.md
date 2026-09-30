# Comprobación pendiente en Windows

Estas comprobaciones requieren un Windows real. No se marcan como aprobadas por pruebas Linux.

1. En un usuario de prueba, ejecutar `instalar_o_actualizar.bat`. Confirmar Python privado, dependencias, acceso directo y ausencia de sesiones preconfiguradas.
2. En instalación existente cerrada, actualizar y verificar conservación de sesiones y huellas. Revisar el respaldo indicado si la validación falla.
3. Abrir una sesión de prueba con clave y otra con contraseña; comprobar almacenamiento/lectura en Windows Credential Manager y rechazo de una clave de host cambiada.
4. Conectar a Platón con código temporal, abrir el perfil guardado y confirmar el usuario/ruta remotos previstos.
5. Abrir PowerShell/CMD local ConPTY; probar Ctrl+C, pegado, Vim remoto, wheel/zoom y tres ciclos separar/reunir.
6. Subir/bajar un archivo grande; cancelar durante copia. Confirmar que el archivo anterior sigue intacto y la navegación sigue disponible.
7. Repetir una desconexión de red deliberada sólo en servidor de prueba; verificar reconexión y estado de transferencias.
8. Probar editor con UTF-8 BOM/CRLF y cambio externo: no debe sobreescribir silenciosamente una edición detectada.

No pruebes órdenes destructivas ni fallos de red en producción. Para reportar un problema basta versión, acción, error anonimizado y captura sin credenciales.
