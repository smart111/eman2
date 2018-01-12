#!/bin/bash

set -xe

unset MACOSX_DEPLOYMENT_TARGET
unset ADDR2LINE
unset AR
unset AS
unset CC
unset CFLAGS
unset CONDA_BACKUP_HOST
unset CPP
unset CPPFLAGS
unset CXX
unset CXXFILT
unset CXXFLAGS
unset DEBUG_CFLAGS
unset DEBUG_CPPFLAGS
unset DEBUG_CXXFLAGS
unset ELFEDIT
unset GCC
unset GCC_AR
unset GCC_NM
unset GCC_RANLIB
unset GPROF
unset GXX
unset HOST
unset LD
unset LDFLAGS
unset LD_GOLD
unset NM
unset OBJCOPY
unset OBJDUMP
unset RANLIB
unset READELF
unset SIZE
unset STRINGS
unset STRIP
unset _PYTHON_SYSCONFIGDATA_NAME

build_dir="${SRC_DIR}/../build_eman"

rm -rf $build_dir
mkdir -p $build_dir
cd $build_dir

cmake $SRC_DIR

make -j${CPU_COUNT}
make install
make test-verbose
