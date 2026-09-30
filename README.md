# MobHector 1.4.1

Cliente SSH/SFTP para Windows de Hector Perez (SGNaomi). Terminal xterm.js, sesiones guardadas, Platón, credenciales de Windows, SFTP, MultiExec, macros, búsqueda, temas y ventanas separables.

## Instalar o actualizar

1. Extrae **todo** el ZIP en una carpeta nueva, fuera de `%USERPROFILE%\bin`.
2. Cierra MobHector.
3. Ejecuta **instalar_o_actualizar.bat**. Detecta si corresponde instalar o actualizar.
4. Abre el acceso directo o ejecuta `mobhector` en una consola nueva.

Instalación nueva: Windows 10/11 x64 y acceso HTTPS a Python.org/PyPI. Instala Python 3.13.14 privado y dependencias con hashes; no necesitas instalar Python manualmente. El ZIP incluye xterm.js; no es un ejecutable autónomo ni un instalador completamente sin conexión.

Actualización: reutiliza el runtime existente, valida archivos y dependencias importables, respalda y revierte la copia si falla la validación. No actualiza automáticamente el runtime anterior. No reemplaza `%APPDATA%\MobHector\config.json`, `known_hosts` ni Windows Credential Manager.

El lanzador de PowerShell solicita `Bypass` únicamente para su proceso, como los paquetes anteriores; no cambia la política permanente. No intenta anular una política de dominio, AppLocker o WDAC. En equipos administrados usa el procedimiento autorizado por tu organización.

## Colores de terminal (1.4.1)

En Apariencia → Sólo la terminal elige **Moba clásico · colores y resaltado** o **Moba clásico · sólo colores ANSI**. El primero resalta estados, IPv4 y rutas sobre texto sin color. Conserva los colores explícitos del servidor y se desactiva en la pantalla alternativa de Vim/top. No modifica comandos, archivos remotos ni texto copiado.

Se activa una sola vez al actualizar una terminal oscura predeterminada. Los otros temas se conservan. Es una aproximación al estilo clásico; MobaXterm permite personalizar su paleta y sus reglas. Las reglas actúan sobre filas visibles, con un máximo de 300 resaltados; no son un diagnóstico del estado real del servidor.

## Qué cambia

- Escritura SSH fuera del hilo gráfico, con cola limitada y gestión de envíos parciales.
- Control de flujo entre SSH, Qt y xterm para contener salida masiva.
- Cancelar una transferencia desde **Ver cola → Cancelar seleccionada**; publicación por archivo y limpieza de temporales.
- Descargas con 32 lecturas anticipadas como máximo y timeout de canal de 30 segundos.
- Rechazo de rutas peligrosas, nombres reservados/ADS de Windows, enlaces locales y colisiones por mayúsculas.
- Importación de sesiones validada antes de modificar la configuración; omite duplicados, credenciales y comandos de inicio.
- Aviso antes de pegados multilínea sin bracketed paste; límite de 1 MiB y filtrado de controles.
- Editor UTF-8 sin sustitución silenciosa de caracteres, conserva BOM/saltos de línea y comprueba cambios externos antes de guardar.
- Corrección de inicialización de la barra de estado y redibujado de terminal al moverla entre ventanas.
- Navegación del WebEngine limitada al documento de terminal y política CSP sin conexiones de red.
- Bloqueo de una segunda instancia para proteger la configuración.
- Instalación con dependencias fijas y hashes; firma del instalador de Python; actualización con rollback verificado.
- Desinstalación limitada a archivos de la aplicación, sin borrar toda la carpeta `bin/assets`.

## Validación y límites

La revisión se ejecutó en Linux con Qt/WebEngine real y SSH/SFTP Paramiko por loopback. Incluye pruebas de cancelación, rutas, claves de host, integridad, rollback, teclado y terminal con 18.000 líneas. Ver [informe](docs/REVISION_1.4.0.md).

No se ha ejecutado el instalador final en Windows ni conectado a tu Ruster/Platón real desde este entorno. ConPTY, el almacén de credenciales y el flujo de acceso corporativo requieren validación en tu Windows. No se afirma ausencia total de vulnerabilidades ni paridad completa con MobaXterm.

## Desarrollo

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python qa_mobhector.py --source
python tools/smoke_gui.py
python tools/build_release.py
```

`requirements-windows.lock` es específico de Windows x64 / CPython 3.13. El archivo `requirements.txt` sirve para desarrollo multiplataforma. El uso diario de la aplicación sigue orientado a Windows.

GitHub Actions contiene pruebas en Windows/Linux y generación del ZIP. Su configuración está preparada; los resultados locales no prueban que el workflow ya se haya ejecutado en GitHub.

## Código y licencias

La autoría original del proyecto se conserva. No se añade una licencia de publicación al código propio sin decisión del autor. xterm.js y fit incluyen su licencia MIT en `assets/`. PySide6, Qt, Paramiko y dependencias mantienen sus propias licencias; el instalador descarga sus distribuciones oficiales. Inventario en `docs/DEPENDENCIES.json`.
