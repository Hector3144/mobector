# Revisión de MobHector — 29 de septiembre de 2026

## Punto de partida recuperado

El adjunto de esta conversación es **1.2.23 SAVED_PLATON_PROFILES**: perfiles Platón guardados y numerosas correcciones de terminal/SFTP. Se localizó y examinó también **MobHector_1_3_4_FULL_INSTALLER_SHARE.zip**, posterior, con sesiones/carpetas, favoritos, Quick Connect, Startup Command, Compose, búsqueda, transcripciones, MultiExec, zoom, pestañas separables e iconos remotos de Windows. La versión nueva se basa en ese código 1.3.4, no en una reconstrucción incompleta de 1.2.23.

El historial de conversaciones describía trabajo posterior, pero no se tomó como prueba de que esas correcciones estuvieran en el ZIP. Por ejemplo, el código recuperado todavía enviaba teclado en el hilo GUI y no tenía cancelación de transferencias. Se verificaron los archivos efectivos.

## Hallazgos y cambios implementados

| Área | Hallazgo | Cambio 1.4.0 |
| --- | --- | --- |
| Inicio | `currentChanged` podía ejecutarse antes de crear `connection_status` | Conexión de señales después de construir la ventana; fallo reproducido y corregido |
| Teclado | `sendall` en el hilo gráfico podía bloquearlo | Worker dedicado, cola acotada a 2 MiB, envío parcial ordenado y timeout de falta de avance |
| Salida | Señales Qt/xterm podían acumular salida ilimitada | Crédito de salida y ACK al consumir el parser; límite aproximado de 1 MiB más una ráfaga de 512 KiB |
| Ventanas | Mover WebEngine puede dejar la terminal negra aunque conserve el buffer | Refit y redibujado explícito, renovación del atlas de caracteres, comprobación visual tras tres ciclos |
| SFTP | Sin cancelación real | Evento por transferencia, comprobado durante preparación, copia y antes de publicar; botón en la cola |
| Cierre | Salir podía cortar transferencias durante publicación | Espera a cancelación/limpieza antes de cerrar las conexiones |
| Descarga | Lecturas secuenciales y posibilidad de espera indefinida | Prefetch con 32 solicitudes y timeout del canal dedicado de 30 s |
| Nombres | Validación de ruta incompleta para Windows | Rechaza ADS (`:`), dispositivos reservados, controles, caracteres inválidos y terminaciones ambiguas |
| Directorios | Un enlace local existente podía redirigir la descarga | Verificación de confinamiento, rechazo de symlinks/junctions; no sigue enlaces de subida |
| Colisiones | `A` y `a` remotos podían sobrescribirse en Windows | Detección previa de nombres que coinciden sin distinguir mayúsculas |
| Importación | Campos arbitrarios, puertos inválidos y mutación parcial | Validación de todo el lote primero, límites de tamaño/cantidad, deduplicación y nuevos identificadores de credencial |
| Comandos importados | Un Startup Command importado se ejecutaría al conectar | Se descarta al importar y exportar; debe configurarse deliberadamente en la aplicación |
| Pegado | Multilínea/controles podían ejecutar órdenes por accidente | Confirmación cuando procede, límite de 1 MiB y eliminación de controles peligrosos |
| Editor | `errors=replace` podía corromper un archivo; se sobrescribían cambios externos | UTF-8 estricto, preserva BOM/CRLF/CR/LF, rechaza mezcla de finales de línea y comprueba hash previo |
| WebEngine | Navegación no restringida al documento local | Página limitada a `terminal.html`, sin ventanas nuevas; CSP y acceso remoto deshabilitado |
| Persistencia | Dos procesos podían sobrescribir configuración | Archivo de bloqueo de instancia; escritura atómica ya existente conservada |
| Credenciales | Buffer mutable quedaba sin limpiar al escribir | Limpieza del buffer de Credential Manager incluso si falla la API; Python no garantiza borrado de todas las copias de strings |
| Confianza SSH | Persistencia aceptaba nombres con separadores | Validación del identificador antes de serializar known_hosts; TOFU explícito conservado |
| Instalación | Assets descargados sin hash de contenido, dependencias variables | Assets locales con licencias, lock de 11 dependencias Windows con SHA-256 y Python con firma Authenticode válida |
| Actualización | Verificadores antiguos dependían de cadenas y versiones fijas | Verificador de rutas/hashes, copia verificada, respaldo completo previo y rollback probado con fallo inyectado |
| Desinstalación | Borraba toda la carpeta `bin/assets` y comodines | Sólo nombres propios de la aplicación; preserva datos y otros archivos de bin |
| Mantenimiento | Archivos históricos y validadores mezclados con entrega actual | README nuevo, informe, historial en docs/history, módulos separados, pruebas de comportamiento y CI |

## Investigación externa aplicada

- **Paramiko, documentación oficial SFTP:** permite limitar `max_concurrent_prefetch_requests`; explica que solicitudes sin límite pueden provocar esperas. Se configuró `SFTPFile.prefetch` con 32 solicitudes y timeout. https://docs.paramiko.org/en/stable/api/sftp.html
- **Qt, documentación oficial QWebEnginePage:** `acceptNavigationRequest` permite controlar la navegación. Se aplicó una lista permitida de un único documento local. https://doc.qt.io/qt-6/qwebenginepage.html
- **Tabby, reporte comunitario #10685:** usuarios reportan interrupciones SSH durante uploads. Sirvió para priorizar separación de canal y pruebas de transferencia; no demuestra que Paramiko tenga la misma causa. https://github.com/Eugeny/tabby/issues/10685
- **Tabby, discusión #5558:** limitaciones de seguimiento de directorio con tmux. Se conserva el mecanismo OSC7 existente sin prometer seguimiento universal de shells/tmux. https://github.com/Eugeny/tabby/discussions/5558
- **Tabby, incidencias de rendimiento #8972:** reforzó la prioridad de transferencias y progresos; no se copió una solución de otro motor SSH sin verificarla. https://github.com/Eugeny/tabby/issues/8972
- **Python/PyPI/npm oficiales:** se verificó disponibilidad del instalador Python 3.13.14 x64, resolución de wheels de Windows y se recuperaron xterm 5.3.0 / fit 0.8.0 con sus licencias. El bootstrap verifica la firma del instalador al ejecutarse en Windows.

No se usaron foros como autoridad para cambiar algoritmos criptográficos o desactivar verificaciones SSH. No se actualizó xterm a una versión mayor sin una migración de sus numerosas integraciones personalizadas.

## Evidencias de validación

- **20 pruebas de comportamiento:** claves de host, nombres peligrosos, importación atómica, límites, cancelación, conservación del destino, confinamiento, colisiones, editor UTF-8, cola de teclado/envíos parciales y rollback.
- **SSH/SFTP real por loopback:** servidor Paramiko temporal, clave de prueba, transferencia de un archivo aleatorio de más de 2 MiB y un archivo vacío, descarga recursiva, comparación byte a byte y canal de navegación aún abierto.
- **GUI real Qt/WebEngine:** arranque, xterm/QWebChannel, 18.000 líneas con UTF-8, ACK, teclado, tres movimientos entre ventanas manteniendo canal/reader/buffer y cierre limpio. Se inspeccionó la captura; faltan fuentes emoji en este Linux, pero el texto UTF-8 no se pierde.
- **Auditoría principal:** 93 PASS, 0 WARN, 0 FAIL. Es una mezcla de pruebas de comportamiento y comprobaciones estáticas; no equivale a 93 escenarios manuales.
- **36 validadores históricos:** preservan comprobaciones de Vim, pegado, historial, zoom, productividad, Platón e iconos. Se actualizaron comprobaciones de versión y se sustituyeron aserciones textuales del viejo actualizador por pruebas reales de rollback. No se simula que se esté ejecutando una versión antigua para pasar las pruebas.
- **Análisis de código:** sintaxis Python y comprobación de nombres no definidos; parser de PowerShell sin errores en los tres scripts. Parsear no equivale a ejecutar en Windows.
- **Integridad del paquete:** manifest, ausencia de config/known_hosts/claves privadas, ZIP sin bytecode ni cachés, checksum externo.

Logs de resultados y captura se incluyen en `docs/qa/`. No contienen sesiones reales del usuario.

## Límites y trabajo pendiente concreto

1. No se ejecutó Windows: pendiente probar instalación nueva, actualización desde tu versión instalada, ConPTY, Credential Manager, teclas/rueda reales y políticas corporativas. El workflow Windows está preparado, no se presenta como ya ejecutado.
2. Sin acceso a Ruster/Platón: no se validaron túneles, `su`, autenticación temporal, sudo ni los servidores corporativos reales. Se conservaron las rutas funcionales de 1.3.4.
3. El núcleo gráfico sigue siendo grande; se extrajeron componentes críticos, pero no se reescribieron 15.000 líneas de interfaz sin pruebas suficientes.
4. La cancelación es cooperativa y puede esperar una operación SFTP bloqueada hasta el timeout. Si se pierde la red durante la limpieza puede quedar un `.mobhector-part-*` remoto. Los archivos ya publicados no se deshacen al cancelar una carpeta.
5. La comparación del editor detecta cambios anteriores a guardar; SFTP no ofrece compare-and-swap universal, por lo que existe una ventana de carrera si otro proceso escribe exactamente durante el guardado.
6. Validación de rutas impide enlaces ya presentes; no es defensa contra un atacante local con el mismo usuario que reemplace directorios concurrentemente. El equipo local debe ser confiable.
7. No se implementó reanudación automática de archivos parciales: sin verificar identidad/contenido del origen podría mezclar datos. Tampoco se añadieron RDP, X11, serial, gestor de paquetes o plugins arbitrarios.
8. No hay certificado de firma de MobHector ni auditoría externa. Se conservaron algoritmos seguros de Paramiko y la confirmación de claves; no se afirma seguridad absoluta.
9. Repositorio GitHub: código, `.gitignore`, documentación y CI preparados. La publicación remota requiere una sesión autenticada con capacidad de crear repositorios; no debe confundirse con el Git local.
