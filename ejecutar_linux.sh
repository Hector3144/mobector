#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID == 0 )); then
    printf '%s\n' 'Abre MobHector como usuario normal, sin sudo.' >&2; exit 1
fi
app_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$app_dir"
if [[ ! -x .venv/bin/python ]]; then
    printf '%s\n' 'Primero ejecuta: bash instalar_linux.sh' >&2; exit 1
fi
if [[ -z ${DISPLAY:-} && -z ${WAYLAND_DISPLAY:-} ]]; then
    printf '%s\n' 'MobHector requiere un escritorio gráfico.' >&2; exit 1
fi
exec .venv/bin/python mobhector.pyw "$@"
