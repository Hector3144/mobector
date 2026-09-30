# VcXsrv 21.1.16.1 — Windows x64

MobHector packages the unmodified runtime extracted from the official no-admin
installer. It is a separate program communicating through X11, not a Python module.
Copyright and licenses remain with the original authors. VcXsrv is distributed
under GPL-3.0-or-later; included components retain their respective licenses.
See LICENSE-VcXsrv.txt (COPYING.txt in the installed runtime).

Original installer:
https://github.com/marchaesen/vcxsrv/releases/download/21.1.16.1/vcxsrv-64.21.1.16.1.installer.noadmin.exe

SHA256: dea6c7d67d3d15b4ed45c87b63a83c88f4aceaaef5425630f0e97a0bad70d620

Corresponding source, licenses, third-party sources and build scripts for this tag:
https://github.com/marchaesen/vcxsrv/tree/21.1.16.1
Source archive (free download):
https://github.com/marchaesen/vcxsrv/archive/refs/tags/21.1.16.1.tar.gz
Build instructions: README.md in that source tree.

The package builder verifies the installer SHA256 before extracting it. No VcXsrv
installer runs on the user's computer; MobHector copies the runtime files alongside
the application. No machine-wide registration or independent VcXsrv setup is needed.
