#!/usr/bin/env bash

source ci_support/setup_conda.sh

conda install --yes --quiet eman-deps -c cryoem -c defaults -c conda-forge

# Build and install eman2
export build_dir=$HOME/build_eman

rm -rf ${build_dir}
mkdir -p ${build_dir}
cd ${build_dir}

cmake "${OLDPWD}"
make
make install
make test-verbose

# Run tests
e2version.py
e2speedtest.py

cd -
mpirun -n 4 $(which python) examples/mpi_test.py
bash tests/run_prog_tests.sh
python tests/test_EMAN2DIR.py
