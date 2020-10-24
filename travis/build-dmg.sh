#!/bin/bash
#
# Credits: from the great https://github.com/Pext/Pext
#

set -x
set -e

# use RAM disk if possible
if [ -d /dev/shm ]; then
    TEMP_BASE=/dev/shm
else
    TEMP_BASE=/tmp
fi

BUILD_DIR=$(mktemp -d "$TEMP_BASE/ginstaller-MacOS-build-XXXXXX")

COMMIT_SHORT=$(echo $TRAVIS_COMMIT|cut -c 1-8)
G_VERSION=$(grep '__version__' ginstaller/__init__.py|sed -e "s/__version__ = '\(.*\)'$/\1/")

if [[ $TRAVIS_BRANCH =~ ^v([0-9].[0-9].[0-9]{1,2}) ]] ; then
    echo "Using tag: $TRAVIS_BRANCH"
    EVERSION=${BASH_REMATCH[1]}
    DMG_DEST="Galacteek-Installer-${EVERSION}.dmg"
else
    if [ "$TRAVIS_BRANCH" != "master" ]; then
        echo "Short commit ID: ${COMMIT_SHORT}"
        DMG_DEST="Galacteek-Installer-${COMMIT_SHORT}.dmg"
    else
        DMG_DEST="Galacteek-Installer-${G_VERSION}.dmg"
    fi
fi

echo "Building to DMG: $DMG_DEST"

cleanup () {
    if [ -d "$BUILD_DIR" ]; then
        rm -rf "$BUILD_DIR"
    fi
}

trap cleanup EXIT

OLD_CWD="$(pwd)"

pushd "$BUILD_DIR"/

# install Miniconda
MINICONDA_DIST="Miniconda3-py37_4.8.3-MacOSX-x86_64.sh"
wget https://repo.anaconda.com/miniconda/${MINICONDA_DIST}
bash ${MINICONDA_DIST} -b -p ~/miniconda -f
rm ${MINICONDA_DIST}

export PATH="$HOME/miniconda/bin:$PATH"

# create conda env
conda create -n ginstaller python=3.7 --yes
source activate ginstaller

# install dependencies
pip install wheel
pip install -r "$OLD_CWD"/requirements.txt
pip install "$OLD_CWD"/dist/ginstaller-${G_VERSION}-py3-none-any.whl

# leave conda env
source deactivate

# create .app Framework
mkdir -p ginstaller.app/Contents/
mkdir ginstaller.app/Contents/MacOS ginstaller.app/Contents/Resources ginstaller.app/Contents/Resources/ginstaller
cp "$OLD_CWD"/travis/Info.plist ginstaller.app/Contents/Info.plist

# copy Miniconda env
cp -R ~/miniconda/envs/ginstaller/* ginstaller.app/Contents/Resources/

# copy icons
mkdir -p ginstaller.app/Contents/Resources/share/icons
cp "$OLD_CWD"/share/icons/ginstaller.icns ginstaller.app/Contents/Resources/share/icons

# copy go-ipfs
mkdir -p ginstaller.app/Contents/Resources/bin
cp $HOME/bin/ipfs ginstaller.app/Contents/Resources/bin
cp $HOME/bin/fs-repo-migrations ginstaller.app/Contents/Resources/bin

# Install libmagic and the magic db files
brew install libmagic
cp -av /usr/local/Cellar/libmagic/*/lib/*.dylib ginstaller.app/Contents/Resources/lib
cp -av /usr/local/Cellar/libmagic/*/share/misc ginstaller.app/Contents/Resources/share/

brew update

brew unlink python@2

# zbar install. Copy depencies (libjpeg)
brew install zbar
cp -av /usr/local/Cellar/zbar/*/lib/*.dylib ginstaller.app/Contents/Resources/lib
cp -av /usr/local/Cellar/jpeg/*/lib/*.dylib ginstaller.app/Contents/Resources/lib
cp -av /usr/local/Cellar/libpng/*/lib/*.dylib ginstaller.app/Contents/Resources/lib

# create entry script for ginstaller
cat > ginstaller.app/Contents/MacOS/ginstaller <<\EAT
#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export GALACTEEK_MAGIC_DBPATH="$DIR/../Resources/share/misc/magic.mgc"
export DYLD_FALLBACK_LIBRARY_PATH=$DYLD_FALLBACK_LIBRARY_PATH:$DIR/../Resources/lib
export PATH=$PATH:$DIR/../Resources/bin
$DIR/../Resources/bin/python $DIR/../Resources/bin/ginstaller -d --from-dmg --no-ssl-verify
EAT

chmod a+x ginstaller.app/Contents/MacOS/ginstaller

# bloat deletion sequence
pushd ginstaller.app/Contents/Resources
rm -rf pkgs
find . -type d -iname '__pycache__' -print0 | xargs -0 rm -r
rm -rf lib/python3.7/site-packages/Cryptodome/SelfTest/*
rm -rf lib/python3.7/site-packages/PyQt5/Qt/plugins/geoservices
rm -rf lib/python3.7/site-packages/PyQt5/Qt/plugins/sceneparsers
rm -rf lib/cmake/
rm -f bin/sqlite3*
rm -rf include/
rm -rf share/{info,man}
popd
popd

# Get the create-dmg repo
git clone https://github.com/andreyvit/create-dmg $HOME/create-dmg

# generate .dmg
$HOME/create-dmg/create-dmg --hdiutil-verbose --volname "Galacteek-Installer-${G_VERSION}" \
    --volicon "${OLD_CWD}"/share/icons/ginstaller.icns \
    --hide-extension ginstaller.app $DMG_DEST "$BUILD_DIR"/
