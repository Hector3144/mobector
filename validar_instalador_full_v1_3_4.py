from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
ps = (ROOT / 'instalar_mobhector.ps1').read_text(encoding='utf-8-sig')
bat = (ROOT / 'instalar_mobhector.bat').read_text(encoding='utf-8-sig')
un = (ROOT / 'desinstalar_mobhector.ps1').read_text(encoding='utf-8-sig')

checks = {
    'version': '$AppVersion = "1.5.0"' in ps,
    'private_runtime': 'MobHectorRuntime' in ps and 'Python' in ps,
    'per_user_python': 'InstallAllUsers=0' in ps,
    'no_system_path_python': 'PrependPath=0' in ps and 'AppendPath=0' in ps,
    'pip_requirements': '-m pip install' in ps and 'requirements.txt' in ps,
    'pyside_paramiko_qa': 'import paramiko, PySide6' in ps,
    'xterm_bundled': all((ROOT/'assets'/n).is_file() for n in ('xterm.js', 'xterm.css', 'xterm-addon-fit.js')),
    'python_signature': 'Get-AuthenticodeSignature' in ps and 'Python Software Foundation' in ps,
    'full_manifest': 'MANIFEST_FULL_SHA256.txt' in ps and 'Get-FileHash' in ps,
    'qa_after_install': 'validate_runtime' in ps,
    'user_path': 'SetEnvironmentVariable("Path"' in ps,
    'desktop_shortcut': 'MobHector.lnk' in ps,
    'ruster_alias': (ROOT / 'rusterfiles.bat').exists(),
    'no_execution_policy_change': 'Set-ExecutionPolicy' not in ps and 'Set-ExecutionPolicy' not in bat,
    'uninstall_preserves_appdata': 'Remove-Item -Recurse -Force -LiteralPath $DataDir' not in un,
    'no_packaged_config': not (ROOT / 'config.json').exists(),
    'no_packaged_known_hosts': not (ROOT / 'known_hosts').exists(),
}

failed = []
for name, ok in checks.items():
    print(f"[{'OK' if ok else 'FAIL'}] {name}")
    if not ok:
        failed.append(name)

# La única referencia a los identificadores del entorno del creador debe estar
# dentro de un validador que confirma que NO son defaults del core.
forbidden = []  # Distribution starts with no user config or known_hosts; never embed identifiers.
for token in forbidden:
    matches = []
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.name == 'validar_instalador_full_v1_3_4.py':
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if token in text and path.name != 'validar_fresh_defaults_v1_2_2.py':
            matches.append(str(path.relative_to(ROOT)))
    ok = not matches
    print(f"[{'OK' if ok else 'FAIL'}] no_personal_{token}: {matches}")
    if not ok:
        failed.append(f'no_personal_{token}')

if failed:
    raise SystemExit('FULL INSTALLER QA FAILED: ' + ', '.join(failed))
print(f'FULL INSTALLER 1.5.0 QA: OK ({len(checks)+len(forbidden)} checks)')
