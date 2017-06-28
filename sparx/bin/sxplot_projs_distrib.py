#! /usr/bin/env python

#
# Author: Pawel A.Penczek, 09/09/2006 (Pawel.A.Penczek@uth.tmc.edu)
# Copyright (c) 2000-2006 The University of Texas - Houston Medical School
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
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
#
#


import os
import global_def
from   global_def import *
from   optparse import OptionParser
import sys
def main():
	
	progname = os.path.basename(sys.argv[0])
	usage = progname + """ 2Dprojections plot_output

Read projection angles from 2Dprojections file or from a text file and write a 2D image file
containing their distribution on a hemisphere."""
	parser = OptionParser(usage,version=SPARXVERSION)
	parser.add_option("--wnx",       type="int",  default=256,             help="plot image size / particle box size (default 256)")
	parser.add_option('--do_hist',    	action="store_true",  	default=False,        	help='create a histogram for each angle (not created by default)')
	parser.add_option('--skip_dim_2',    	action="store_true",  	default=False,        	help='skip creating a 2D angular distribution plot (created by default)')
	parser.add_option('--skip_dim_3',    	action="store_true",  	default=False,        	help='skip creating a 3D angular distribution plot (created by default)')
	parser.add_option('--acc',             	type='int',          	default=6,           	help='accuracy of the loaded angle (default 5)')
	parser.add_option('--particle_radius',     		type='int',          	default=175,         	help='particle radius [Pixels] (default 175)')
	parser.add_option('--cylinder_width',      		type='int',          	default=1,           	help='width of the cylinder (default 1)')
	parser.add_option('--cylinder_length',     		type='int',          	default=10000,       	help='length of the cylinder (default 10000)')
	parser.add_option('--pixel_size',     		type='float',          	default=1.0,       	help='pixel_size (default 1.0)')
	parser.add_option('--sym',     		type='str',          	default='c1',       	help='symmetry (default c1)')

	(options, args) = parser.parse_args()
    	if len(args) != 2:
		print "usage: " + usage
		print "Please run '" + progname + """ -h' for detailed options"""
	else:
		if global_def.CACHE_DISABLE:
			from utilities import disable_bdb_cache
			disable_bdb_cache()
		from applications import plot_projs_distrib
		global_def.BATCH = True
		plot_projs_distrib(
			args[0],
			args[1],
			wnx=options.wnx,
			plot_hist=options.do_hist,
			plot_2d=bool(options.skip_dim_2 == False),
			plot_3d=bool(options.skip_dim_3 == False),
			acc=options.acc,
			particle_radius=options.particle_radius,
			width=options.cylinder_width,
			length=options.cylinder_length,
			pixel_size=options.pixel_size,
			sym=options.sym
			)
		global_def.BATCH = False

if __name__ == "__main__":
	        main()
