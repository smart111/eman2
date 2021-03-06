#!/usr/bin/env python
from __future__ import print_function

#
# Author: Steven Ludtke, 10/04/2013 (sludtke@bcm.edu)
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
#

# e2classvsproj.py  Steven Ludtke

from EMAN2 import *
from math import *
import os
import sys
import traceback
import Queue

def simfn(jsd,projs,fsp,i,options,verbose):
	# Now find the best match for each particle. We could use e2simmx, but more efficient to just do it in place (though not parallel this way)
	best=None
	ptcl=EMData(fsp,i)
	ptcl.process_inplace("normalize.edgemean")
	vals={}
	for j,proj in enumerate(projs):
		projf=proj.process("filter.matchto",{"to":ptcl})
		aligned=projf.align(options.align[0],ptcl,options.align[1],options.aligncmp[0],options.aligncmp[1])
		if options.ralign != None: # potentially employ refine alignment
			refine_parms=options.ralign[1]
			refine_parms["xform.align2d"] = aligned.get_attr("xform.align2d")
			projf.del_attr("xform.align2d")
			aligned = projf.align(options.ralign[0],ptcl,refine_parms,options.raligncmp[0],options.raligncmp[1])
		
		c=ptcl.cmp(options.cmp[0],aligned,options.cmp[1])
		if best==None or c<best[0] : 
			aptcl=ptcl.process("xform",{"transform":aligned["xform.align2d"].inverse()})
			best=(c,aptcl,projf)
		vals[j]=c
		if options.verbose>2 : print(i,j,c)
	
	if options.verbose>1: print("Class-average {} with projection {}".format(i,str(best[2]["xform.projection"])))

	# return ptcl#, best sim val, aligned ptcl, projection, {per proj sim}
	jsd.put((i,best[0],best[1],best[2],vals))

def main():
	progname = os.path.basename(sys.argv[0])
	usage = """prog [options] <classes> <projection stack or 3Dmap> <output>
	Compares each class-average (or particle) in the classes input stack to each projection in the 'projection stack'. If a
	3-D map is provided as the second input, then projections are generated using the specified angular spacing.

	e2ptclvsmap.py is similar, but also sorts the results """


	parser = EMArgumentParser(usage=usage,version=EMANVERSION)

	parser.add_argument("--ang",type=float,help="Angle between projections if 3Dmap provided",default=10.0)
	parser.add_argument("--sym", dest="sym", default="c1", help="Set the symmetry; if no value is given then the model is assumed to have no symmetry.\nChoices are: i, c, d, tet, icos, or oct.")
	parser.add_argument("--align",type=str,help="The name of an 'aligner' to use prior to comparing the images", default="rotate_translate_flip")
	parser.add_argument("--aligncmp",type=str,help="Name of the aligner along with its construction arguments",default="ccc")
	parser.add_argument("--ralign",type=str,help="The name and parameters of the second stage aligner which refines the results of the first alignment", default="refine")
	parser.add_argument("--raligncmp",type=str,help="The name and parameters of the comparitor used by the second stage aligner. Default is ccc.",default="ccc")
	parser.add_argument("--cmp",type=str,help="The name of a 'cmp' to be used in comparing the aligned images", default="ccc")
	parser.add_argument("--savesim",type=str,default=None,help="Save all of the similarity results to a text file. (ptcl#,proj#,alt,az,sim)")
	parser.add_argument("--threads", default=4,type=int,help="Number of alignment threads to run in parallel on a single computer. This is the only parallelism supported by this program at present.", guitype='intbox', row=24, col=2, rowspan=1, colspan=1, mode="refinement")
	parser.add_argument("--ppid", type=int, help="Set the PID of the parent process, used for cross platform PPID",default=-1)
	parser.add_argument("--verbose", "-v", dest="verbose", action="store", metavar="n", type=int, default=0, help="verbose level [0-9], higner number means higher level of verboseness")

	(options, args) = parser.parse_args()

	if len(args)<3 : parser.error("Input and output files required")

	options.align=parsemodopt(options.align)
	options.aligncmp=parsemodopt(options.aligncmp)
	options.ralign=parsemodopt(options.ralign)
	options.raligncmp=parsemodopt(options.raligncmp)
	options.cmp=parsemodopt(options.cmp)

	# initialize projections either a stack from a file, or by making projections of a 3-D map
	projs=EMData.read_images(args[1])
	if len(projs)==1 :
		mdl=projs[0]
		projs=[]
		if mdl["nz"]==1 : 
			print("Error, you must provide either a stack of 2-D images or a 3-D map as the second argument")
			sys.exit(1)

		print("Generating projections with an angular step of {} and symmetry {}".format(options.ang,options.sym))
		
		E2n=E2init(sys.argv, options.ppid)
		mdl.process_inplace("normalize.edgemean")
		sym_object = parsesym(options.sym)
		eulers = sym_object.gen_orientations("eman", {"delta":options.ang,"inc_mirror":0,"perturb":0})
		for i,euler in enumerate(eulers):
			p=mdl.project("standard",euler)
			p.set_attr("xform.projection",euler)
			p.set_attr("ptcl_repr",0)
			p.process_inplace("normalize.edgemean")
			projs.append(p)
			if options.verbose : print(i,euler)
	else:
		E2n=E2init(sys.argv, options.ppid)
	
	jsd=Queue.Queue(0)
	nptcl=EMUtil.get_image_count(args[0])
	thrds=[threading.Thread(target=simfn,args=(jsd,projs,args[0],i,options,options.verbose)) for i in xrange(nptcl)]

	if options.savesim!=None : out=open(options.savesim,"w")
	
	# here we run the threads and save the results, no actual alignment done here
	print(len(thrds)," threads")
	thrtolaunch=0
	while thrtolaunch<len(thrds) or threading.active_count()>1:
		# If we haven't launched all threads yet, then we wait for an empty slot, and launch another
		# note that it's ok that we wait here forever, since there can't be new results if an existing
		# thread hasn't finished.
		if thrtolaunch<len(thrds) :
			while (threading.active_count()==options.threads ) : time.sleep(.1)
			if options.verbose : print("Starting thread {}/{}".format(thrtolaunch,len(thrds)))
			thrds[thrtolaunch].start()
			thrtolaunch+=1
		else: time.sleep(1)
	
		while not jsd.empty():
			# returns ptcl#, best sim val, aligned ptcl, projection, {per proj sim}
			i,sim,ali,proj,pps=jsd.get()
			ali.write_image(args[2],i*2)
			proj.write_image(args[2],i*2+1)
			if options.savesim:
				for prj in pps.keys():
					xf=projs[prj]["xform.projection"]
					out.write("{}\t{}\t{}\t{}\t{}\n".format(i,prj,xf.get_rotation("eman")["alt"],xf.get_rotation("eman")["az"],pps[prj]))


	for t in thrds:
		t.join()

	E2end(E2n)


if __name__ == "__main__":
    main()
