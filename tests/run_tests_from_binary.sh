#!/usr/bin/env bash

export SRC_DIR=$(cd "$(dirname $0)"/.. && pwd -P)
export PREFIX=${SRC_DIR}

bash ${MYDIR}/run_tests.sh
