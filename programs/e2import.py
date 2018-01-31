#!/usr/bin/env python
from __future__ import print_function
#
# Author: John Flanagan (jfflanag@bcm.edu)
# Copyright (c) 2000-2011 Baylor College of Medicine


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

import os, shutil, glob
from EMAN2 import *
from EMAN2star import StarFile
import numpy as np

def main():
	progname = os.path.basename(sys.argv[0])
	usage = """prog [options] files
	This program performs a variety of tasks for getting data or metadata from other programs into an EMAN2 project.

	import_particles - will simply copy a set of per-micrograph particle files into EMAN2.1's preferred HDF format in particles/
	import_boxes - will read EMAN1 '.box' files (text files containing coordinates) into appropriate info/*json files (see --box_type)
	import_eman1 - will convert a typical EMAN1 phase-flipped start.hed/img file into an EMAN2 project (converting files, fixing CTF, splitting, ...)

	import_tomos - imports subtomogams for a SPT project (see also --importation)
	import_serialem - imports subtomogams for a SPT project (see also --importation)
	import_tiltseries - imports tilt series for a tomography project (--importation copy recommended)
	import_tiltangles - imports tilt ang.es for corresponding tilt series (--importation copy recommended)

	"""

	parser = EMArgumentParser(usage=usage,version=EMANVERSION)

	parser.add_pos_argument(name="import_files",help="List the files to import here.", default="", guitype='filebox', browser="EMBrowserWidget(withmodal=True,multiselect=True)",  row=0, col=0, rowspan=1, colspan=2, nosharedb=True, mode='coords,parts,tomos,eman1,movies,tilts')

	parser.add_header(name="filterheader", help='Options below this label are specific to e2import', title="### e2import options ###", row=2, col=0, rowspan=1, colspan=2, mode='coords,parts,tomos')

	# SPR Data
	parser.add_argument("--import_particles",action="store_true",help="Import particles",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='parts[True]')
	parser.add_argument("--import_eman1",action="store_true",help="This will import a phase-flipped particle stack from EMAN1",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='eman1[True]')

	# Tomo Data
	parser.add_argument("--import_tomos",action="store_true",help="Import tomograms for segmentation and/or subtomogram averaging",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='tomos[True]')

	# Tiltseries
	parser.add_argument("--serialem",action="store_true",help="Interpret input as a tiltseries produced by SerialEM.",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='tilts[True]')
	parser.add_argument("--import_mdoc",type=str,help="Import metadata from a corresponding SerialEM '.mdoc' file.\nIf not specified, this program will search for an MDOC file with the standard naming convention relative to 'input_tiltseries'\nImportant: this will ensure the correct tilt series order when reconstructing a motion corrected, bidrectional tilt series.",default="", guitype='filebox', browser="EMBrowserWidget(withmodal=True,multiselect=True)", row=1, col=0, rowspan=1, colspan=3, mode='tilts')

	parser.add_argument("--import_movies",action="store_true",help="This will import a phase-flipped particle stack from EMAN1",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='movies[True]')
	parser.add_argument("--import_dark",type=str,help="Import dark correction image to be associated with imported movies",default="", guitype='filebox', browser="EMBrowserWidget(withmodal=True,multiselect=True)", row=1, col=0, rowspan=1, colspan=3, mode='movies')
	parser.add_argument("--import_gain",type=str,help="Import gain normalization image to be associated with these files.",default="", guitype='filebox', browser="EMBrowserWidget(withmodal=True,multiselect=True)", row=2, col=0, rowspan=1, colspan=3, mode='movies')

	parser.add_argument("--shrink",type=int,help="Shrink tomograms before importing. Dose not work while not copying.",default=1, guitype='intbox', row=4, col=0, rowspan=1, colspan=1, mode='tomos')
	parser.add_argument("--invert",action="store_true",help="Invert the contrast before importing tomograms",default=False, guitype='boolbox', row=4, col=1, rowspan=1, colspan=1, mode='tomos,tilts')
	parser.add_argument("--tomoseg_auto",action="store_true",help="Default process for tomogram segmentation, including lowpass, highpass, normalize, clampminmax.",default=True, guitype='boolbox', row=4, col=2, rowspan=1, colspan=1, mode='tomos,tilts')
	parser.add_argument("--importation",help="Specify import mode: move, copy or link",default='copy',guitype='combobox',choicelist='["move","copy","link"]',row=3,col=1,rowspan=1,colspan=1, mode='tomos,tilts,movies["move"]')
	parser.add_argument("--preprocess",type=str,help="Other pre-processing operation before importing tomograms. Dose not work while not copying.",default="", guitype='strbox', row=5, col=0, rowspan=1, colspan=2, mode='tomos,tilts')
	parser.add_argument("--import_boxes",action="store_true",help="Import boxes",default=False, guitype='boolbox', row=3, col=0, rowspan=1, colspan=1, mode='coords[True]')
	parser.add_argument("--extension",type=str,help="Extension of the micrographs that the boxes match", default='dm3')
	parser.add_argument("--box_type",help="Type of boxes to import, normally boxes, but for tilted data use tiltedboxes, and untiltedboxes for the tilted  particle partner",default="boxes",guitype='combobox',choicelist='["boxes","coords","relion_star","tiltedboxes","untiltedboxes"]',row=3,col=1,rowspan=1,colspan=1, mode="coords['boxes']")
	parser.add_argument("--boxsize",help="Specify the boxsize for each particle.",type=int,default=256)
	parser.add_argument("--curdefocushint",action="store_true",help="Used with import_eman1, will use EMAN1 defocus as starting point",default=False, guitype='boolbox', row=5, col=0, rowspan=1, colspan=1, mode='eman1[True]')
	parser.add_argument("--curdefocusfix",action="store_true",help="Used with import_eman1, will use EMAN1 defocus unchanged (+-.001 um)",default=False, guitype='boolbox', row=5, col=1, rowspan=1, colspan=1, mode='eman1[False]')
	parser.add_argument("--threads", default=1,type=int,help="Number of threads to run in parallel on a single computer when multi-computer parallelism isn't useful",guitype='intbox', row=7, col=0, rowspan=1, colspan=1, mode='eman1[1]')
	parser.add_argument("--verbose", "-v", dest="verbose", action="store", metavar="n", type=int, default=0, help="verbose level [0-9], higner number means higher level of verboseness")
	parser.add_argument("--ppid", type=int, help="Set the PID of the parent process, used for cross platform PPID",default=-1)

	(options, args) = parser.parse_args()
	logid=E2init(sys.argv,options.ppid)

	# Import EMAN1
	# will read start.hed/img, split by micrograph (based on defocus), and reprocess CTF in EMAN2 style
	if options.import_eman1 :
		try:
			n=EMUtil.get_image_count(args[0])
		except:
			print("Error, couldn't read images from: ",args[0])
			sys.exit(1)

		try:
			img=EMData(args[0],0)
			ctf=img["ctf"]
		except:
			print("Error, start.hed/img must be phase-flipped to import")
			sys.exit(1)

		db=js_open_dict("info/project.json")
		db["global.apix"]=ctf.apix
		db["global.cs"]=ctf.cs
		db["global.voltage"]=ctf.voltage

		try: os.mkdir("particles")
		except: pass

		imgnum=0
		lastdf=-1.0
		for i in xrange(n):
			img=EMData(args[0],i)
			ctf=img["ctf"]
			img.del_attr("ctf")
			fft1=img.do_fft()
			if ctf.defocus!=lastdf :
				imgnum+=1
				if options.verbose>0: print("Defocus {:4.2f} particles{:03d}".format(ctf.defocus,imgnum))
				db=js_open_dict("info/particles{:03d}_info.json".format(imgnum))
				ctf2=EMAN2Ctf()
				ctf2.defocus=ctf.defocus
				ctf2.cs=ctf.cs
				ctf2.apix=ctf.apix
				ctf2.voltage=ctf.voltage
				ctf2.ampcont=ctf.ampcont
				ctf2.dfdiff=0
				ctf2.dfang=0
				db["ctf"]=[ctf2]
				db.close()

				flipim=fft1.copy()
				ctf2.compute_2d_complex(flipim,Ctf.CtfType.CTF_SIGN)

			lastdf=ctf.defocus

			# unflip the EMAN1 phases (hopefully accurate enough)
			fft1.mult(flipim)
			img=fft1.do_ift()
			img.write_image("particles/particles{:03d}.hdf".format(imgnum),-1)		# append particle to stack

		if options.curdefocusfix:
			flag="--curdefocusfix"
			rbysnr=" "
		elif options.curdefocushint:
			flag="--curdefocushint"
			rbysnr="--refinebysnr"
		else:
			flag=""
			rbysnr="--refinebysnr"

		# fill in the needed CTF info
		launch_childprocess("e2ctf.py --autofit {} --allparticles --threads {} --voltage {} --cs {} --ac {} --apix {} --computesf".format(flag,options.threads,ctf.voltage,ctf.cs,ctf.ampcont,ctf.apix))
		launch_childprocess("e2ctf.py --autofit {} --allparticles --threads {} --voltage {} --cs {} --ac {} --apix {}".format(flag,options.threads,ctf.voltage,ctf.cs,ctf.ampcont,ctf.apix))

		# reflip flip the phases, and make "proc" images
		launch_childprocess("e2ctf.py {} --phaseflip --allparticles --phaseflipproc filter.highpass.gauss:cutoff_freq=0.005 --phaseflipproc2 filter.lowpass.gauss:cutoff_freq=0.08 --phaseflipproc3 math.meanshrink:n=2".format(rbysnr))

		# build sets
		launch_childprocess("e2buildsets.py --allparticles --setname all")

	# Import boxes
	if options.import_boxes:
		# Check to make sure there are micrographs
		if not os.access("info", os.R_OK):
			os.mkdir("info")
		# Do imports
		# we add boxsize/2 to the coords since box files are stored with origin being the lower left side of the box, but in EMAN2 origin is in the center
		if options.box_type == 'boxes':
			micros=os.listdir("micrographs")
			for filename in args:
				boxlist = []
				fh = open(filename, 'r')
				for line in fh.readlines():
					if line[0]=="#" : continue
					fields = line.split()
					if len(fields)<4 : continue		# skip lines that don't work
					boxlist.append([float(fields[0])+float(fields[3])/2, float(fields[1])+float(fields[3])/2, 'manual'])

				js=js_open_dict(info_name(filename,nodir=True))
				js["boxes"]=boxlist
				js.close()
				if not "{}.hdf".format(base_name(filename,nodir=True)) in micros:
					print("Warning: Imported boxes for {}, but micrographs/{}.hdf does not exist".format(base_name(filename),base_name(filename,True)))

		elif options.box_type == 'coords':
			micros=os.listdir("micrographs")
			for filename in args:
				boxlist = []
				fh = open(filename, 'r')
				for line in fh.readlines():
					if line[0]=="#" : continue
					fields = line.split()
					if len(fields)<2 : continue		# skip lines that don't work
					boxlist.append([float(fields[0]), float(fields[1]), 'manual'])
				js_open_dict(info_name(filename,nodir=True))["boxes"]=boxlist
				if not "{}.hdf".format(base_name(filename,nodir=True)) in micros:
					print("Warning: Imported boxes for {}, but micrographs/{}.hdf does not exist".format(base_name(filename),base_name(filename,True)))


		elif options.box_type == 'tiltedboxes':

			for filename in args:
				boxlist = []
				fh = open(filename, 'r')
				for line in fh.readlines():
					if line[0]=="#" : continue
					fields = line.split()
					if len(fields)<4 : continue		# skip lines that don't work
					boxlist.append([float(fields[0])+float(fields[3])/2, float(fields[1])+float(fields[3])/2, 'tilted'])
				js_open_dict(info_name(filename,nodir=True))["boxes_rct"]=boxlist

		elif options.box_type == 'untiltedboxes':
			for filename in args:
				boxlist = []
				fh = open(filename, 'r')
				for line in fh.readlines():
					if line[0]=="#" : continue
					fields = line.split()
					if len(fields)<4 : continue		# skip lines that don't work
					boxlist.append([float(fields[0])+float(fields[3])/2, float(fields[1])+float(fields[3])/2, 'untilted'])
				js_open_dict(info_name(filename,nodir=True))["boxes_rct"]=boxlist

		elif options.box_type == 'relion_star':
			bs = options.boxsize
			starfs = [f for f in args if '.star' in f]
			if len(starfs) < 1:
				print("You must specify at least one .star file containing particle coordinates")
				exit(1)
			for filename in starfs:
				print(("Importing from {}.star".format(base_name(filename,nodir=True))))
				sf = StarFile(filename)
				hdr = sf.keys()
				if len(hdr) < 3:
					print(("Could not parse {}".format(filename)))
					continue
				mk = "rlnMicrographName"
				yk = "rlnCoordinateY"
				xk = "rlnCoordinateX"
				project_micros = os.listdir('micrographs')
				if mk not in hdr or yk not in hdr or xk not in hdr:
					possible = "{}.hdf".format(base_name(filename.replace('_autopick.star',''),nodir=True))
					if possible in project_micros:
						micros = [possible]
					else:
						print(("{} does not follow the RELION header convention for single particle data. To use this program".format(filename)))
						if mk not in hdr: print("Micrograph names should be listed under _rlnMicrographName")
						if yk not in hdr: print("Y coordinates must be listed under _rlnCoordinateY")
						if xk not in hdr: print("X coordinates must be listed under _rlnCoordinateX")
						continue
				else: micros=[i.split('/')[-1] for i in np.unique(sf[mk])]
				if len(micros) == 1:
					mg = micros[0]
					boxlist = []
					print(("Found {} boxes for {}".format(len(sf[xk]),mg)))
					for x,y in zip(sf[xk],sf[yk]):
						xc = int(x)
						yc = int(y)
						boxlist.append([xc,yc,'manual']) # should probably be 'relion' or 'from_star'
					js_open_dict(info_name(mg,nodir=True))["boxes"]=boxlist
					if not "{}.hdf".format(base_name(mg,nodir=True)) in project_micros:
						print("Warning: Imported boxes for {}.hdf, but micrographs/{}.hdf does not exist".format(base_name(filename),base_name(mg,nodir=True)))
				elif len(micros) > 1:
					for mg in project_micros:
						boxlist = []
						ptcls = []
						for i,name in enumerate(sf[mk]):
							mgname = name.split('/')[-1].split('.')[0]
							#print(mgname,hdf_name,mg)
							if mg[:-4] in mgname: ptcls.append(i)
						print(("Found {} boxes for {}".format(len(ptcls),mg)))
						for p in ptcls:
							xc = int(sf[xk][p])
							yc = int(sf[yk][p])
							boxlist.append([xc,yc,'manual'])
						js_open_dict(info_name(mg,nodir=True))["boxes"]=boxlist
						if not "{}.hdf".format(base_name(mg,nodir=True)) in project_micros:
							print("Warning: Imported boxes for {}, but micrographs/{}.hdf does not exist".format(base_name(mg),base_name(mg,nodir=True)))

		else : print("ERROR: Unknown box_type")

	# Import particles
	if options.import_particles:
		if not os.access("particles", os.R_OK):
			os.mkdir("particles")

		fset=set([base_name(i) for i in args])
		if len(fset)!=len(args):
			print("ERROR: You specified multiple files to import with the same base name, eg - a10/abc123.spi and a12/abc123.spi. If you have multiple images with the same \
name, you will need to modify your naming convention (perhaps by prefixing the date) before importing. If the input files are in IMAGIC format, so you have .hed and .img files \
with the same name, you should specify only the .hed files (no renaming is necessary).")
			sys.exit(1)

		for i,fsp in enumerate(args):
			E2progress(logid,float(i)/len(args))
			if EMData(fsp,0,True)["nz"]>1 :
				run("e2proc2d.py {} particles/{}.hdf --threed2twod --inplace".format(fsp,base_name(fsp)))
			else: run("e2proc2d.py {} particles/{}.hdf --inplace".format(fsp,base_name(fsp)))

	if options.import_dark or options.import_gain:
		dgdir = os.path.join(".","darkgain")
		if not os.access(dgdir, os.R_OK):
			os.mkdir(dgdir)

		if options.import_dark:
			darkname=os.path.join(dgdir,os.path.basename(options.import_dark))
			if darkname[-4:] == ".mrc": darkname+="s"

			if options.importation == "move":
				os.rename(options.dark,darkname)
			if options.importation == "copy":
				run("e2proc2d.py {} {} ".format(options.import_dark, darkname))
			if options.importation == "link":
				os.symlink(options.dark,darkname)
			#db=js_open_dict(info_name(newname,nodir=True))
			#db.close()
		
		if options.import_dark:
			gainname=os.path.join(dgdir,os.path.basename(options.import_gain))
			if gainname[-4:] == ".mrc": gainname+="s"

			if options.importation == "move":
				os.rename(options.dark,gainname)
			if options.importation == "copy":
				run("e2proc2d.py {} {} ".format(options.import_gain, gainname))
			if options.importation == "link":
				os.symlink(options.dark,gainname)

			#db=js_open_dict(info_name(newname,nodir=True))
			#db.close()
		
	if options.import_movies:
		moviesdir = os.path.join(".","movies")
		if not os.access(moviesdir, os.R_OK):
			os.mkdir(moviesdir)

		for filename in args:
			newname=os.path.join(moviesdir,os.path.basename(filename))
			if newname[-4:] == ".mrc": newname+="s"
			if options.importation == "move":
				os.rename(filename,newname)
			if options.importation == "copy":
				run("e2proc2d.py {} {} ".format(filename, newname))
			if options.importation == "link":
				os.symlink(filename,newname)
			db=js_open_dict(info_name(newname,nodir=True))
			if options.import_dark: db["ddd_gainref"]=gainname
			if options.import_dark: db["ddd_darkref"]=darkname
			db.close()
		print("Done.")
	
	# Import tomograms
	if options.import_tomos:
		tomosdir = os.path.join(".","tomograms")
		if not os.access(tomosdir, os.R_OK):
			os.mkdir("tomograms")
		for filename in args:
			if options.importation == "move":
				os.rename(filename,os.path.join(tomosdir,os.path.basename(filename)))
			if options.importation == "copy":
				### use hdf file as output

				if options.shrink>1:
					shrinkstr="_bin{:d}".format(options.shrink)
				else:
					shrinkstr=""

				tpos=filename.rfind('.')
				if tpos>0:
					newname=os.path.join(tomosdir,os.path.basename(filename[:tpos]+shrinkstr+'.hdf'))
				else:
					newname=os.path.join(tomosdir,os.path.basename(filename))
				cmd="e2proc3d.py {} {} ".format(filename, newname)
				if options.shrink>1:
					cmd+=" --meanshrink {:d} ".format(options.shrink)
				if options.invert:
					cmd+=" --mult -1 --process normalize "
				if options.tomoseg_auto:
					cmd+=" --process filter.lowpass.gauss:cutoff_abs=.25 --process filter.highpass.gauss:cutoff_pixels=5 --process normalize --process threshold.clampminmax.nsigma:nsigma=3 "
				cmd+=options.preprocess
				run(cmd)
				print("Done.")
				#shutil.copy(filename,os.path.join(tomosdir,os.path.basename(filename)))
			if options.importation == "link":
				os.symlink(filename,os.path.join(tomosdir,os.path.basename(filename)))

	# Import metadata
	if options.import_mdoc:
		mdoc = read_mdoc(options.import_mdoc)
		
		# check and correct project parameters from MDOC file contents
		d = js_open_dict("info/project.json")
		try: d.setval("global.apix",mdoc["PixelSpacing"],deferupdate=True)
		except: pass
		try: d.setval("global.microscope_voltage",mdoc["Voltage"],deferupdate=True)
		except: pass
		d.close()

		raw = [t for t in os.listdir("rawtilts")]
		raw.sort()
		for j,tlt in enumerate(raw):
			for z in range(mdoc["zval"]+1):
				if mdoc[z]["SubFramePath"] in base_name(tlt):
					d = js_open_dict(info_name(tlt))
					for k in mdoc[z].keys():
						d.setval(k,mdoc[z][k],deferupdate=True)
					d.close()
					break

	# Import tilt series
	if options.serialem:

		tomosdir = os.path.join(".","orig")
		if not os.access(tomosdir, os.R_OK):
			os.mkdir("orig")
		for filename in args:
			if options.importation == "move":
				os.rename(filename,os.path.join(tomosdir,os.path.basename(filename)))
			if options.importation == "copy":
				### use hdf file as output
				if options.shrink>1:
					shrinkstr="_bin{:d}".format(options.shrink)
				else:
					shrinkstr=""
				tpos=filename.rfind('.')
				if tpos>0:
					newname=os.path.join(tomosdir,os.path.basename(filename[:tpos]+shrinkstr+'.hdf'))
				else:
					newname=os.path.join(tomosdir,os.path.basename(filename))
				cmd="e2proc3d.py {} {} ".format(filename, newname)
				if options.shrink>1:
					cmd+=" --meanshrink {:d} ".format(options.shrink)
				if options.invert:
					cmd+=" --mult -1 --process normalize "
				if options.tomoseg_auto:
					cmd+=" --process filter.lowpass.gauss:cutoff_abs=.25 --process filter.highpass.gauss:cutoff_pixels=5 --process normalize --process threshold.clampminmax.nsigma:nsigma=3 "
				cmd+=options.preprocess
				run(cmd)
				print("Done.")
				#shutil.copy(filename,os.path.join(tomosdir,os.path.basename(filename)))
			if options.importation == "link":
				os.symlink(filename,os.path.join(tomosdir,os.path.basename(filename)))


	E2end(logid)

def read_mdoc(mdoc):
	movie = {}
	frames = {}
	zval = -1
	frames[zval] = {}
	frames["misc"] = []
	frames["labels"] = []
	with open(mdoc) as mdocf:
		for l in mdocf.readlines():
			p = l.strip()
			if "ZValue" in p:
				zval+=1
				frames[zval] = {}
			elif p != "":
				x,y = p.split("=")[:2]
				x = x.strip()
				if x == "TiltAngle": frames[zval]["tilt_angle"]=y
				elif x == "Magnification": frames[zval]["magnification"] = y
				elif x == "Intensity": frames[zval]["intensity"]=y
				elif x == "SpotSize": frames[zval]["spot_size"]=y
				elif x == "Defocus": frames[zval]["defocus"]=y
				elif x == "ExposureTime": frames[zval]["exposure_time"]=y
				elif x == "Binning": frames[zval]["binning"]=y
				elif x == "ExposureDose": frames[zval]["exposure_dose"]=y
				elif x == "RotationAngle": frames[zval]["rotation_angle"]=y
				elif x == "StageZ": frames[zval]["stage_z"]=y
				elif x == "CameraIndex": frames[zval]["camera_index"]=y
				elif x == "DividedBy2": frames[zval]["divide_by_2"]=y
				elif x == "MagIndex": frames[zval]["mag_index"]=y
				elif x == "TargetDefocus": frames[zval]["target_defocus"]=y
				elif x == "NumSubFrames": frames[zval]["sub_frame_count"]=y
				elif x == "ImageShift": frames[zval]["image_shift"]=y
				elif x == "StagePosition": frames[zval]["stage_position"]=y
				elif x == "MinMaxMean": frames[zval]["min_max_mean"]=y
				elif x == "SubFramePath":
					sfp = base_name(y).split("-")[-1]
					frames[zval]["SubFramePath"]=sfp
				elif x == "DateTime": frames[zval]["date_time"]=y
				elif x == "PixelSpacing": frames["global.apix"] = float(y)
				elif x == "Voltage": frames["global.microscope_voltage"] = float(y)
				elif x == "ImageFile": frames["image_file"] = str(y)
				elif x == "ImageSize": frames["image_size"] = y.split()
				elif x == "DataMode": frames["data_mode"] = y
				elif x == "PriorRecordDose": frames["prior_record_dose"] = y
				elif x == "FrameDosesAndNumber": frames["frame_doses_and_number"] = y
				elif x == "[T": frames["labels"].append(y.replace("]",""))
				elif "PreexposureTime" in x: frames[zval]["preexposure_time"] = y
				elif "TotalNumberOfFrames" in x: frames[zval]["frame_count"] = y
				elif "FramesPerSecond" in x: frames[zval]["frames_per_second"] = y
				elif "ProtectionCoverMode" in x: frames[zval]["protection_cover_mode"] = y
				elif "ProtectionCoverOpenDelay" in x: frames[zval]["protection_cover_open_delay"] = y
				elif "TemperatureDetector" in x: frames[zval]["detector_temperature"] = y
				elif "FaradayPlatePeakReading" in x: frames[zval]["faraday_plate_peak_reading"] = y
				elif "SensorModuleSerialNumber" in x: frames[zval]["sensor_module_serial_number"] = y
				elif "ServerSoftwareVersion" in x: frames[zval]["server_software_version"] = y
				elif "SensorReadoutDelay" in x: frames[zval]["sensor_readout_delay"] = y
				else: frames["misc"].append(y) # catches any missed parameters

	frames["zval"] = zval
	return frames

def run(command):
	"Mostly here for debugging, allows you to control how commands are executed (os.system is normal)"

	print("{}: {}".format(time.ctime(time.time()),command))
	ret=launch_childprocess(command)

	# We put the exit here since this is what we'd do in every case anyway. Saves replication of error detection code above.
	if ret !=0 :
		print("Error running: ",command)
		sys.exit(1)

	return

if __name__ == "__main__":
	main()
