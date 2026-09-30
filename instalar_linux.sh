#!/usr/bin/env bash
# MobHector: preparación y arranque para Ubuntu/Debian y CentOS Stream 9 con escritorio.
set -Eeuo pipefail
trap 'printf "\nError en la línea %s. No se han borrado sesiones ni configuraciones.\n" "$LINENO" >&2' ERR

launch=1
system_packages=1
for arg in "$@"; do
    case "$arg" in
        --no-launch) launch=0 ;;
        --skip-system) system_packages=0 ;;
        -h|--help)
            printf '%s\n' 'Uso: bash instalar_linux.sh [--no-launch] [--skip-system]' \
                'Instala dependencias con apt/dnf y Python en un entorno virtual; después abre MobHector.' \
                '--no-launch: prepara la instalación sin abrir la ventana.' \
                '--skip-system: omite apt/dnf si las bibliotecas del sistema ya están instaladas.' \
                'Ejecutar como usuario normal. sudo se usa únicamente para apt/dnf.'
            exit 0 ;;
        *) printf 'Opción desconocida: %s\n' "$arg" >&2; exit 2 ;;
    esac
done
if (( EUID == 0 )); then
    printf '%s\n' 'Ejecuta este script con tu usuario normal, sin sudo.' >&2
    exit 1
fi
if [[ $(uname -s) != Linux ]]; then
    printf '%s\n' 'Este instalador requiere Linux.' >&2; exit 1
fi
if (( system_packages )); then
    if [[ ! -r /etc/os-release ]]; then
        printf '%s\n' 'No se pudo identificar la distribución.' >&2; exit 1
    fi
    . /etc/os-release
    command -v sudo >/dev/null || { printf '%s\n' 'Se requiere sudo para instalar paquetes.' >&2; exit 1; }
    printf '%s\n' 'Instalando dependencias del sistema (sudo puede solicitar tu contraseña)...'
    case "${ID:-}" in
        ubuntu|debian)
            sudo apt-get update
            audio_package=libasound2
            if apt-cache show libasound2t64 >/dev/null 2>&1; then audio_package=libasound2t64; fi
            sudo apt-get install -y git ca-certificates python3 python3-venv \
                libegl1 libopengl0 libnss3 "$audio_package" libxtst6 libxkbfile1 \
                libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
                libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0
            ;;
        centos|rhel|rocky|almalinux|ol)
            if [[ ${VERSION_ID%%.*} != 9 ]]; then
                printf '%s\n' 'Esta rama admite CentOS Stream / Enterprise Linux 9. No modifica otras versiones.' >&2; exit 1
            fi
            # Python paralelo: nunca cambiar /usr/bin/python3 ni el Python de dnf.
            sudo dnf install -y git ca-certificates python3.11 python3.11-pip \
                mesa-libEGL mesa-libGL libglvnd-opengl nss alsa-lib libXtst \
                libxkbfile libxkbcommon-x11 libxcb xcb-util-cursor xcb-util-wm \
                xcb-util-image xcb-util-keysyms xcb-util-renderutil fontconfig \
                dejavu-sans-fonts
            ;;
        *) printf '%s\n' 'Instalación automática disponible para Ubuntu/Debian y CentOS/Enterprise Linux 9.' \
             'Con las dependencias instaladas puedes usar --skip-system.' >&2; exit 1 ;;
    esac
fi
python_bin=''
for candidate in python3.11 python3.12 python3; do
    if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,15) else 1)' 2>/dev/null; then
        python_bin=$(command -v "$candidate")
        break
    fi
done
if [[ -z $python_bin ]]; then
    printf '%s\n' 'Falta Python compatible (3.10–3.14). En CentOS Stream 9 instala python3.11 y python3.11-pip.' >&2; exit 1
fi
printf 'Python de MobHector: %s\n' "$python_bin"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f "$script_dir/mobhector.pyw" && -f "$script_dir/requirements.txt" ]]; then
    app_dir=$script_dir
else
    app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/MobHector/source"
    if [[ ! -e "$app_dir" ]]; then
        command -v git >/dev/null || { printf '%s\n' 'Falta git para descargar MobHector.' >&2; exit 1; }
        mkdir -p -- "$(dirname -- "$app_dir")"
        git clone --depth 1 -- https://github.com/Hector3144/mobector.git "$app_dir"
    elif [[ ! -f "$app_dir/mobhector.pyw" || ! -f "$app_dir/requirements.txt" ]]; then
        printf 'La ruta ya existe y no contiene MobHector: %s\n' "$app_dir" >&2; exit 1
    fi
fi
cd -- "$app_dir"
if [[ -e .venv ]]; then
    if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,15) else 1)' 2>/dev/null; then
        backup=".venv.backup.$(date +%Y%m%d%H%M%S).$$"
        mv -- .venv "$backup"
        printf 'Entorno anterior conservado en: %s/%s\n' "$app_dir" "$backup"
    fi
fi
if [[ ! -e .venv ]]; then "$python_bin" -m venv .venv; fi
if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'El entorno .venv existente no es válido para Linux; utiliza una carpeta nueva.' >&2; exit 1
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'from PySide6.QtWidgets import QApplication; from PySide6.QtWebEngineWidgets import QWebEngineView; import paramiko'
printf '\nMobHector preparado en: %s\n' "$app_dir"
printf 'Para volver a abrirlo: bash %q\n' "$app_dir/ejecutar_linux.sh"
printf '%s\n' 'Linux: SSH/SFTP disponibles; consola local Windows y guardado de contraseñas Windows no disponibles.'
if (( launch )); then
    if [[ -z ${DISPLAY:-} && -z ${WAYLAND_DISPLAY:-} ]]; then
        printf '%s\n' 'No se detectó un escritorio gráfico. Instalación preparada; ábrelo desde una sesión de escritorio.'
        exit 0
    fi
    exec .venv/bin/python mobhector.pyw
fi
