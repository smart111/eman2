#!/usr/bin/env bash

source ci_support/setup_conda.sh

export CPU_COUNT=2

conda install conda-build=2 -c defaults --yes --quiet

conda build recipes/eman -c cryoem -c defaults -c conda-forge
