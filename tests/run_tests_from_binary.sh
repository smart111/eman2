#!/usr/bin/env bash

MYDIR=$(cd $(dirname $0) && pwd -P)

export SRC_DIR=${MYDIR}
export PREFIX=${MYDIR}

bash ${MYDIR}/run_tests.sh
