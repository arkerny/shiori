[app]

# title of your application
title = Shiori

# project root directory. default = The parent directory of input_file
project_dir = .

# source file entry point path. default = main.py
input_file = main.py

# directory where the executable output is generated
exec_directory = .

# path to the project file relative to project_dir
project_file = 

# application icon
icon = /Users/arkerny/Desktop/shiori/.venv/lib/python3.14/site-packages/PySide6/scripts/deploy_lib/pyside_icon.icns

[python]

# python path
python_path = /Users/arkerny/Desktop/shiori/.venv/bin/python3.14

# python packages to install
packages = Nuitka==4.1.3

[qt]

# paths to required qml files. comma separated
# normally all the qml files required by the project are added automatically
qml_files = 

# excluded qml plugin binaries
excluded_qml_plugins = 

# qt modules used. comma separated
modules = Core,DBus,Gui,Widgets

# qt plugins used by the application
plugins = accessiblebridge,egldeviceintegrations,generic,iconengines,imageformats,platforminputcontexts,platforms,platforms/darwin,platformthemes,styles,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[nuitka]

# usage description for permissions requested by the app as found in the info.plist
# file of the app bundle. comma separated
# eg = extra_args = --show-modules --follow-stdlib
macos.permissions = 

# mode of using nuitka. accepts standalone or onefile. default = onefile
# 注意：macos 上 pyside6-deploy 强制 --standalone --macos-create-app-bundle，
# 此项只对 windows/linux 生效；macos 产物固定为 shiori.app
mode = onefile

# specify any extra nuitka arguments
# --include-package-data = pypinyin/certifi：两者都在运行期按 __file__ 相对
# 路径读包内数据文件（拼音字典 / ca 证书），nuitka 不会自动打入，须显式包含
extra_args = --quiet --noinclude-qt-translations --include-package-data=pypinyin --include-package-data=certifi

