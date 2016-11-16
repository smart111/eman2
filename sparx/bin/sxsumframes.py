#! /usr/bin/env python
#
# Copyright (C) 2016  Markus Stabrin (markus.stabrin@mpi-dortmund.mpg.de)
#
# This software is issued under a joint BSD/GNU license. You may use the
# source code in this file under either license. However, note that the
# complete EMAN2 and SPARX software packages have some GPL dependencies,
# so you are responsible for compliance with the licenses of these packages
# if you opt to use BSD licensing. The warranty disclaimer below holds
# in either instance.
#
# This complete copyright notice must be included in any revised version of the
# source code. Additional authorship citations may be added, but existing
# author citations must be preserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.

from sparx import EMData, Region, fshift, read_text_row, fft, Util
from sys import argv
from os import path
from global_def import SPARXVERSION, ERROR
from optparse import OptionParser
import global_def
import time

def main():
    
    progname = path.basename(argv[0])
    usage = progname + """ input_stack output_stack
    --shift_file
    --pixel_size
    --first
    --last
    --skip_alignment

    sp_sum_frame exists in non-MPI version.

    First element has the index 0 and last element is N-1.
    Negative indexing is also supported.
    -5 is the fifth elemnt from behind.
    For example --first=-5 and --last=-1 will sum the last five frames.

    """

    parser = OptionParser(usage, version=SPARXVERSION)
    parser.add_option('--shift_file', type=str, default='', help='Shift file for alignment (default "")')
    parser.add_option('--pixel_size', type=float, default=-1, help='Pixel size [A] (default -1)')
    parser.add_option('--first', type=int, default=0, help='First frame to use (default 0)')
    parser.add_option('--last', type=int, default=-1, help='Last frame to use (default -1). Can not be used together with the --dose option.')
    parser.add_option('--skip_alignment', action='store_true', default=False, help='Skip the alignment and just sum the frames (default False)')
    parser.add_option('--dose', type=float, default=-1, help='Total electron dose for summing. Can not be used together with the --last option.')
    (options, args) = parser.parse_args(argv[1:])

    global_def.BATCH = True

    # If arguments are missing abort
    if len(args) != 2:
        ERROR("see usage:\n" + usage, 1)

    if options.pixel_size <= 0:
        ERROR("pixel size [A] needs to be greater then 0 (default -1)\n" + usage, 1)

    # Use realpath
    input_name = path.realpath(args[0])
    output_name = path.realpath(args[1])

    if not path.exists(input_name):
        ERROR("input image {0} does not exists".format(input_name), 1)

    if not path.exists(options.shift_file) and not \
            options.skip_alignment:
        ERROR(
            "given shift file {0} does not exists\n".format(
                options.shift_file
                ) + \
            usage, 
            1
            )

    options_dict = {
            'shift_file': options.shift_file,
            'pixel_size': options.pixel_size,
            'first': options.first,
            'last': options.last,
            'skip_alignment': options.skip_alignment,
            'dose': options.dose
            }

    sum_images(input_name, output_name, options_dict)

    print('All Done!')


def sum_images(input_name, output_name, options):
    """Translate images and sum them"""

    #Import the input stack
    input_stack = EMData(input_name)

    # Get the dimensions of the input stack
    nx = input_stack['nx']
    ny = input_stack['ny']
    nz = input_stack['nz']

    # Check how many frames to use
    if nz < abs(options['last']):
        ERROR(
                "Last option {0} is out of range: maximum |{1}|".format(
                options['last'], nz-1
                ), 
            1)

    if nz < abs(options['first']):
        ERROR(
                "First option {0} is out of range: maximum |{1}|".format(
                options['last'], nz-1
                ), 
            1)

    # Get real indices
    if options['first'] < 0:
        first = nz + options['first']
    else:
        first = options['first']

    if options['last'] < 0:
        last = nz + options['last'] + 1
    else:
        last = options['last'] + 1

    if first >= last:
        ERROR("First option {0}={1} muss be smaller equals last option {2}={3}".format(
            options['first'], first, options['last'], last-1
            ),
            1)

    # Import shift files
    shifts = read_text_row(options['shift_file'])
    sx, sy = shifts[-2], shifts[-1]
    # Transform shifts in angstrom to pixels
    for i in range(len(sx)):
        sx[i] /= options['pixel_size']
        sy[i] /= options['pixel_size']

    # If one wants to perform the alignment
    if not options['skip_alignment']:
        # Create an output image container in fourier space
        output_image = EMData(nx, ny, 1, False)
        # Loop over all frames
        for i in xrange(first, last):
            # Get the frame as a slice of the 3D volume
            frame = input_stack.get_clip(Region(0, 0, i, nx, ny, 1))
            # Transform into fourier space
            frame = fft(frame)
            # Perform cyclic phase shift
            frame = fshift(frame, sx[i], sy[i])
            # Add shiftet frame to the output image
            Util.add_img(output_image, frame)
        # Transform the output image to real space
        output_image = fft(output_image)

    # Else just perform the suming
    else:
        # Create an output image container in real space
        output_image = EMData(nx, ny, 1, True)
        for i in xrange(first, last):
            # Get the frame as a slice of the 3D volume
            frame = input_stack.get_clip(Region(0, 0, i, nx, ny, 1))
            # Add to output image
            Util.add_img(output_image, frame)

    # Write the output image
    output_image.write_image(output_name)

if __name__ == '__main__':
    main()
