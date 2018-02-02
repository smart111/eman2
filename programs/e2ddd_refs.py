#!/usr/bin/env python
from __future__ import print_function

#
# Author: Steven Ludtke, 02/12/2013 (sludtke@bcm.edu). Updated on 08/28/16.
# Modified by James Michael Bell, 03/27/2017 (jmbell@bcm.edu)
# Copyright (c) 2000-2013 Baylor College of Medicine
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  2111-1307 USA
#

from EMAN2 import *
from numpy import *
import pprint
import sys
import os
from sys import argv
from time import sleep,time
import threading
import Queue
import numpy as np
from sklearn import linear_model
from scipy import optimize

def main():

	progname = os.path.basename(sys.argv[0])
	usage = """prog [options] <ddd_movie_stack>

	This program will do various processing operations on "movies" recorded on direct detection cameras. It
	is primarily used to do whole-frame alignment of movies using all-vs-all CCFs with a global optimization
	strategy. Several outputs including different frame subsets are produced, as well as a text file with the
	translation vector map.

	See e2ddd_particles for per-particle alignment.

	Note: We have found the following to work on DE64 images:
	e2ddd_movie.py <movies> --de64 --dark <dark_frames> --gain <gain_frames> --gain_darkcorrected --reverse_gain --invert_gain

	Note: For multi-image files in MRC format, use the .mrcs extension. Do not use .mrc, as it will handle input stack as a 3D volume.
	"""

	parser = EMArgumentParser(usage=usage,version=EMANVERSION)

	parser.add_pos_argument(name="movies",help="List the movies to align.", default="", guitype='filebox', browser="EMMovieDataTable(withmodal=True,multiselect=True)",  row=0, col=0,rowspan=1, colspan=3, mode="align,tomo")

	parser.add_header(name="orblock1", help='Just a visual separation', title="Dark/Gain Correction", row=2, col=0, rowspan=2, colspan=3, mode="align,tomo")

	#parser.add_header(name="orblock2", help='Just a visual separation', title="- CHOOSE FROM -", row=3, col=0, rowspan=1, colspan=3, mode="align,tomo")

	parser.add_argument("--dark",type=str,default="",help="Perform dark image correction using the specified image file",guitype='filebox',browser="EMMovieDataTable(withmodal=True,multiselect=False)", row=4, col=0, rowspan=1, colspan=3, mode="align,tomo")
	parser.add_argument("--rotate_dark",  default = "0", type=str, choices=["0","90","180","270"], help="Rotate dark reference by 0, 90, 180, or 270 degrees. Default is 0. Transformation order is rotate then reverse.",guitype='combobox', choicelist='["0","90","180","270"]', row=5, col=0, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--reverse_dark", default=False, help="Flip dark reference along y axis. Default is False. Transformation order is rotate then reverse.",action="store_true",guitype='boolbox', row=5, col=1, rowspan=1, colspan=1, mode="align,tomo")

	parser.add_argument("--gain",type=str,default="",help="Perform gain image correction using the specified image file",guitype='filebox',browser="EMMovieDataTable(withmodal=True,multiselect=False)", row=6, col=0, rowspan=1, colspan=3, mode="align,tomo")
	parser.add_argument("--k2", default=False, help="Perform gain image correction on gain images from a Gatan K2. Note, these are the reciprocal of typical DDD gain images.",action="store_true",guitype='boolbox', row=7, col=0, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--rotate_gain", default = 0, type=str, choices=["0","90","180","270"], help="Rotate gain reference by 0, 90, 180, or 270 degrees. Default is 0. Transformation order is rotate then reverse.",guitype='combobox', choicelist='["0","90","180","270"]', row=7, col=1, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--reverse_gain", default=False, help="Flip gain reference along y axis (about x axis). Default is False. Transformation order is rotate then reverse.",action="store_true",guitype='boolbox', row=7, col=2, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--de64", default=False, help="Perform gain image correction on DE64 data. Note, these should not be normalized.",action="store_true",guitype='boolbox', row=8, col=0, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--gain_darkcorrected", default=False, help="Do not dark correct gain image. False by default.",action="store_true",guitype='boolbox', row=8, col=1, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--invert_gain", default=False, help="Use reciprocal of input gain image",action="store_true",guitype='boolbox', row=8, col=2, rowspan=1, colspan=1, mode="align,tomo")

	#parser.add_header(name="orblock3", help='Just a visual separation', title="- OR -", row=6, col=0, rowspan=1, colspan=3, mode="align,tomo")

	parser.add_header(name="orblock4", help='Just a visual separation', title="Output: ", row=10, col=0, rowspan=2, colspan=1, mode="align,tomo")

	parser.add_argument("--ext",default="hdf",type=str, choices=["hdf","mrcs","mrc"],help="Save frames with this extension. Default is 'hdf'.", guitype='strbox', row=19, col=1, rowspan=1, colspan=1, mode="align,tomo")
	parser.add_argument("--suffix",type=str,default="proc",help="Specify a unique suffix for output frames. Default is 'proc'. Note that the output of --frames will be overwritten if identical suffix is already present.",guitype='strbox', row=19, col=2, rowspan=1, colspan=1, mode="align,tomo")

	parser.add_argument("--verbose", "-v", dest="verbose", action="store", metavar="n", type=int, default=0, help="verbose level [0-9], higner number means higher level of verboseness")
	parser.add_argument("--debug", default=False, action="store_true", help="run with debugging output")
	parser.add_argument("--ppid", type=int, help="Set the PID of the parent process, used for cross platform PPID",default=-2)

	(options, args) = parser.parse_args()

	if len(args)<1:
		print(usage)
		parser.error("Specify input DDD stack to be processed.")

	if options.frames == False and options.noali == False and options.align_frames == False:
		print("No outputs specified. See --frames, --noali, or --align_frames. Exiting.") 
		sys.exit(1)

	if options.align_frames == True:
		if options.allali == False and options.rangeali == False and options.goodali == False and options.bestali == False and options.ali4to14 == False:
			print("No post alignment outputs specified. Try with --allali, --rangeali, --goodali, --bestali, or --ali4to14. Exiting.")
			sys.exit(1)

	if options.bad_columns == "": options.bad_columns = []
	else: 
		try: options.bad_columns = [int(c) for c in options.bad_columns.split(",")]
		except:
			print("Error: --bad_columns contains nonnumeric input.")
			sys.exit(1)

	if options.bad_rows == "": options.bad_rows = []
	else: 
		try: options.bad_rows = [int(r) for r in options.bad_rows.split(",")]
		except:
			print("Error: --bad_rows contains nonnumeric input.")
			sys.exit(1)

	# try: os.mkdir("micrographs")
	# except: pass

	if options.tomo:
		try: os.mkdir("rawtilts")
		except: pass

	pid=E2init(sys.argv)

	if options.dark != "":
		print("Loading Dark Reference")
		if "e2ddd_darkref" in options.dark:
			dark = EMData(options.dark,-1)
		else:
			if options.dark[-4:].lower() in (".mrc") :
				dark_hdr = EMData(options.dark,0,True)
				nx = dark_hdr["nx"]
				ny = dark_hdr["ny"]
				nd = dark_hdr["nz"]
				dark=EMData(options.dark,0,False,Region(0,0,0,nx,ny,1))
			else:
				nd=EMUtil.get_image_count(options.dark)
				dark = EMData(options.dark,0)
				nx = dark["nx"]
				ny = dark["ny"]
			if nd>1:
				sigd=dark.copy()
				sigd.to_zero()
				a=Averagers.get("mean",{"sigma":sigd,"ignore0":1})
				print("Summing Dark Frames")
				for i in xrange(0,nd):
					if options.verbose:
						sys.stdout.write("({}/{})   \r".format(i+1,nd))
						sys.stdout.flush()
					if options.dark[-4:].lower() in (".mrc") :
						t=EMData(options.dark,0,False,Region(0,0,i,nx,ny,1))
					else:
						t=EMData(options.dark,i)
					t.process_inplace("threshold.clampminmax",{"minval":0,"maxval":t["mean"]+t["sigma"]*3.5,"tozero":1})
					a.add_image(t)
				dark=a.finish()
				if options.debug: sigd.write_image(options.dark.rsplit(".",1)[0]+"_sig.hdf")
				if options.fixbadpixels:
					sigd.process_inplace("threshold.binary",{"value":sigd["sigma"]/10.0}) # Theoretically a "perfect" pixel would have zero sigma, but in reality, the opposite is true
					dark.mult(sigd)
				if options.debug: dark.write_image(options.dark.rsplit(".",1)[0]+"_sum.hdf")
			#else: dark.mult(1.0/99.0)
			dark.process_inplace("threshold.clampminmax.nsigma",{"nsigma":3.0})
			dark2=dark.process("normalize.unitlen")
	else : dark=None

	if options.gain != "":
		print("Loading Gain Reference")
		if "e2ddd_gainref" in options.gain:
			gain = EMData(options.gain,-1)
		else:
			if options.k2: gain=EMData(options.gain)
			else:
				if options.gain[-4:].lower() in (".mrc") :
					gain_hdr = EMData(options.gain,0,True)
					nx = gain_hdr["nx"]
					ny = gain_hdr["ny"]
					nd = gain_hdr["nz"]
					gain=EMData(options.gain,0,False,Region(0,0,0,nx,ny,1))
				else:

					nd=EMUtil.get_image_count(options.gain)
					gain = EMData(options.gain,0)
					nx = gain["nx"]
					ny = gain["ny"]
				if nd>1:
					sigg=gain.copy()
					sigg.to_zero()
					a=Averagers.get("mean",{"sigma":sigg,"ignore0":1})
					print("Summing Gain Frames")
					for i in xrange(0,nd):
						if options.verbose:
							sys.stdout.write("({}/{})   \r".format(i+1,nd))
							sys.stdout.flush()
						if options.dark != "" and options.dark[-4:].lower() in (".mrc") :
							t=EMData(options.gain,0,False,Region(0,0,i,nx,ny,1))
						else:
							t=EMData(options.gain,i)
						#t.process_inplace("threshold.clampminmax.nsigma",{"nsigma":4.0,"tozero":1})
						t.process_inplace("threshold.clampminmax",{"minval":0,"maxval":t["mean"]+t["sigma"]*3.5,"tozero":1})
						a.add_image(t)
					gain=a.finish()
					if options.debug: sigg.write_image(options.gain.rsplit(".",1)[0]+"_sig.hdf")
					if options.fixbadpixels:
						sigg.process_inplace("threshold.binary",{"value":sigg["sigma"]/10.0}) # Theoretically a "perfect" pixel would have zero sigma, but in reality, the opposite is true
						if dark!="" : 
							try: sigg.mult(sigd)
							except: pass
						gain.mult(sigg)
					if options.debug: gain.write_image(options.gain.rsplit(".",1)[0]+"_sum.hdf")
				if options.de64:
					gain.process_inplace( "threshold.clampminmax", { "minval" : gain[ 'mean' ] - 8.0 * gain[ 'sigma' ], "maxval" : gain[ 'mean' ] + 8.0 * gain[ 'sigma' ], "tomean" : True } )
				else:
					gain.process_inplace("math.reciprocal",{"zero_to":0.0})
					#gain.mult(1.0/99.0)
					#gain.process_inplace("threshold.clampminmax.nsigma",{"nsigma":3.0})

			if dark!="" and options.gain != "" and options.gain_darkcorrected == False: gain.sub(dark) # dark correct the gain-reference

			if options.de64:
				mean_val = gain["mean"]
				if mean_val <= 0.: mean_val=1.
				gain.process_inplace("threshold.belowtominval",{"minval":0.01,"newval":mean_val})

			gain.mult(1.0/gain["mean"])

			if options.invert_gain: gain.process_inplace("math.reciprocal")
	#elif options.gaink2 :
	#	gain=EMData(options.gaink2)
	else : gain=None

	if options.rotate_gain and gain != None:
		tf = Transform({"type":"2d","alpha":int(options.rotate_gain)})
		gain.process_inplace("xform",{"transform":tf})

	if options.reverse_gain: gain.process_inplace("xform.reverse",{"axis":"y"})

	if options.rotate_dark and dark != None:
		tf = Transform({"type":"2d","alpha":int(options.rotate_dark)})
		dark.process_inplace("xform",{"transform":tf})

	if options.reverse_dark: dark.process_inplace("xform.reverse",{"axis":"y"})

	if gain or dark:
		try: os.mkdir("movies")
		except: pass

	if gain:
		gainname="movies/e2ddd_gainref.hdf"
		gain.write_image(gainname,-1)
		gainid=EMUtil.get_image_count(gainname)-1
		gain["filename"]=gainname
		gain["fileid"]=gainid

	if dark:
		darkname="movies/e2ddd_darkref.hdf"
		dark.write_image(darkname,-1)
		darkid=EMUtil.get_image_count(darkname)-1
		dark["filename"]=darkname
		dark["fileid"]=darkid

	E2end(pid)

if __name__ == "__main__":
	main()
