# Linux Binary Installer
Install any files (e.g., scripts, binaries, AppImages) and add shortcuts to the desktop and start menu.

## Installation Instructions
The following command assumes **Python** and **pip** are already installed. It will create the directory `$HOME/Software/LinuxBinaryInstaller`, download the required files, install dependencies, and launch the installer.

```bash
mkdir -p $HOME/Software/LinuxBinaryInstaller && cd $HOME/Software/LinuxBinaryInstaller && curl -O https://raw.githubusercontent.com/Daechler/LinuxBinaryInstaller/refs/heads/main/requirements.txt -O https://raw.githubusercontent.com/Daechler/LinuxBinaryInstaller/refs/heads/main/installer_gui.py && pip install -r requirements.txt && python installer_gui.py
```
