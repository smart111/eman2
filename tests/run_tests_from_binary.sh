#!/usr/bin/env bash

set -xe

MYDIR="$(cd "$(dirname "$0")" && pwd -P)"

export SRC_DIR="$(cd "$(dirname "$0")"/.. && pwd -P)"
export PREFIX=${SRC_DIR}

bash "${MYDIR}/run_tests.sh"
