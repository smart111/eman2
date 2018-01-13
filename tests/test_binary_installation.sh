#!/usr/bin/env bash

set -xe

MYDIR=$(cd $(dirname $0) && pwd -P)

for f in ${@};do
    dir=$(dirname $f)
    fbase=$(basename $f)
    fbase=${fbase%\.*}
    fbase=${fbase//\./-}
    conda_loc=${dir}/${fbase}
    
    echo "... $fbase ..."
    
    bash $f -b -p ${conda_loc}
    source ${conda_loc}/bin/activate root
    bash ${MYDIR}/run_tests_from_binary.sh || true
    source deactivate
done
