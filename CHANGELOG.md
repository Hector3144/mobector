## 1.5.1 — X11 integrado

- ZIP con VcXsrv x64 y dependencias; instalación y actualización copian el servidor automáticamente.
- Detección del servidor integrado y directorio de trabajo propio.
- Builder verifica el instalador original con SHA256; package de CI incluye X11.
- Prueba de apertura real en Windows pendiente.

# Cambios

## 1.5.0 — 2026-09-30

- Reenvío X11 autenticado por sesión SSH estándar.
- Integración con VcXsrv instalado en Windows y Xauthority/display existentes en Linux.
- Cookies SSH temporales verificadas antes de conectar al servidor X local; cierre al desconectar.
- Sesiones importadas mantienen X11 desactivado.

## 1.4.1 — 2026-09-30

- Paleta Moba clásico sobre negro, con 16 colores ANSI y variante sin resaltado.
- Resaltado visual de estados, IPv4 válidas y rutas; respeta colores del servidor y pantalla alternativa.
- Activación única en terminal oscura predeterminada; cambio reversible en Apariencia.

## 1.4.0 — 2026-09-29

Base recuperada: instalador compartible 1.3.4.

- Terminal: envío asíncrono ordenado, cola limitada, control de flujo de salida y redibujado al cambiar de ventana.
- UI: corregido error de inicialización del estado de conexión.
- SFTP: cancelación cooperativa, timeout, prefetch limitado, validación Windows y confinamiento de descargas.
- Sesiones: importación validada y atómica, sin credenciales/comandos de inicio, deduplicación.
- Editor: UTF-8 estricto, preservación de BOM y finales de línea, detección de cambios externos.
- Seguridad: confirmación de pegados sensibles, página terminal restringida, CSP y bloqueo de instancias simultáneas.
- Instalación: dependencias Windows con hashes, firma de Python, xterm local, actualización verificada y rollback.
- Desinstalación: evita borrar archivos ajenos de la carpeta bin.
- QA: pruebas de comportamiento, integración SSH/SFTP real local, smoke gráfico y CI Windows/Linux.

Los resultados y límites están en docs/REVISION_1.4.0.md. Las notas históricas originales están en docs/history.
