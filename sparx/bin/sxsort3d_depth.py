#!/usr/bin/env python
#
#
#  08/26/2016
#  New version of sort3D.
#  
from __future__ import print_function

"""
There are two ways to run the program:

1.Import data from a meridien refinement.
mpirun -np 64 --hostfile four_nodes.txt  sxsort3d_depth.py  --refinemet_dir=meridien_run --niter_for_sorting=28  --memory_per_node=100. --img_per_grp=80000  --minimum_grp_size=15000   --stop_mgskmeans_percentage=8. --output_dir=SORT3D

2.Import data from a given data stack.
mpirun  -np 48  --hostfile ./node012.txt  sxsort3d_depth.py --stop_mgskmeans_percentage=15. --orientation_groups=40  --do_swap_au  --swap_ratio=5. --output_dir=sorting_bmask04 --sym=c1   --radius=30  --minimum_grp_size=2000   --img_per_grp=2800    --instack=bdb:data  >sorting_bmask04/printout &

Notices on options:

a. --do_swap_au  --swap_ratio=5.   : Ratio of the elements of determined clusters that are exchanged with the unaccounted elements.
b. --stop_mgskmeans_percentage=15. : criterion to stop Kmeans run.
c. --orientation_groups=50:  user defined number of orientation groups within an asymmetric unit.

Nomenclatures in sorting intermediate results:

NACC:  total number of accounted
NUACC: number of unaccounted
MGU:   user defined minimum_grp_size  
MGR:   random group size
K:     number of groups

"""

import  os
import  sys
import  types
import  global_def
from    global_def import *
from    optparse   import OptionParser
from    sparx      import *
from    EMAN2      import *
from    numpy      import array
from    logger     import Logger, BaseLogger_Files
from    mpi        import  *
from    math  	   import  *
from    random     import  *
import  shutil
import  os
import  sys
import  subprocess
import  time
import  string
import  json
from    sys 	import exit
from    time    import localtime, strftime, sleep
global  Tracker, Blockdata

# ------------------------------------------------------------------------------------
mpi_init(0, [])
nproc     = mpi_comm_size(MPI_COMM_WORLD)
myid      = mpi_comm_rank(MPI_COMM_WORLD)
Blockdata = {}
#  MPI stuff
Blockdata["nproc"]              = nproc
Blockdata["myid"]               = myid
Blockdata["main_node"]          = 0
Blockdata["last_node"]          = nproc -1

Blockdata["shared_comm"]                    = mpi_comm_split_type(MPI_COMM_WORLD, MPI_COMM_TYPE_SHARED,  0, MPI_INFO_NULL)
Blockdata["myid_on_node"]                   = mpi_comm_rank(Blockdata["shared_comm"])
Blockdata["no_of_processes_per_group"]      = mpi_comm_size(Blockdata["shared_comm"])
masters_from_groups_vs_everything_else_comm = mpi_comm_split(MPI_COMM_WORLD, Blockdata["main_node"] == Blockdata["myid_on_node"], Blockdata["myid_on_node"])
Blockdata["color"], Blockdata["no_of_groups"], balanced_processor_load_on_nodes = get_colors_and_subsets(Blockdata["main_node"], MPI_COMM_WORLD, Blockdata["myid"], \
         Blockdata["shared_comm"], Blockdata["myid_on_node"], masters_from_groups_vs_everything_else_comm)
         
#  We need two nodes for processing of volumes
if(Blockdata["no_of_groups"] > 1):
	Blockdata["node_volume"] = [Blockdata["no_of_groups"]-2, Blockdata["no_of_groups"]-1]
	#Blockdata["nodes"] = [Blockdata["no_of_groups"]-2, Blockdata["no_of_groups"]-1]  # For 3D stuff take last two nodes
else: 
	Blockdata["node_volume"] = [0, 0]
#  We need two CPUs for processing of volumes, they are taken to be main CPUs on each volume
#  We have to send the two myids to all nodes so we can identify main nodes on two selected groups.
if(Blockdata["no_of_groups"] > 1): Blockdata["main_shared_nodes"] = [Blockdata["node_volume"][0]*Blockdata["no_of_processes_per_group"],Blockdata["node_volume"][1]*Blockdata["no_of_processes_per_group"]]
else:  Blockdata["main_shared_nodes"] = [0, 1]
Blockdata["nproc_previous"]  = 0
# End of Blockdata: sorting requires at least three nodes, and the used number of nodes be integer times of three
global_def.BATCH = True
global_def.MPI   = True
global _proc_status, _scale, is_unix_cluster
try:			
	_proc_status = '/proc/%d/status' % os.getpid()
	_scale = {'kB': 1024.0, 'mB': 1024.0*1024.0,'KB': 1024.0, 'MB': 1024.0*1024.0}
	is_unix_cluster = True
except:
	if Blockdata["myid"]==Blockdata["main_node"]:print("Not a unix machine")
	is_unix_cluster = False
	
def create_subgroup():
	# select a subset of myids to be in subdivision
	if( Blockdata["myid_on_node"] < Blockdata["ncpuspernode"] ): submyids = [Blockdata["myid"]]
	else:  submyids = []
	submyids = wrap_mpi_gatherv(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	submyids = wrap_mpi_bcast(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	#if( Blockdata["myid"] == Blockdata["main_node"] ): print(submyids)
	world_group = mpi_comm_group(MPI_COMM_WORLD)
	subgroup = mpi_group_incl(world_group,len(submyids),submyids)
	Blockdata["subgroup_comm"] = mpi_comm_create(MPI_COMM_WORLD, subgroup)
	mpi_barrier(MPI_COMM_WORLD)
	Blockdata["subgroup_size"] = -1
	Blockdata["subgroup_myid"] = -1
	if (MPI_COMM_NULL != Blockdata["subgroup_comm"]):
		Blockdata["subgroup_size"] = mpi_comm_size(Blockdata["subgroup_comm"])
		Blockdata["subgroup_myid"] = mpi_comm_rank(Blockdata["subgroup_comm"])
	#  "nodes" are zero nodes on subgroups on the two "node_volume" that compute backprojection
	Blockdata["nodes"] = [Blockdata["node_volume"][0]*Blockdata["ncpuspernode"], Blockdata["node_volume"][1]*Blockdata["ncpuspernode"]]
	mpi_barrier(MPI_COMM_WORLD)
	return
	
def create_zero_group():
	# select a subset of myids to be in subdivision, This is a group of all zero IDs on nodes, taken from isac2
	if( Blockdata["myid_on_node"] == 0 ): submyids = [Blockdata["myid"]]
	else:  submyids = []

	submyids = wrap_mpi_gatherv(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	submyids = wrap_mpi_bcast(submyids, Blockdata["main_node"], MPI_COMM_WORLD)
	#if( Blockdata["myid"] == Blockdata["main_node"] ): print(submyids)
	world_group = mpi_comm_group(MPI_COMM_WORLD)
	subgroup = mpi_group_incl(world_group,len(submyids),submyids)
	#print(" XXX world group  ",Blockdata["myid"],world_group,subgroup)
	Blockdata["group_zero_comm"] = mpi_comm_create(MPI_COMM_WORLD, subgroup)
	mpi_barrier(MPI_COMM_WORLD)
	#print(" ZZZ subgroup  ",Blockdata["myid"],world_group,subgroup,subgroup_comm)

	Blockdata["group_zero_size"] = -1
	Blockdata["group_zero_myid"] = -1
	if (MPI_COMM_NULL != Blockdata["group_zero_comm"]):
		Blockdata["group_zero_size"] = mpi_comm_size(Blockdata["group_zero_comm"])
		Blockdata["group_zero_myid"] = mpi_comm_rank(Blockdata["group_zero_comm"])
	#  "nodes" are zero nodes on subgroups on the two "node_volume" that compute backprojection
	#Blockdata["nodes"] = [Blockdata["node_volume"][0]*Blockdata["ncpuspernode"], Blockdata["node_volume"][1]*Blockdata["ncpuspernode"]]
	mpi_barrier(MPI_COMM_WORLD)
	return
	
### restart

def check_restart_from_given_depth_order(current_depth_order,  restart_from_generation, \
     restart_from_depth_order_init, restart_from_nbox_init, log_main):
	global Tracker, Blockdata
	import shutil
	from   logger import Logger, BaseLogger_Files
	
	keepgoing                = 1
	restart_from_depth_order = max(0, restart_from_depth_order_init)
	restart_from_nbox        = max(0, restart_from_nbox_init)
	
	log_main = Logger(BaseLogger_Files())
	log_main.prefix = Tracker["constants"]["masterdir"]+"/"
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		if not os.path.exists(Tracker["constants"]["masterdir"]):
			print("masterdir does not exist")
			keepgoing = 0
		
	keepgoing = bcast_number_to_all(keepgoing, Blockdata["main_node"], MPI_COMM_WORLD)
	if keepgoing == 0:
		 ERROR("masterdir does not exist", "restart from depth order", 1, Blockdata["myid"])
	 
	if(Blockdata["myid"] == Blockdata["main_node"]):
		if not os.path.exists(os.path.join(Tracker["constants"]["masterdir"]), "Tracker.json"):
			print("Tracker.json in masterdir does not exist")
			keepgoing = 0
		
	keepgoing = bcast_number_to_all(keepgoing, Blockdata["main_node"], MPI_COMM_WORLD)
	if keepgoing == 0:
		 ERROR("Tracker does not exist", "restart from depth order", 1, Blockdata["myid"])
		 
	sort3d_utils("load_tracker", log_main =  log_main)
	if(Blockdata["myid"] == Blockdata["main_node"]):
		keepchecking = 1
		msg = "previous depth order: %d  current depth order: %d"%(Tracker["constants"]["depth_order"], current_depth_order)
		log_main.add(msg)
		
		if current_depth_order >Tracker["constants"]["depth_order"]:
			Tracker["constants"]["depth_order"] = current_depth_order #
		# remove the directories after specified ones
		
		for idepth in xrange(Tracker["constants"]["depth_order"]):
			depth_dir = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%restart_from_generation, "layer%d"%idepth)
			n_cluster_boxes = 2**(current_depth_order - idepth)
			if idepth > restart_from_depth_order:
				if os.path.exists(depth_dir):
					shutil.rmtree(depth_dir)
					
			elif idepth == restart_from_depth_order:
				if os.path.exists(depth_dir):
					keepchecking = check_sorting_state(depth_dir, keepchecking, log_file)
					if keepchecking ==1:
						for ibox in xrange(n_cluster_boxes):
							box_dir = os.path.join(depth_dir, "nbox%d"%ibox)
							if ibox>= restart_from_nbox:
								if os.path.exists(box_dir): shutil.rmtree(box_dir)
							else:
								checking_box  =1 
								checking_box = check_sorting_state(depth_dir, checking_box, log_file)
								if checking_box == 0: shutil.rmtree(box_dir)
				else:
					msg = "%d layer has not been created"%idepth
					print(msg)
					log_main.add(msg)
					break
			else: continue
	else: Tracker = 0
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
	return
			
######### depth clustering functions
def depth_clustering(work_dir, depth_order, initial_id_file, params, previous_params, log_main):
	global Tracker, Blockdata
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]):
		msg_pipe = '----------------------------------'
		msg      = '  >>>>> depth_clustering <<<<<<<  '
		print(line,msg_pipe)
		print(line, msg)
		print(line,msg_pipe)
		log_main.add(msg_pipe)
		log_main.add(msg)
		log_main.add(msg_pipe)
	keepchecking   = 1
	init_layer_dir = os.path.join(work_dir, "layer0")
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if not os.path.exists(init_layer_dir): os.mkdir(init_layer_dir)
		#msg = "depth_clustering starts"
		#log_main.add(msg)
		#print(line, msg)
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		partition_per_box_per_layer_list = []
		initial_id_list = read_text_file(initial_id_file)
		for iparti in xrange(0, 2**(depth_order+1), 2):
			reassign = [initial_id_list, None]
			partition_per_box_per_layer_list.append(reassign)
	else: partition_per_box_per_layer_list = 0
	partition_per_box_per_layer_list = wrap_mpi_bcast(partition_per_box_per_layer_list, Blockdata["main_node"])
	
	Tracker["depth"] = 0
	for depth in xrange(depth_order): #  layers, depth_order = 1 means one layer and two boxes.
		time_layer_start = time.time()
		n_cluster_boxes  = 2**(depth_order - depth)
		depth_dir        = os.path.join(work_dir, "layer%d"%depth)
		Tracker["depth"] = depth
		if(Blockdata["myid"] == Blockdata["main_node"]):
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			msg = 'depth layer %d contains %d boxes, and each box has two MGSKmeans runs \n'%(depth,n_cluster_boxes) 
			print(line, msg)
			log_main.add(msg)
			if not os.path.exists(depth_dir): 
				os.mkdir(depth_dir)
				keepchecking = 0
				mark_sorting_state(depth_dir, False, log_main)
			else: 
				keepchecking = check_sorting_state(depth_dir, keepchecking, log_main)
				if keepchecking == 0: mark_sorting_state(depth_dir, False, log_main)
		else: keepchecking = 0
		keepchecking = bcast_number_to_all(keepchecking, Blockdata["main_node"], MPI_COMM_WORLD)
		## box loop
		if keepchecking == 0:
			checkingbox = 1
			Tracker["box_nxinit"]      = -1
			Tracker["box_nxinit_freq"] = -1.0
			for nbox in xrange(n_cluster_boxes):
				input_accounted_file   = partition_per_box_per_layer_list[nbox][0]
				input_unaccounted_file = partition_per_box_per_layer_list[nbox][1]
				nbox_dir = os.path.join(depth_dir, "nbox%d"%nbox)
				if(Blockdata["myid"] == Blockdata["main_node"]):
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					if not os.path.exists(nbox_dir):
						os.mkdir(nbox_dir)
						checkingbox = 0
						mark_sorting_state(nbox_dir, False, log_main)
					else:
						checkingbox = check_sorting_state(nbox_dir, checkingbox, log_main)
						if checkingbox == 0:# found not finished box
							line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
							msg ="box %d is not finished. Remove it and recompute..."%nbox
							print(line, msg)
							log_main.add(msg)
							shutil.rmtree(nbox_dir)
							os.mkdir(nbox_dir)
							mark_sorting_state(nbox_dir, False, log_main)	
				else: checkingbox = 0
				checkingbox = bcast_number_to_all(checkingbox, Blockdata["main_node"], MPI_COMM_WORLD)
				# Code structure of the box
				if checkingbox == 0:
					depth_clustering_box(nbox_dir, input_accounted_file, input_unaccounted_file, params, previous_params, nbox, log_main)
					if(Blockdata["myid"] == Blockdata["main_node"]): mark_sorting_state(nbox_dir, True, log_main)
				else: continue
			partition_per_box_per_layer_list = []
			if(Blockdata["myid"] == Blockdata["main_node"]):
				stop_generation = 0
				for nbox in xrange(0,n_cluster_boxes,2):
					input_box_parti1 = os.path.join(depth_dir, "nbox%d"%nbox,     "partition.txt")
					input_box_parti2 = os.path.join(depth_dir, "nbox%d"%(nbox+1), "partition.txt")
					minimum_grp_size, maximum_grp_size, accounted_list, unaccounted_list, bad_clustering, stop_generation = \
					do_boxes_two_way_comparison_new(nbox, input_box_parti1, input_box_parti2, depth_order - depth, log_main)
					if stop_generation ==1:
						partition_per_box_per_layer_list = []
						partition_per_box_per_layer_list.append([accounted_list, unaccounted_list])
						break
					else:partition_per_box_per_layer_list.append([accounted_list, unaccounted_list])
			else: 
				partition_per_box_per_layer_list = 0
				bad_clustering   = 0
				Tracker          = 0
				stop_generation  = 0
			partition_per_box_per_layer_list = wrap_mpi_bcast(partition_per_box_per_layer_list, Blockdata["main_node"], MPI_COMM_WORLD)
			bad_clustering = bcast_number_to_all(bad_clustering, Blockdata["main_node"], MPI_COMM_WORLD)
			stop_generation = bcast_number_to_all(stop_generation, Blockdata["main_node"], MPI_COMM_WORLD)
			Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
			if(Blockdata["myid"] == Blockdata["main_node"]): mark_sorting_state(depth_dir, True, log_main)
			if bad_clustering ==1:
				msg = "No cluster is found and sorting stops"
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				if(Blockdata["myid"] == Blockdata["main_node"]):
					print(line, msg)
					log_main.add(msg)
				from mpi import mpi_finalize
				mpi_finalize()
				exit()
			if stop_generation == 1: break ### only one cluster survives 
		else:
			if(Blockdata["myid"] == Blockdata["main_node"]):
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				msg  = "depth layer %d is done  "%depth
				print(line, msg)
				log_main.add(msg)
		time_of_sorting_h,  time_of_sorting_m = get_time(time_layer_start)
		if Blockdata["myid"] == Blockdata["main_node"]:
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			msg = "layer %d costs time %d hours %d minutes"%(depth, time_of_sorting_h, time_of_sorting_m)
			log_main.add(msg +'\n')
			print(msg +'\n')
			
	if(Blockdata["myid"] == Blockdata["main_node"]):
		msg = " depth_clustering finishes \n"
		print(msg)
		log_main.add(msg)
	return partition_per_box_per_layer_list

def depth_box_initialization(box_dir, input_list1, input_list2, log_file):
	global Tracker, Blockdata
	img_per_grp  = Tracker["constants"]["img_per_grp"]
	if input_list2 is not None: #Track 2
		total_stack = len(input_list1)+ len(input_list2)
		groups = []
		for one in input_list1:
			if one[0] not in groups: groups.append(one[0]) # safe in speed when the number of groups is not large.
		number_of_groups = len(groups)
		if number_of_groups< total_stack//img_per_grp: number_of_groups = total_stack//img_per_grp
		minimum_grp_size = Tracker["constants"]["minimum_grp_size"]
		if Blockdata["myid"] == Blockdata["main_node"]:
			msg = "intialization found %d  groups, the total possible groups  %d"%(number_of_groups, total_stack//img_per_grp)
			print(msg)
			log_file.add(msg)
			write_text_row(input_list1, os.path.join(box_dir, "previous_NACC.txt"))
			write_text_file(input_list2, os.path.join(box_dir, "previous_NUACC.txt"))
		mpi_barrier(MPI_COMM_WORLD)
		
		if Tracker["constants"]["do_swap_au"]: swap_ratio = Tracker["constants"]["swap_ratio"]
		else: swap_ratio = 0.0
		new_assignment = []
		for indep in xrange(2):
			tmp_assignment = swap_accounted_with_unaccounted_elements_mpi(os.path.join(box_dir, "previous_NACC.txt"), \
				os.path.join(box_dir, "previous_NUACC.txt"), log_file, number_of_groups, swap_ratio)
			new_assignment.append(tmp_assignment)
		if Blockdata["myid"] == Blockdata["main_node"]:
			for indep in xrange(2):
				write_text_file(new_assignment[indep], os.path.join(box_dir, "independent_index_%03d.txt"%indep))
			new_assignment = []
			for indep in xrange(2):
				new_assignment.append(read_text_row(os.path.join(box_dir,"independent_index_%03d.txt"%indep)))
			id_list = read_text_file( os.path.join(box_dir, "independent_index_000.txt"), -1)
			if len(id_list)>1: id_list=id_list[0]
			total_stack = len(id_list)
			number_of_groups = max(id_list)+1 # assume K be 0, ...,number_of_groups-1
		else:
			number_of_groups = 0
			total_stack      = 0
			new_assignment   = 0
		new_assignment = wrap_mpi_bcast(new_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		number_of_groups = bcast_number_to_all(number_of_groups, Blockdata["main_node"], MPI_COMM_WORLD)
		total_stack = bcast_number_to_all(total_stack, Blockdata["main_node"], MPI_COMM_WORLD)
		
	else: #Tracker 1
		total_stack = len(input_list1)
		if Blockdata["myid"] == Blockdata["main_node"]:
			write_text_file(input_list1, os.path.join(box_dir, "previous_all_indexes.txt"))
		number_of_groups = total_stack//img_per_grp
		if number_of_groups <= 1:
			number_of_groups = total_stack//Tracker["constants"]["minimum_grp_size"] -1
		new_assignment = create_nrandom_lists_from_given_pids(box_dir, os.path.join(box_dir, \
		      "previous_all_indexes.txt"), number_of_groups, 2)
		minimum_grp_size = Tracker["constants"]["minimum_grp_size"]
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		msg = "depth_box_initialization  total_stack  %d number_of_groups  %d  minimum_grp_size  %d"%(total_stack, number_of_groups, minimum_grp_size)
		log_file.add(msg)
	mpi_barrier(MPI_COMM_WORLD)		
	
	return img_per_grp, number_of_groups, total_stack, minimum_grp_size, new_assignment
	
def depth_iter_initialization(run_id_file):
	id_list          = read_text_file(run_id_file, -1)
	number_of_groups = max(id_list[0])+1
	total_stack      = len(id_list[0])
	return total_stack, number_of_groups
	
def output_iter_results(box_dir, ncluster, NACC, NUACC, minimum_grp_size, list_of_stable, unaccounted_list, log_main):
	### single node
	line     = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	
	new_list = []
	nc       = 0
	NACC     = 0
	try:
		fout = open(os.path.join(current_dir,"freq_cutoff.json"),'r')
		freq_cutoff_dict = convert_json_fromunicode(json.load(fout))
		fout.close()
	except: freq_cutoff_dict = {}
	
	msg ='+++ Save iteration results: group size smaller than %d will be set as an empty group +++'%minimum_grp_size
	print(line, msg)
	log_main.add(msg)
	
	for index_of_any in xrange(len(list_of_stable)):
		any = list_of_stable[index_of_any]
		any.tolist()
		if len(any) >= minimum_grp_size:
			any.sort()
			new_list.append(any)
			msg = 'cluster %d  with size %d is saved '%(index_of_any, len(any))
			log_main.add(msg)
			print(line, msg)
			write_text_file(any, os.path.join(box_dir, "Cluster_%03d.txt"%ncluster))
			freq_cutoff_dict["Cluster_%03d.txt"%ncluster] = Tracker["freq_fsc143_cutoff"]
			ncluster += 1
			nc       += 1
			NACC +=len(any)
		else:
			msg ='group %d with size %d is rejected because of size smaller than minimum_grp_size %d and elements are sent back into unaccounted ones'%(index_of_any, len(any), minimum_grp_size)
			log_main.add(msg)
			print(line, msg)
			for element in any: unaccounted_list.append(element)
	unaccounted_list.sort()
	NUACC = len(unaccounted_list)
	fout = open(os.path.join(box_dir, "freq_cutoff.json"),'w')
	json.dump(freq_cutoff_dict, fout)
	fout.close()
	msg = '+++++++++++++++++++++++++++++++++++++++++++++++++++++++++'
	print(line, msg)
	log_main.add(msg)
	return ncluster, NACC, NUACC, unaccounted_list, nc
	
def check_state_within_box_run(keepgoing, nruns, img_per_grp, minimum_grp_size, unaccounted_list, no_cluster_last_run):
	global Tracker, Blockdata
	total_stack = len(unaccounted_list)
	
	if total_stack//img_per_grp <=1:
		number_of_groups = 2
		if total_stack/float(Tracker["constants"]["minimum_grp_size"]) <= 2.0: 
			keepgoing = 0 # otherwise sorting will fall into endless loop
		else: number_of_groups = total_stack//Tracker["constants"]["minimum_grp_size"]-1
	else: number_of_groups = total_stack//img_per_grp
	
	if keepgoing ==1: nruns +=1
	else:
		total_stack      = 0
		number_of_groups = 0
	if no_cluster_last_run: number_of_groups -=1
	if number_of_groups<=1 : keepgoing = 0
	return keepgoing, nruns, total_stack, number_of_groups
	
def get_box_partition(box_dir, ncluster, unaccounted_list):
	if ncluster >=1:
		unaccounted_list.sort()
		clusters_in_box = []
		for ic in xrange(ncluster):
			one_cluster = read_text_file(os.path.join(box_dir, "Cluster_%03d.txt"%ic))
			clusters_in_box.append(one_cluster)
		if len(unaccounted_list)>0: clusters_in_box.append(unaccounted_list)
		alist, plist = merge_classes_into_partition_list(clusters_in_box)
	else: plist = []
	return plist
		
def get_box_partition_reassign(input_list):
	global Tracker, Blockdata
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		plist            = input_list[0][0]
		unaccounted_list = input_list[0][1]
		clusters, npart  = split_partition_into_ordered_clusters(plist)
		if len(unaccounted_list)>1: unaccounted_list.sort()
		total_stack = len(plist)+len(unaccounted_list)
	else:
		unaccounted_list = 0
		clusters         = 0
		total_stack      = 0
	clusters         = wrap_mpi_bcast(clusters, Blockdata["main_node"],         MPI_COMM_WORLD)
	unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
	total_stack      = bcast_number_to_all(total_stack, Blockdata["main_node"], MPI_COMM_WORLD)
	
	if len(unaccounted_list)> 0:
		if len(unaccounted_list)>100*Blockdata["nproc"]:
			clusters  = assign_unaccounted_elements_mpi(\
				unaccounted_list, clusters, total_stack)
			dlist, assignment_list = merge_classes_into_partition_list(clusters)
		else:
			if Blockdata["myid"] == Blockdata["main_node"]: clusters = \
			              assign_unaccounted_elements(unaccounted_list, clusters, total_stack)
			else: clusters = 0
			clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			dlist, assignment_list = merge_classes_into_partition_list(clusters)
	else: dlist, assignment_list = merge_classes_into_partition_list(clusters)
	return assignment_list, len(clusters)
		
def output_clusters(output_dir, partition, unaccounted_list, not_include_unaccounted, log_main):
	global Tracker, Blockdata
	import copy
	### single cpu function
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	nclasses, npart = split_partition_into_ordered_clusters(partition)
	nc = 0
	identified_clusters = []
	msg = '++++++++++++++++++++++output cluster text file++++++++++++++++++++++++++++++++++'
	log_main.add(msg)
	print(line,msg)
	msg = 'write the determined clusters as Cluster*.txt on each generation directory'
	log_main.add(msg)
	print(line, msg)
	for ic in xrange(len(nclasses)):
		if len(nclasses[ic])>= Tracker["constants"]["minimum_grp_size"]:
			write_text_file(nclasses[ic], os.path.join(output_dir,"Cluster_%03d.txt"%nc))
			msg = 'save cluster with size %d  to %s '%(len(nclasses[ic]), os.path.join(output_dir,"Cluster_%03d.txt"%nc))
			log_main.add(msg)
			print(line, msg)
			nc +=1
			identified_clusters.append(nclasses[ic])
		else: unaccounted_list +=nclasses[ic]
		
	if len(unaccounted_list)>1: 
		unaccounted_list.sort()
		write_text_file(unaccounted_list, os.path.join(output_dir, "Unaccounted.txt"))
		msg = 'save unaccounted with size %d  to %s '%(len(unaccounted_list),  os.path.join(output_dir, "Unaccounted.txt"))
		log_main.add(msg)
		print(line, msg)
	nclasses = copy.deepcopy(identified_clusters)
	del identified_clusters
	
	if len(unaccounted_list)>1:
		if not not_include_unaccounted:
			write_text_file(unaccounted_list, os.path.join(output_dir,"Cluster_%03d.txt"%nc))
			msg  ="the Cluster_%03d.txt contains unaccounted ones"%nc
			log_main.add(msg +'\n')
			print(line, msg +'\n')
	else:
		msg = ' '
		log_main.add(msg +'\n')
		print(line, msg +'\n')
		
	do_analysis_on_identified_clusters(nclasses, log_main)
	
	if not not_include_unaccounted:
		import copy
		unclasses = copy.deepcopy(nclasses)
		unclasses.append(unaccounted_list)
		alist, partition = merge_classes_into_partition_list(unclasses)
		del unclasses
	else: alist, partition = merge_classes_into_partition_list(nclasses)
	write_text_row(partition, os.path.join(output_dir, "final_partition.txt"))
	msg = '+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++'
	log_main.add(msg)
	return nclasses
	
def do_analysis_on_identified_clusters(clusters, log_main):
	global Tracker, Blockdata
	summary = []
	dummy = output_micrograph_number_per_cluster(Tracker["constants"]["orgstack"], \
		os.path.join(Tracker["constants"]["masterdir"], "indexes.txt"), clusters, log_main = log_main)
		   
	if Tracker["nosmearing"]:
		vs, ds, ss, norms = get_params_for_analysis(Tracker["constants"]["orgstack"], \
		os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt"),\
		 None, None)
	else:
		vs, ds, ss, norms = get_params_for_analysis(Tracker["constants"]["orgstack"], \
		os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt"),\
		 os.path.join(Tracker["constants"]["masterdir"], "all_smearing.txt"), Tracker["constants"]["nsmear"])

	tmpres1, tmpres2, summary = do_one_way_anova_scipy(clusters, ds, name_of_variable="defocus", summary= summary, log_main = log_main)
	if ss is not None: tmpres1, tmpres2, summary = do_one_way_anova_scipy(clusters, ss, name_of_variable="smearing", summary= summary, log_main = log_main)
	if norms:          tmpres1, tmpres2, summary = do_one_way_anova_scipy(clusters, norms, name_of_variable="norm", summary= summary, log_main = log_main)
	if summary is not None:
		fout = open(os.path.join(Tracker["constants"]["masterdir"], "anova_summary.txt"),"w")
		fout.writelines(summary)
		fout.close()
	else:
		msg = "anova is not computed"
		print(msg)
		log_main.add(msg)
	return 
	
def check_sorting_state(current_dir, keepchecking, log_file):
	# single processor job
	import json
	try:
		fout = open(os.path.join(current_dir, "state.json"),'r')
		current_state = convert_json_fromunicode(json.load(fout))
		fout.close()
		if current_state["done"]: 
			keepchecking = 1
			#msg = "directory %s is done already"%current_dir
			#log_file.add(msg)
		else:  
			keepchecking = 0
			#msg = "directory %s is not finished yet"%current_dir
			#log_file.add(msg)
	except:
		keepchecking = 0
		#msg = "directory %s is not finished yet"%current_dir
		#log_file.add(msg)
	return keepchecking
	
def read_tracker_mpi(current_dir, log_file):
	global Tracker, Blockdata
	open_tracker = 1
	if(Blockdata["myid"] == Blockdata["main_node"]):
		try:
			fout    = open(os.path.join(current_dir, "Tracker.json"),'r')
			Tracker = convert_json_fromunicode(json.load(fout))
			fout.close()
		except:
			open_tracker = 0
			msg = "fail in opening Tracker.json"
			log_file.add(msg)
	else: open_tracker = 0
	open_tracker =  bcast_number_to_all(open_tracker, Blockdata["main_node"], MPI_COMM_WORLD)
	if open_tracker ==1:
		if(Blockdata["myid"] != Blockdata["main_node"]): Tracker = 0
		Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
	return		

def mark_sorting_state(current_dir, sorting_done, log_file):
	# single processor job
	import json
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	current_state = {}
	fout = open(os.path.join(current_dir, "state.json"),'w')
	if sorting_done: current_state["done"] = True
	else: current_state["done"] = False
	json.dump(current_state, fout)
	fout.close()
	#if sorting_done: msg = "directory %s is marked as done"%current_dir
	#else:    msg = "directory %s is marked as not finished"%current_dir
	#log_file.add(msg)
	#print(line, msg)
	return

def depth_clustering_box(work_dir, input_accounted_file, input_unaccounted_file, params, previous_params, nbox, log_main):
	global Tracker, Blockdata
	from utilities import read_text_file, wrap_mpi_bcast, write_text_file, write_text_row
	import copy
	import shutil
	from   shutil import copyfile
	from   math   import sqrt
	import time
	box_niter = 5
	if(Blockdata["myid"] == Blockdata["main_node"]):
		if not os.path.exists(work_dir): os.mkdir(work_dir)
		freq_cutoff_dict = {}
		fout = open(os.path.join(work_dir, "freq_cutoff.json"),'w')
		json.dump(freq_cutoff_dict, fout)
		fout.close()
		msg_pipe = '-------------------------------------------' 
		msg      = '  >>>>>>depth_clustering_box %d<<<<<<  '%nbox
		log_main.add(msg_pipe)
		log_main.add(msg)
		log_main.add(msg_pipe +'\n')
		
	### ------- Initialization
	ncluster  = 0
	nruns     = 0
	keepgoing = 1
	converged = 0
	####
	img_per_grp, number_of_groups_init, total_stack_init, minimum_grp_size_init, new_assignment = \
	   depth_box_initialization(work_dir, input_accounted_file, input_unaccounted_file, log_main)
	NUACC = total_stack_init
	NACC  = 0
	####<<<<--------------------------
	assignment_list = new_assignment[:]
	within_box_run_dir = os.path.join(work_dir, "run%d"%nruns)
	if Blockdata["myid"] == Blockdata["main_node"]:
		if not os.path.exists(within_box_run_dir):os.mkdir(within_box_run_dir)
		time_box_start = time.time()
	total_stack      = total_stack_init
	number_of_groups = number_of_groups_init
	while keepgoing ==1:
		######<<<<<----iter initialization
		iter                = 0
		previous_iter_ratio = 0.0
		current_iter_ratio  = 0.0
		iter_dir = os.path.join(within_box_run_dir, "iter%d"%iter)
		if Blockdata["myid"] == Blockdata["main_node"]:
			if not os.path.exists(iter_dir):os.mkdir(iter_dir)
			for indep in xrange(2):
				write_text_row(assignment_list[indep], \
				    os.path.join(iter_dir, "random_assignment_%03d.txt"%indep))
		mpi_barrier(MPI_COMM_WORLD)
		
		iter_id_init_file = os.path.join(iter_dir, "random_assignment_000.txt")
		if Blockdata["myid"] == Blockdata["main_node"]:
			iter_total_stack, iter_number_of_groups = depth_iter_initialization(iter_id_init_file)
		else:
			iter_total_stack      = 0
			iter_number_of_groups = 0
			
		iter_total_stack      = bcast_number_to_all(iter_total_stack, Blockdata["main_node"],      MPI_COMM_WORLD)
		iter_number_of_groups = bcast_number_to_all(iter_number_of_groups, Blockdata["main_node"], MPI_COMM_WORLD)
		total_stack           = iter_total_stack
		current_number_of_groups      = iter_number_of_groups
		
		if Blockdata["myid"] == Blockdata["main_node"]:
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			msg  = "before run %3d current NACC: %8d  NUACC: %8d K: %3d  total_stack: %8d identified clusters: %3d"%\
			   (nruns, NACC, NUACC, current_number_of_groups, total_stack, ncluster)
			log_main.add(msg)
			print(line, msg)
			
		#### computation starts! <<<<<<---prepare data
		original_data, norm_per_particle  = read_data_for_sorting(iter_id_init_file, params, previous_params)
		
		if Tracker["nosmearing"]:
			parameterstructure  = None
			paramstructure_dict = None
			paramstructure_dir  = None
		else:
			paramstructure_dict = Tracker["paramstructure_dict"]
			paramstructure_dir  = Tracker["paramstructure_dir"]
			parameterstructure  = read_paramstructure_for_sorting(iter_id_init_file, paramstructure_dict, paramstructure_dir)
		mpi_barrier(MPI_COMM_WORLD)	
		Tracker["directory"] = within_box_run_dir
		if nruns == 0: # only do it in the first box
			if Tracker["box_nxinit"] ==-1:
				Tracker["nxinit"], Tracker["freq_fsc143_cutoff"] = get_sorting_image_size(original_data, iter_id_init_file, current_number_of_groups,\
					parameterstructure, norm_per_particle, log_main)
				Tracker["box_nxinit"]      = Tracker["nxinit"]
				Tracker["box_nxinit_freq"] = Tracker["freq_fsc143_cutoff"]
			else: 
				Tracker["nxinit"]             = Tracker["box_nxinit"]
				Tracker["freq_fsc143_cutoff"] = Tracker["box_nxinit_freq"]
		else: # nruns>1 always estimate image size
			Tracker["nxinit"], Tracker["freq_fsc143_cutoff"] = get_sorting_image_size(original_data, iter_id_init_file, current_number_of_groups,\
				parameterstructure, norm_per_particle, log_main)
		Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
			
		### preset variables in trackers
		Tracker["total_stack"]      = total_stack
		Tracker["number_of_groups"] = current_number_of_groups
		minimum_grp_size = minimum_grp_size_init
		iter_previous_iter_ratio = 0.0
		iter_current_iter_ratio  = 0.0
		while iter <= box_niter and converged == 0:
			for indep_run_iter in xrange(2):
				Tracker["directory"] = os.path.join(iter_dir, "MGSKmeans_%03d"%indep_run_iter)
				MGSKmeans_index_file = os.path.join(iter_dir, "random_assignment_%03d.txt"%indep_run_iter)
				if Blockdata["myid"] == Blockdata["main_node"]:
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					msg =  "within_box_indep_run_iter %d"%indep_run_iter
					print(line, msg)
					log_main.add(msg)
					if not os.path.exists(Tracker["directory"]):os.mkdir(Tracker["directory"])
					if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
				mpi_barrier(MPI_COMM_WORLD)
				if Tracker["constants"]["relax_oriens"]:
					tmp_final_list, premature =  Kmeans_minimum_group_size_relaxing_orien_groups(original_data, MGSKmeans_index_file, \
					   params, parameterstructure, norm_per_particle, minimum_grp_size, clean_volumes= True)
				else: 
					tmp_final_list, premature =  Kmeans_minimum_group_size_orien_groups(original_data, MGSKmeans_index_file, \
					   params, parameterstructure, norm_per_particle, minimum_grp_size, clean_volumes= True)
					   
				if Blockdata["myid"] == Blockdata["main_node"]:
					write_text_row(tmp_final_list, os.path.join(iter_dir, "partition_%03d.txt"%indep_run_iter))
				mpi_barrier(MPI_COMM_WORLD)
				
			if Blockdata["myid"] == Blockdata["main_node"]:
				minimum_grp_size1, maximum_grp_size1, list_of_stable, unaccounted_list, iter_current_iter_ratio, selected_number_of_groups = \
				do_withinbox_two_way_comparison(iter_dir, nbox, nruns, iter, log_main) # two partitions are written in partition_dir as partition_%03d.txt
			else: 
				unaccounted_list =  0
				list_of_stable   =  0
				minimum_grp_size1 = 0
				Tracker = 0
			minimum_grp_size1 = bcast_number_to_all(minimum_grp_size1, Blockdata["main_node"], MPI_COMM_WORLD)
			unaccounted_list  = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"])
			list_of_stable    = wrap_mpi_bcast(list_of_stable, Blockdata["main_node"], MPI_COMM_WORLD)
			Tracker           = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
			
			accounted_file    = os.path.join(iter_dir, "Accounted.txt")
			unaccounted_file  = os.path.join(iter_dir, "Unaccounted.txt")
			
			if Tracker["constants"]["do_swap_au"]: swap_ratio = Tracker["constants"]["swap_ratio"]
			else: swap_ratio = 0.0
			new_assignment_list = []
			
			for indep in xrange(2):
				tmp_list = swap_accounted_with_unaccounted_elements_mpi(accounted_file, unaccounted_file, \
					log_main, current_number_of_groups, swap_ratio)
				new_assignment_list.append(tmp_list)
				
			if Blockdata["myid"] == Blockdata["main_node"]:
				if abs(iter_current_iter_ratio - iter_previous_iter_ratio< 1.0) and iter_current_iter_ratio > 90.: converged = 1
			converged = bcast_number_to_all(converged, Blockdata["main_node"], MPI_COMM_WORLD)
			
			if converged == 0:
				iter_previous_iter_ratio = iter_current_iter_ratio
				iter +=1
				if (iter <= box_niter):
					iter_dir = os.path.join(within_box_run_dir, "iter%d"%iter)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						if not os.path.exists(iter_dir):os.mkdir(iter_dir)
						for indep in xrange(2):
							write_text_file(new_assignment_list[indep], \
								os.path.join(iter_dir, "random_assignment_%03d.txt"%indep))				   
						msg ="+++++++++++++ move to iter %d... +++++++++++++++"%iter
						log_main.add(msg)
						print(line, msg)
			else:
				if Blockdata["myid"] == Blockdata["main_node"]:
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					msg =" internal loop converged "
					log_main.add(msg)
					print(line, msg)
			mpi_barrier(MPI_COMM_WORLD)
			
		if Blockdata["myid"] == Blockdata["main_node"]:
			ncluster, NACC, NUACC, unaccounted_list, new_clusters = output_iter_results(\
			    work_dir, ncluster, NACC, NUACC, Tracker["constants"]["minimum_grp_size"], \
			            list_of_stable, unaccounted_list, log_main)
		else:
			ncluster = 0
			NACC  = 0
			NUACC = 0
			unaccounted_list = 0
			new_clusters     = 0
		new_clusters = bcast_number_to_all(new_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
		ncluster     = bcast_number_to_all(ncluster, Blockdata["main_node"], MPI_COMM_WORLD)
		NACC         = bcast_number_to_all(NACC,     Blockdata["main_node"], MPI_COMM_WORLD)
		NUACC        = bcast_number_to_all(NUACC,    Blockdata["main_node"], MPI_COMM_WORLD)
		unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
		if new_clusters >0: no_cluster = False
		else:               no_cluster = True
		keepgoing, nruns, total_stack, current_number_of_groups = \
		   check_state_within_box_run(keepgoing, nruns, img_per_grp, minimum_grp_size, unaccounted_list, no_cluster)
		   
		if Blockdata["myid"] == Blockdata["main_node"]:# report current state
			line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
			if keepgoing ==1: pnruns =nruns-1
			else: 			  pnruns =nruns
			msg1 = "current NACC: %8d  NUACC: %8d K: %3d total identified clusters: %3d  identified clusters in this run: %3d"%\
			  (NACC, NUACC, current_number_of_groups, ncluster, new_clusters)
			time_of_box_h,  time_of_box_m = get_time(time_box_start)
			msg2 = " time cost: %d hours  %d minutes"%(time_of_box_h, time_of_box_m)
			msg  = "boxrunsummary: generation %d layer %d nbox %d run %d: "%(Tracker["current_generation"], Tracker["depth"], nbox, pnruns) + msg1 +msg2
			log_main.add(msg +'\n \n')
			if os.path.exists(os.path.join(within_box_run_dir, "tempdir")): shutil.rmtree(os.path.join(within_box_run_dir, "tempdir"))
			
		if keepgoing == 1:
			within_box_run_dir = os.path.join(work_dir, "run%d"%nruns)
			unaccounted_file = os.path.join(within_box_run_dir, "Unaccounted_from_previous_run.txt")
			if(Blockdata["myid"] == Blockdata["main_node"]):
				if not os.path.exists(within_box_run_dir):os.mkdir(within_box_run_dir)
				write_text_file(unaccounted_list, unaccounted_file)# new starting point
			nreassign_list  = []
			assignment_list = create_nrandom_lists(unaccounted_file, current_number_of_groups, 2)
			
			if(Blockdata["myid"] == Blockdata["main_node"]):
				for indep in xrange(2):
					write_text_row(assignment_list[indep], os.path.join(within_box_run_dir,\
				     "independent_index_%03d.txt"%indep))
			run_id_file = os.path.join(within_box_run_dir, "independent_index_000.txt")
		else:
			partition = get_box_partition(work_dir, ncluster, unaccounted_list)
			if(Blockdata["myid"] == Blockdata["main_node"]): write_text_row(partition, os.path.join(work_dir, "partition.txt"))
		mpi_barrier(MPI_COMM_WORLD)
	return
######<<<<<<----------------------------+++++++++++++++++++
def check_mpi_settings(log):
	global Tracker, Blockdata
	from   utilities import wrap_mpi_bcast, read_text_file, bcast_number_to_all
	import os
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	current_mpi_settings_is_bad = 0
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		fsc_refinement = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "fsc_global.txt"))
		q = float(Tracker["constants"]["img_per_grp"])/float(Tracker["constants"]["total_stack"])
		for ifreq in xrange(len(fsc_refinement)): fsc_refinement[ifreq] = fsc_refinement[ifreq]*q/(1.-fsc_refinement[ifreq]*(1.-q))
		res = 0.0
		for ifreq in xrange(len(fsc_refinement)):
			if fsc_refinement[ifreq]<0.143: break
		res = float(ifreq)/2./float(len(fsc_refinement))
		nxinit = int(2.*res*Tracker["constants"]["nnxo"])
		del fsc_refinement
	else: nxinit =0
	nxinit = bcast_number_to_all(nxinit, Blockdata["main_node"], MPI_COMM_WORLD)	
	sys_required_mem = 1.0*Blockdata["no_of_processes_per_group"]
	
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg_pipe  =' ' 
		log.add(msg_pipe)
		msg_pipe  ='-----------------------------------------------------------------' 
		log.add(msg_pipe)
		msg       ='         >>>>>>>   Number of input images and memory information   <<<<<               '
		msg_pipe1 ='++++++                                                     ++++++' 
		log.add(msg)
		log.add(msg_pipe1)
		msg ="Number of processes: %5d  node number:  %5d.  Number of processes per group:  %5d."%(Blockdata["nproc"], Blockdata["no_of_groups"], Blockdata["no_of_processes_per_group"])
		log.add(msg)
	try:
		image_org_size     = Tracker["constants"]["nnxo"]
		image_in_core_size = nxinit
		ratio = float(nxinit)/float(image_org_size)
		raw_data_size = float(Tracker["constants"]["total_stack"]*image_org_size*image_org_size)*4.0/1.e9
		raw_data_size_per_node = float(Tracker["constants"]["total_stack"]*image_org_size*image_org_size)*4.0/1.e9/Blockdata["no_of_groups"]
		sorting_data_size_per_node = raw_data_size_per_node + 2.*raw_data_size_per_node*ratio**2
		volume_size_per_node = (4.*image_in_core_size**3*8.)*Blockdata["no_of_processes_per_group"]/1.e9
	except:  current_mpi_settings_is_bad = 1
	if current_mpi_settings_is_bad == 1:ERROR("initial info is not provided", "check_mpi_settings", 1, Blockdata["myid"])
	try:
		mem_bytes = os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')# e.g. 4015976448
		mem_gib = mem_bytes/(1024.**3) # e.g. 3.74
		if( Blockdata["myid"] == Blockdata["main_node"]):
			msg = "Available memory information provided by the operating system: %5.1f GB"%mem_gib
			log.add(msg)
	except:
		mem_gib = None
		#if( Blockdata["myid"] == Blockdata["main_node"]):print(line, "It is not an unix machine!")
		else: pass
	if Tracker["constants"]["memory_per_node"] == -1.:
		if mem_gib: total_memory = mem_gib
		else:
			total_memory =  Blockdata["no_of_processes_per_group"]*2.0 # assume each CPU has 2.0 G
			if( Blockdata["myid"] == Blockdata["main_node"]):
				msg ="Memory per node is not provided, sort3d assumes 2G per node"
				log.add(msg)
		Tracker["constants"]["memory_per_node"] = total_memory
	else:
		msg ="Memory per node: %f"%Tracker["constants"]["memory_per_node"]
		total_memory =  Tracker["constants"]["memory_per_node"]
		if( Blockdata["myid"] == Blockdata["main_node"]):
			log.add(msg)
	if(Blockdata["myid"] == Blockdata["main_node"]):
		msg = "Total number of particles: %d.  Number of particles per group: %d."%(Tracker["constants"]["total_stack"], Tracker["constants"]["img_per_grp"])
		log.add(msg)
	if(Blockdata["myid"] == Blockdata["main_node"]):
		msg = "The total available memory:  %5.1f GB"%total_memory
		log.add(msg)
		msg = "The size of input 2D stack: %5.1f GB, the amount of memory 2D data will occupy per node: %5.1f GB"%(raw_data_size, raw_data_size_per_node)
		log.add(msg)
	if (total_memory - sys_required_mem - raw_data_size_per_node - volume_size_per_node - sorting_data_size_per_node - 5.0) <0.0: 
		current_mpi_settings_is_bad = 1
		new_nproc =  raw_data_size*(2.*ratio**2+1.)*Blockdata["no_of_processes_per_group"]/(total_memory - 5. - sys_required_mem - volume_size_per_node)
		new_nproc =  int(new_nproc)
		if( Blockdata["myid"] == Blockdata["main_node"]):
			msg ="Suggestion: set number of processes to: %d"%int(new_nproc)
			log.add(msg)
		ERROR("Insufficient memory", "check_mpi_settings", 1, Blockdata["myid"])
	images_per_cpu = float(Tracker["constants"]["total_stack"])/float(Blockdata["nproc"])
	images_per_cpu_for_unaccounted_data  = Tracker["constants"]["img_per_grp"]*1.5/float(Blockdata["nproc"])
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg="Number of images per cpu:  %d "%int(images_per_cpu)
		log.add(msg )
	if images_per_cpu < 5.0: ERROR("image per cpu less than 5", "check_mpi_settings", 1, Blockdata["myid"])
	if(Blockdata["myid"] == Blockdata["main_node"]):
		log.add(msg_pipe + '\n')
	return
	
def get_sorting_image_size(original_data, partids, number_of_groups, sparamstructure, snorm_per_particle, log):
	global Tracker, Blockdata
	from utilities    import wrap_mpi_bcast, read_text_file, write_text_file
	from applications import MPI_start_end
	iter = 0
	Tracker["number_of_groups"] = number_of_groups
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		msg = "3D reconstruction is computed using window size:  %d"%Tracker["nxinit_refinement"]
		log.add(msg)
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			iter_assignment = []
			for im in xrange(len(lpartids[0])):
				iter_assignment.append(randint(0,number_of_groups - 1))# simple version
		else:
			iter_assignment = lpartids[0]
	else:   iter_assignment = 0
	iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"])
	
	Tracker["total_stack"] = len(iter_assignment)
	proc_list = [[None, None] for iproc in xrange(Blockdata["nproc"])]
	for iproc in xrange(Blockdata["nproc"]):
		iproc_image_start, iproc_image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], iproc)
		proc_list[iproc] = [iproc_image_start, iproc_image_end]
	compute_noise(Tracker["nxinit_refinement"])
	rdata = downsize_data_for_rec3D(original_data, Tracker["nxinit_refinement"], return_real = False, npad = 1)
	update_rdata_assignment(iter_assignment, proc_list, Blockdata["myid"], rdata)
	Tracker["nxinit"] = Tracker["nxinit_refinement"]
	compute_noise(Tracker["nxinit"])
	do3d_sorting_groups_fsc_only_iter(rdata, sparamstructure, snorm_per_particle, iteration = iter)
	del rdata
	
	if( Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		msg = "3D reconstruction using refinement window size %d is completed."%Tracker["nxinit_refinement"]
		log.add(msg)
		
	if( Blockdata["myid"] == Blockdata["main_node"]):
		fsc_data = []
		for igroup in xrange(Tracker["number_of_groups"]):
			for ichunk in xrange(2):
				tmp_fsc_data = read_text_file(os.path.join(Tracker["directory"], "fsc_driver_chunk%d_grp%03d_iter%03d.txt"%(ichunk, igroup, iter)), -1)
				fsc_data.append(tmp_fsc_data[0])
	else: fsc_data = 0
	fsc_data = wrap_mpi_bcast(fsc_data, Blockdata["main_node"])
	avg_fsc = [0.0 for i in xrange(len(fsc_data[0]))]
	avg_fsc[0] = 1.0
	for igroup in xrange(1): # Use group zero first
		for ifreq in xrange(1, len(fsc_data[0])):avg_fsc[ifreq] += fsc_data[igroup][ifreq]
	fsc143 = len(fsc_data[0])
	for ifreq in xrange(len(avg_fsc)):
		if avg_fsc[ifreq] < 0.143:
			fsc143 = ifreq -1
			break
	if fsc143 !=0: nxinit = min((int(fsc143)+ max(int(Tracker["constants"]["nnxo"]*0.03), 5))*2, Tracker["constants"]["nnxo"])
	else: ERROR("program obtains wrong image size", "get_sorting_image_size", 1, Blockdata["myid"])
	freq_fsc143_cutoff = float(fsc143)/float(nxinit)
	if(Blockdata["myid"] == Blockdata["main_node"]): write_text_file(avg_fsc, os.path.join(Tracker["directory"], "fsc_image_size.txt"))
	del iter_assignment
	del proc_list
	del fsc_data
	del avg_fsc
	return nxinit, freq_fsc143_cutoff
	
def compute_noise(image_size):
	global Tracker, Blockdata
	from utilities    import get_im, model_blank
	from fundamentals import fft
	if Tracker["applybckgnoise"]: # from SPARX refinement only
		if(Blockdata["myid"] == Blockdata["main_node"]):
			tsd = get_im(Tracker["bckgnoise"]) # inverted power spectrum
			nnx = tsd.get_xsize()
			nny = tsd.get_ysize()
		else:
			nnx = 0
			nny = 0
		nnx = bcast_number_to_all(nnx, Blockdata["main_node"], MPI_COMM_WORLD)
		nny = bcast_number_to_all(nny, Blockdata["main_node"], MPI_COMM_WORLD)
		if( Blockdata["myid"] != Blockdata["main_node"]):tsd = model_blank(nnx, nny)
		bcast_EMData_to_all(tsd, Blockdata["myid"], Blockdata["main_node"])
		temp_image = model_blank(image_size, image_size)
		temp_image = fft(temp_image)
		nx = temp_image.get_xsize()
		ny = temp_image.get_ysize()
		Blockdata["bckgnoise"]  = []
		Blockdata["unrolldata"] = []
		for i in xrange(nny):
			prj = nnx*[0.0]
			for k in xrange(nnx):
				if tsd.get_value_at(k,i)>0.0: prj[k] = tsd.get_value_at(k,i)
			Blockdata["bckgnoise"].append(prj)
		for i in xrange(len(Blockdata["bckgnoise"])): Blockdata["unrolldata"].append(Util.unroll1dpw(ny, Blockdata["bckgnoise"][i]))
	else: # from datastack and relion
		temp_image = model_blank(image_size, image_size)
		temp_image = fft(temp_image)
		nx = temp_image.get_xsize()
		ny = temp_image.get_ysize()
		Blockdata["bckgnoise"] = [1.0]*nx
		Blockdata["unrolldata"] = Util.unroll1dpw(ny, nx*[1.0])
	return
			
def get_params_for_analysis(orgstack, ali3d_params, smearing_file, smearing_number):
	if ali3d_params is not None:
		vecs_list =[]
		norm_list =[]
		ali3d_params = read_text_row(ali3d_params)
		for im in xrange(len(ali3d_params)):
			vecs_list.append(getvec(ali3d_params[im][0], ali3d_params[im][1]))
			try: norm_list.append(ali3d_params[im][7])
			except: norm_list = None
	##
	if( orgstack is not None ):
		defo_list = []
		ctfs = EMUtil.get_all_attributes(orgstack, "ctf")
		for im in xrange(len(ctfs)):
			defo_list.append(ctfs[im].defocus)
	else: defo_list = None
	##
	if smearing_file is not None:
		try: smearing_list = read_text_file(smearing_file)
		except: smearing_list = None
	else: smearing_list = None
	##
	return vecs_list, defo_list, smearing_list, norm_list
	
def orien_analysis(veclist, cluster_id, log_main):
	mean_vec = [0.0, 0.0, 0.0]
	for im in xrange(len(veclist)):
		for jm in xrange(len(mean_vec)):
			mean_vec[jm] +=veclist[im][jm]
	lsum = 0.0
	for jm in xrange(len(mean_vec)):
		mean_vec[jm]/=float(len(veclist))
		lsum += mean_vec[jm]**2
	from math import sqrt
	lsum =sqrt(lsum)
	max_value = max(mean_vec[0], mean_vec[1], mean_vec[2])
	msg = "%5d  %f   %f  %f  %f"%\
	   (cluster_id, mean_vec[0], mean_vec[1], mean_vec[2], lsum) +"\n"+\
	   "%5s  %f   %f  %f  "%\
	   (" ", mean_vec[0]/max_value, mean_vec[1]/max_value, mean_vec[2]/max_value)
	print(msg)
	log_main.add(msg)
	return mean_vec

def do_one_way_anova_scipy(clusters, value_list, name_of_variable="variable", summary = None , log_main = None):
	# single cpu program
	import copy
	from math   import sqrt
	import scipy
	from scipy import stats
	if summary == None: summary = []
	NMAX = 30
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	msg_pipe = '-------------------------------------------' 
	msg      = '   >>>>>> do_one_way_anova_scipy <<<<<<<   '
	print(line, msg_pipe)
	print(msg)
	print(line, msg_pipe)
	log_main.add(msg_pipe)
	log_main.add(msg)
	log_main.add(msg_pipe)
	if len(clusters)<=1:
		print("the number of clusters for anova is less than 2")
		return None, None, None
	K = min(NMAX, len(clusters))
	if len(clusters) > K : print("total number of clusters is larger than 30. Process only the first 30 clusters")
	replicas = []
	for ic in xrange(K):
		ll = copy.deepcopy(clusters[ic])
		ll1 = [None for i in xrange(len(ll))]
		for ie in xrange(len(ll)): ll1[ie] = value_list[ll[ie]]
		replicas.append(ll1)
	x0 = replicas[0]
	x1 = replicas[1]
	try: x2 = replicas[2]
	except: pass
	try: x3 = replicas[3]
	except: pass
	try: x4 = replicas[4]
	except: pass
	try: x5 = replicas[5]
	except: pass
	try: x6 = replicas[6]
	except: pass
	try: x7 = replicas[7]
	except: pass
	try: x8 = replicas[8]
	except: pass
	try: x9 = replicas[9]
	except: pass
	try: x10 = replicas[10]
	except: pass
	try: x11 = replicas[11]
	except: pass
	try: x12 = replicas[12]
	except: pass
	try: x13 = replicas[13]
	except: pass
	try: x14 = replicas[14]
	except: pass
	try: x15 = replicas[15]
	except: pass
	try: x16 = replicas[16]
	except: pass
	try: x17 = replicas[17]
	except: pass
	try: x18 = replicas[18]
	except: pass
	try: x19 = replicas[19]
	except: pass
	try: x20 = replicas[20]
	except: pass
	try: x21 = replicas[21]
	except: pass
	try: x22 = replicas[22]
	except: pass
	try: x23 = replicas[23]
	except: pass
	try: x24 = replicas[24]
	except: pass
	try: x25 = replicas[25]
	except: pass
	try: x26 = replicas[26]
	except: pass
	try: x27 = replicas[27]
	except: pass
	try: x28 = replicas[28]
	except: pass
	try: x29 = replicas[29]
	except: pass
	
	if   K==2: res = stats.f_oneway(x0, x1)
	elif K==3: res = stats.f_oneway(x0, x1, x2)
	elif K==4: res = stats.f_oneway(x0, x1, x2, x3)
	elif K==5: res = stats.f_oneway(x0, x1, x2, x3, x4)
	elif K==6: res = stats.f_oneway(x0, x1, x2, x3, x4, x5)
	elif K==7: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6)
	elif K==8: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7)
	elif K==9: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8)
	elif K==10: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9)
	elif K==11: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10)
	elif K==12: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11)
	elif K==13: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12)
	elif K==14: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13)
	elif K==15: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14)
	elif K==16: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15)
	elif K==17: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16)
	elif K==18: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17)
	elif K==19: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18)
	elif K==20: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19)
	elif K==21: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20)
	elif K==22: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21)
	elif K==23: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22)
	elif K==24: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23)
	elif K==25: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24)
	elif K==26: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24, x25)
	elif K==27: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24, x25, x26)
	elif K==28: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24, x25, x26, x27)
	elif K==29: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24, x25, x26, x27, x28)
	elif K==30: res = stats.f_oneway(x0, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10, x11, x12, x13, x14, x15, x16, x17,x18, x19, x20, x21, x22, x23, x24, x25, x26, x27, x28, x29)
	else:
		print("ERROR in %s anova, and skip the rest calculation"%name_of_variable)
		return None, None, None
	res_table_stat = []
	for im in xrange(K):
		alist = table_stat(replicas[im])
		res_table_stat.append(alist)
	avgs =[]
	global_mean = 0.0
	for ir in xrange(K): 
		global_mean +=sum(replicas[ir])
		avgs.append(sum(replicas[ir])/float(len(replicas[ir])))
	
	summed_squared_elements = 0.0
	summed_squared_elements_within_groups = [None for i in xrange(K)]
	std_list =[]
	sst = 0.0
	nsamples = 0.0
	for i in xrange(K): nsamples +=len(replicas[i])
	for i in xrange(K):
		ssa_per_group = 0.0
		std_per_group = 0.0 
		for j in xrange(len(replicas[i])):
			sst +=replicas[i][j]**2
			summed_squared_elements +=replicas[i][j]*replicas[i][j]
			ssa_per_group +=replicas[i][j]
			std_per_group += (replicas[i][j] -avgs[i])**2
		std_list.append(sqrt(std_per_group/float(len(replicas[i]))))
		summed_squared_elements_within_groups[i] = ssa_per_group**2/float(len(replicas[i]))
		
	sst -=global_mean**2/nsamples
	ssa = sum(summed_squared_elements_within_groups) - global_mean**2/nsamples
	sse = sst - ssa
	n1 = 0
	for i in xrange(K): n1 +=len(replicas[i])-1
	msa = ssa/(K-1.0)
	mse = sse/float(n1)
	mst = sst/float(n1)
	f_ratio = msa/mse
	msg ="anova ====================>>>ANOVA on %s<<<===================== \n"%(name_of_variable)+\
		'{:5} {:^12} {:^12} {}'.format('anova', 'f_value',  'p_value', '\n')+\
		'{:5} {:12.5f} {:12.6f} {}'.format('anova', res[0], round(res[1],6), '\n')
	log_main.add("\n"+msg)
	summary.append(msg)
	if res[1] <=0.00001:
		msg = "anova null hpypothesis is rejected! There is statistically significant %s difference among clusters. \n"%name_of_variable
		log_main.add("\n"+msg)
		summary.append(msg)
	else: 
		msg = "anova null hpypothesis is accepted! There is no statistically significant difference among %s of clusters \n"%name_of_variable
		log_main.add("\n"+msg)
		summary.append(msg)
	msg = ("anova  ---------->>>global %s mean of all clusters: %f  \n"%(name_of_variable, global_mean/(float(nsamples))))
	msg += "anova  ---------->>>Means per group<<<-----\n"+\
	'{:5} {:^7} {:^8} {:^12} {:^12} {}'.format('anova', 'GID', 'N',  'mean',   'std', '\n')
	for i in xrange(K):
		msg +='{:5} {:^7d} {:^8d} {:12.4f} {:12.4f} {}'.format('anova', i, len(replicas[i]), res_table_stat[i][0], res_table_stat[i][1],'\n')
	summary.append(msg)
	log_main.add("\n"+msg)
	msg ="anova  ---------->>>pairwise anova<<<----------- \n"
	log_main.add("\n"+msg)
	summary.append(msg)
	msg ='{:5} {:^3} {:^3} {:^12} {:^12} {:^12} {:^12} {:^36} {}'.format('anova', 'A', 'B', 'avgA','avgB', 'P_value', 'f-value', 'statistically significant difference', "\n") 
	log_main.add("\n"+msg)
	summary.append(msg)
	tmsg = ''
	for ires in xrange(K-1):
		for jres in xrange(ires+1, K):
			cres = stats.f_oneway(replicas[ires], replicas[jres])
			if cres[1] <=0.00001: msg = '{:5} {:^3d} {:^3d} {:12.4f} {:12.4f} {:12.3f} {:12.6f} {:^36} {}'.format('anova', ires, jres, avgs[ires], avgs[jres], cres[0], round(cres[1],6),'Yes', '\n')
			else:                 msg = '{:5} {:^3d} {:^3d} {:12.4f} {:12.4f} {:12.3f} {:12.6f} {:^36} {}'.format('anova', ires, jres, avgs[ires], avgs[jres], cres[0], round(cres[1], 6),'No', '\n')
			tmsg +=msg
	log_main.add("\n"+tmsg)
	summary.append(tmsg)
	msg = "anova ================================================================================\n \n \n"
	log_main.add("\n"+msg)
	summary.append(msg)
	return res[0], res[1], summary
	
def output_micrograph_number_per_cluster(orgstack, index_file, clusters, log_main = None):
	# single node job
	mic_dict = {}
	inverse_mic_dict = {}
	try: mics = EMUtil.get_all_attributes(orgstack, "ptcl_source_image")
	except:
		msg = "No ptcl_source_image attribute are set in data headers!"
		print(msg)
		log_main.add(msg)
		try:
			tmpmics = EMUtil.get_all_attributes(orgstack, "ctf")
			mics = [None for i in xrange(len(tmpmics))]
			for im in xrange(len(mics)): mics[im] = tmpmics[im].defocus
		except:
			msg = "CTF parameters are not found either, so sort3d skips counting micograph number per cluster..."
			print(msg)
			log_main.add(msg)
			return
	pid_list =read_text_file(index_file)
	for im in xrange(len(pid_list)):
		mic_dict [pid_list[im]] = mics[pid_list[im]]
		inverse_mic_dict[mics[pid_list[im]]] =  im
	mics_in_clusters = [None for i in xrange(len(clusters))]
	msg = "micstat------->>>number of micrographs in clusters<<<-----------\n"
	msg += "micstat total number of micrographs:  %d \n"%len(inverse_mic_dict)
	msg +='{:10} {:^5} {:^20} {:^12} {}'.format('micstat', 'GID', 'No. of micrographs', 'percentage', '\n')
	for ic in xrange(len(clusters)):
		tmp_mics_in_cluster = {}
		for im in xrange(len(clusters[ic])): 
			tmp_mics_in_cluster[mic_dict[clusters[ic][im]]] = im
		mics_in_clusters[ic] = len(tmp_mics_in_cluster)
		msg +='{:10} {:^5} {:^20}  {:^12} {}'.format('micstat', ic, mics_in_clusters[ic], round(float(mics_in_clusters[ic])/float(len(inverse_mic_dict))*100.,2), '\n')
	log_main.add('\n', msg)
	print(msg)
	return mics_in_clusters

def check_3dmask(log_main):
	global Tracker, Blockdata
	###########################################################################	
	Tracker["nxinit"]     = Tracker["nxinit_refinement"]
	Tracker["currentres"] = float(Tracker["constants"]["fsc05"])/float(Tracker["nxinit"])
	##################--------------->>>>>> shrinkage, current resolution, fuse_freq <<<<<<------------------------------------------
	Tracker["total_stack"] = Tracker["constants"]["total_stack"]
	Tracker["shrinkage"]   = float(Tracker["nxinit"])/Tracker["constants"]["nnxo"]
	Tracker["radius"]      = Tracker["constants"]["radius"]*Tracker["shrinkage"]
	try: fuse_freq = Tracker["fuse_freq"]
	except: Tracker["fuse_freq"] = int(Tracker["constants"]["pixel_size"]*Tracker["constants"]["nnxo"]/Tracker["constants"]["fuse_freq"]+0.5)	
	if Tracker["constants"]["mask3D"]:Tracker["mask3D"] =Tracker["constants"]["mask3D"]
	else: Tracker["mask3D"] = None
	if Tracker["constants"]["focus3Dmask"]:Tracker["focus3D"] = Tracker["constants"]["focus3Dmask"]
	else: Tracker["focus3D"] = None
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		bad_focus3Dmask = 0
		if Tracker["constants"]["focus3Dmask"]:
			try:
				focusmask = get_im(Tracker["constants"]["focus3Dmask"])
				st = info(focusmask)
				if ((st[2] != 0.0) or (st[3] != 1.0)):
					focusmask = binarize(focusmask)# binarize focus mask if it is not a binary mask
					st = Util.infomask(focusmask)
				if(st[0] == 0.0) or (st[0] == 1.0): bad_focus3Dmask = 1
				else:
					focusmask.write_image(os.path.join(Tracker["constants"]["masterdir"], "focus3d.hdf"))
					Tracker["focus3D"] = os.path.join(Tracker["constants"]["masterdir"], "focus3d.hdf")
			except:  bad_focus3Dmask = 1
	else: bad_focus3Dmask = 0
	bad_focus3Dmask = bcast_number_to_all(bad_focus3Dmask,	source_node =  Blockdata["main_node"])
	if bad_focus3Dmask: ERROR("Incorrect focused mask, after binarize all values zero","sxsort3d.py", 1, Blockdata["myid"])
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		bad_3Dmask = 0
		if Tracker["constants"]["mask3D"]:
			try: 
				mask3D = get_im(Tracker["constants"]["mask3D"])
				st = Util.infomask(binarize(mask3D), None, True)
				if (st[0] ==0.0): bad_3Dmask = 1
				else: 
					mask3D.write_image(os.path.join(Tracker["constants"]["masterdir"], "mask3D.hdf"))
					Tracker["mask3D"]= os.path.join(Tracker["constants"]["masterdir"], "mask3D.hdf")
			except: bad_3Dmask = 1
	else: bad_3Dmask = 0
	bad_3Dmask = bcast_number_to_all(bad_focus3Dmask,	source_node =  Blockdata["main_node"])
	if bad_3Dmask: ERROR("Incorrect 3D mask", "sxsort3d.py", 1, Blockdata["myid"])
	
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]):
		#print_dict(Tracker["constants"],"Permanent settings of the program after update from the input options")
		fout = open(os.path.join(Tracker["constants"]["masterdir"], "Tracker.json"),'w')
		json.dump(Tracker, fout)
		fout.close()
		#msg = "orgstack: %s  image comparison method: %s "%(Tracker["constants"]["orgstack"], \
		#   Tracker["constants"]["comparison_method"])
		#print(line, msg)
		#log_main.add(msg)
		if Tracker ["constants"]["focus3Dmask"]:
			msg ="User provided focus mask file:  %s"%Tracker ["constants"]["focus3Dmask"]
			print(line, msg)
			log_main.add(msg)
	Tracker["shrinkage"] = float(Tracker["nxinit"])/Tracker["constants"]["nnxo"]
	#if(Blockdata["myid"] == Blockdata["main_node"]):  print_dict(Tracker,"Current settings of the sorting program")
	return

def import_data(log_main):
	global Tracker, Blockdata
	# Two typical sorting scenarios
	# 1. import data and refinement parameters from meridien refinement;
	# 2. given data stack and xform.projection/ctf in header(For simulated test data);
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		msg = "importing data ... "
		print(line, msg)
		log_main.add(msg)
	import_from_relion_refinement = 0
	import_from_sparx_refinement  = 0
	import_from_data_stack		  = 0
	total_stack					  = 0
	if Tracker["constants"]["refinement_method"] =="SPARX": # Senario one
		import_from_sparx_refinement = get_input_from_sparx_ref3d(log_main)
		Tracker["smearing"] = True
	else:  # Senario three, sorting from a given data stack, general cases
		import_from_data_stack = get_input_from_datastack(log_main)
		Tracker["constants"]["hardmask"] = True
		Tracker["applybckgnoise"]        = False
		Tracker["applymask"]             = True
		Tracker["smearing"]              = False
	Tracker["total_stack"] = Tracker["constants"]["total_stack"]
	###<<<------------------------>>>>>>checks<<<<<-------------
	if Tracker["constants"]["symmetry"] != Tracker["constants"]["sym"]:
		if(Blockdata["myid"] == Blockdata["main_node"]):
			msg = "input symmetry %s is altered to %s after reading refinement information! "%(Tracker["constants"]["sym"], Tracker["constants"]["symmetry"])
			log_main.add(msg)
			print(msg)
	## checking settings!
	number_of_groups =  Tracker["constants"]["total_stack"]//Tracker["constants"]["img_per_grp"]
	if number_of_groups<=1: ERROR("Your img_per_grp is too large", "sxsort3d_depth.py", 1,  Blockdata["myid"])
	minimum_grp_size = Tracker["constants"]["minimum_grp_size"]
	if minimum_grp_size >= Tracker["constants"]["img_per_grp"]:
		ERROR("minimum_grp_size is too large", "sxsort3d_depth.py", 1,  Blockdata["myid"])
	return
	
def create_masterdir(log_main):
	global Tracker, Blockdata
	line      = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	masterdir = Tracker["constants"]["masterdir"]
	restart   = 0
	if(Blockdata["myid"] == Blockdata["main_node"]):
		if not os.path.exists(os.path.join(Tracker["constants"]["masterdir"])):
			print(line, "Sort3d starts")
			if not masterdir:
				timestring = strftime("_%d_%b_%Y_%H_%M_%S", localtime())
				masterdir  ="sort3d"+timestring
				os.mkdir(masterdir)
			else:
				if not os.path.exists(masterdir): os.mkdir(masterdir)
			li =len(masterdir)
		else:
			li =len(masterdir)
			if os.path.exists(os.path.join(Tracker["constants"]["masterdir"], "layer0")): restart = 1
			if os.path.exists(os.path.join(Tracker["constants"]["masterdir"], "Tracker.json")): restart = 1
			print("restart", restart)
	else: 
		restart = 0
		li = 0
	restart = bcast_number_to_all(restart, Blockdata["main_node"], MPI_COMM_WORLD)
	li                                    = mpi_bcast(li,1,MPI_INT,Blockdata["main_node"],MPI_COMM_WORLD)[0]
	masterdir                             = mpi_bcast(masterdir,li,MPI_CHAR,Blockdata["main_node"],MPI_COMM_WORLD)
	masterdir                             = string.join(masterdir,"")
	if not Tracker["constants"]["masterdir"]: Tracker["constants"]["masterdir"]  = masterdir
	Tracker["constants"]["chunk_0"]       = os.path.join(Tracker["constants"]["masterdir"],"chunk_0.txt")
	Tracker["constants"]["chunk_1"]       = os.path.join(Tracker["constants"]["masterdir"],"chunk_1.txt")
	return restart

def sort3d_init(to_be_decided, log_main):
	global Tracker, Blockdata
	if Tracker["constants"]["img_per_grp"]<= 2:
		ERROR("poor img_per_grp", "sort3d_init", 1, Blockdata["myid"])
	if Tracker["total_stack"] <= Blockdata["nproc"]*2:
		ERROR("either too many cpus are used, or number of images is too small", "sort3d_init", 1, Blockdata["myid"])
	Tracker["img_per_grp"]             = Tracker["constants"]["img_per_grp"]
	Tracker["number_of_groups"]        = Tracker["total_stack"]//Tracker["constants"]["img_per_grp"]
	Tracker["rnd_assign_group_size"]   = Tracker["constants"]["img_per_grp"]//Tracker["number_of_groups"]
	Tracker["minimum_grp_size"] = Tracker["constants"]["minimum_grp_size"]
	if Tracker["constants"]["minimum_grp_size"]>Tracker["img_per_grp"]:
		ERROR("img_per_grp is less than minimum_grp_size", "sort3d_init", 1, Blockdata["myid"])
	if Blockdata["myid"] == Blockdata["main_node"]: print_dict(Tracker, to_be_decided)
	return

def print_shell_command(args_list, log_main):
	global Tracker, Blockdata
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(Blockdata["myid"] == Blockdata["main_node"]):
		log_main.add("The shell line command:")
		line = ""
		for a in args_list: line +=(a + " ")
		log_main.add(line)
		#log_main.add("Sort3d master directory: %s"%Tracker["constants"]["masterdir"])
		#print_dict(Tracker["constants"],"Permanent settings of the program after initialization")
	mpi_barrier(MPI_COMM_WORLD)
	return

def sort3d_utils(to_be_decided, log_main = None, input_file1 = None):
	global Tracker, Blockdata
	from utilities import get_number_of_groups
	### global initialization
	
	try:    Tracker["sort3d_counter"] +=1
	except: Tracker["sort3d_counter"]  =0
		
	if Blockdata["myid"] == Blockdata["main_node"]:
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		#msg = "sort3d_step  %d  "%Tracker["sort3d_counter"]+ to_be_decided
		#print(line, msg)
		#if log_main != None: log_main.add(msg)
		
	if to_be_decided == "initialization":
		sort3d_init(to_be_decided, log_main)
		return True
		
	elif to_be_decided == "check_mpi_settings":
		check_mpi_settings(log_main)
		return
		
	elif to_be_decided =="check_mask3d":
		check_3dmask(log_main)
		return

	elif to_be_decided =="import_data":
		import_data(log_main)
		return
		
	elif to_be_decided =="create_masterdir":
		return create_masterdir(log_main)
		
	elif to_be_decided == "dump_tracker":
		if(Blockdata["myid"] == Blockdata["main_node"]):
			if input_file1 is None: dump_dir = Tracker["constants"]["masterdir"]
			else:  dump_dir = input_file1
			fout = open(os.path.join(dump_dir, "Tracker.json"),'w')
			json.dump(Tracker, fout)
			fout.close()
		mpi_barrier(MPI_COMM_WORLD)
		return
		
	elif to_be_decided == "load_tracker":
		if(Blockdata["myid"] == Blockdata["main_node"]):
			fout = open(os.path.join(Tracker["constants"]["masterdir"], "Tracker.json"),'r')
			Tracker = convert_json_fromunicode(json.load(fout))
			fout.close()
			msg ="restart from interuption, load tracker files"
			log_main.add(msg)
		else: Tracker = 0
		Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
		
	elif to_be_decided =="print_command":
		print_shell_command(sys.argv, log_main)
		return
	return
	
def reset_assignment_to_previous_groups(assignment, match_pairs):
	# match pair is computed by two way comparison of new_iteration with old_iteration 
	group_dict = {}
	for ic in xrange(len(match_pairs)): group_dict[match_pairs[ic][0]] = match_pairs[ic][1]
	print("  group_dict", group_dict)
	for im in xrange(len(assignment)): assignment[im] = group_dict[assignment[im]]
	return assignment
	
def AI_MGSKmeans(iter_assignment, last_iter_assignment, best_assignment, keepgoing, best_score, stopercnt, minimum_grp_size, log_file):
	# single cpu function
	import collections
	group_dict       = collections.Counter(iter_assignment)
	number_of_groups = len(group_dict)
	msg = "group id     group size"
	log_file.add(msg)
	clusters = []
	for igrp in xrange(len(group_dict)):
		msg ="%5d    %10d"%(igrp, group_dict[igrp])
		log_file.add(msg)
		clusters.append(group_dict[igrp])
	is_unicorn_cluster = 0
	nc  = 0
	tot = 0
	for ic in xrange(len(clusters)):
		tot += clusters[ic]
		if clusters[ic] < minimum_grp_size + len(clusters): nc +=1
	if tot//minimum_grp_size>2*len(clusters) and nc+1==len(clusters):is_unicorn_cluster =1
	if is_unicorn_cluster == 0:
		sum_newindices1 = 0
		sum_newindices2 = 0
		ratio, newindices, stable_clusters = compare_two_iterations(iter_assignment, last_iter_assignment, number_of_groups)
		for idx in xrange(len(newindices)):
			sum_newindices1 += newindices[idx][0]
			sum_newindices2 += newindices[idx][1]
			if newindices[idx][0] != newindices[idx][1]:
				msg ="group %d  swaps with group %d "%(newindices[idx][0], newindices[idx][1])
				log_file.add(msg)
		changed_nptls = 100.- ratio*100.
		if best_score >= changed_nptls:
			best_score = changed_nptls
			best_assignment = copy.copy(iter_assignment)
		if changed_nptls < stopercnt: keepgoing = 0
	else:
		msg ="unicorn cluster is found. shuffle assignment"
		log_file.add(msg)
		print(msg)
		iter_assignment = shuffle_assignment(iter_assignment, number_of_groups)
		best_score    = 100.
		changed_nptls = 100.
		keepgoing     = 1
		best_assignment = copy.copy(iter_assignment)
	return best_score, changed_nptls, keepgoing, best_assignment, iter_assignment

def shuffle_assignment(iter_assignment, number_of_groups):
	import random
	new_assignment  = range(0, len(iter_assignment))
	tmp_assignment  = range(0, len(iter_assignment))
	ngroup          = 0
	while len(tmp_assignment) >=1:
		shuffle(tmp_assignment)
		im = tmp_assignment[0]
		new_assignment[im] = ngroup%number_of_groups
		del tmp_assignment[0]
		ngroup +=1
	return new_assignment
	
#####
def Kmeans_minimum_group_size_orien_groups(original_data, partids, params, paramstructure, norm_per_particle, minimum_group_size, clean_volumes = False):
	global Tracker, Blockdata
	import shutil
	import numpy as np
	#<<<<---------- >>>>EQKmeans starts<<<<------------ 
	log	                     = Logger()
	log                      = Logger(BaseLogger_Files())
	log.prefix               = Tracker["directory"]+"/"
	premature                = 0
	changed_nptls            = 100.0
	number_of_groups         = Tracker["number_of_groups"]
	stopercnt                = Tracker["constants"]["stop_mgskmeans_percentage"]
	total_iter               = 0
	require_check_setting    = False
	partial_rec3d            = False
	best_score               = 100.0
	best_assignment          = []
	max_iter                 = Tracker["total_number_of_iterations"]
	last_score               = 100.0
	fixed_value              = 100.0
	has_converged            = 0
	times_around_fixed_value = 0  
	###<<<<<<------------
	if( Blockdata["myid"] == Blockdata["main_node"]):
		try:
			if os.path.exists(Tracker["mask3D"]): # prepare mask
				mask3D = get_im(Tracker["mask3D"])
				if mask3D.get_xsize() != Tracker["nxinit"]: 
					mask3D = fdecimate(mask3D, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
		except:
			mask3D = model_circle(Tracker["constants"]["radius"], Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"])
			mask3D = fdecimate(mask3D, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
	else:
		mask3D = model_blank(Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"])
	bcast_EMData_to_all(mask3D, Blockdata["myid"], Blockdata["main_node"])
		
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:# Not true for sorting
			iter_assignment = []
			for im in xrange(len(lpartids[0])):iter_assignment.append(randint(0,number_of_groups-1))# simple version
		else: iter_assignment = lpartids[0]
	else: iter_assignment = 0
	iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"]) # initial assignment
	###
	total_stack              = len(iter_assignment)
	Tracker["total_stack"]   = total_stack
	minimum_group_size_ratio =  min((minimum_group_size*Tracker["number_of_groups"])/float(Tracker["total_stack"]), 0.95)
	nima                     = len(original_data)
	image_start, image_end   = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	
	Tracker["min_orien_group_size"] = Tracker["number_of_groups"]*Tracker["minimum_ptl_number"]
	angle_step  = get_angle_step_from_number_of_orien_groups(Tracker["constants"]["orientation_groups"])
	ptls_in_orien_groups = get_orien_assignment_mpi(angle_step, partids, params, log)
		
	### printed info
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg_pipe ='----------------------------------'
		msg      = ' >>>> MGSKmeans clustering <<<< '
		log.add(msg_pipe)
		log.add(msg)
		log.add(msg_pipe)
		msg = "total_stack:  %d K = : %d  nxinit: %d  CTF:  %s  Symmetry:  %s  stop percentage: %f  3-D mask: %s focus mask: %s  Comparison method: %s  minimum_group_size: %d orien  %d"% \
		   (Tracker["total_stack"], Tracker["number_of_groups"], Tracker["nxinit"],  Tracker["constants"]["CTF"], \
		     Tracker["constants"]["symmetry"], stopercnt, Tracker["mask3D"], Tracker["focus3D"], Tracker["constants"]["comparison_method"], minimum_group_size, len(ptls_in_orien_groups))
		log.add(msg)
		print(line, msg)
		
	proc_list = [[None, None] for iproc in xrange(Blockdata["nproc"])]
	for iproc in xrange(Blockdata["nproc"]):
		iproc_image_start, iproc_image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], iproc)
		proc_list[iproc] = [iproc_image_start, iproc_image_end]
		
	compute_noise(Tracker["nxinit"])
	mpi_barrier(MPI_COMM_WORLD)
	cdata, rdata, fdata = downsize_data_for_sorting(original_data, preshift = True, npad = 1, norms =norm_per_particle)# pay attentions to shifts!
	mpi_barrier(MPI_COMM_WORLD)
	srdata = precalculate_shifted_data_for_recons3D(rdata, paramstructure, Tracker["refang"], \
	   Tracker["rshifts"], Tracker["delta"], Tracker["avgnorm"], Tracker["nxinit"], \
	     Tracker["constants"]["nnxo"], Tracker["nosmearing"], norm_per_particle, Tracker["constants"]["nsmear"])
	del rdata
	mpi_barrier(MPI_COMM_WORLD)
	last_iter_assignment = copy.copy(iter_assignment)
	best_assignment      = copy.copy(iter_assignment)
	total_iter       = 0
	keepgoing        = 1
	do_partial_rec3d = 0
	partial_rec3d    =  False
	
	while total_iter < max_iter:
		ptls_in_orien_groups = get_orien_assignment_mpi(angle_step, partids, params, log)
		if(Blockdata["myid"] == Blockdata["main_node"]):
			msg = "Iteration %d particle assignment changed ratio  %f "%(total_iter, changed_nptls)
			log.add(msg)
			write_text_file(iter_assignment, os.path.join(Tracker["directory"], "assignment%03d.txt"%total_iter))
			if changed_nptls< 50.0: do_partial_rec3d = 1
			else:                   do_partial_rec3d = 0
		else: do_partial_rec3d = 0
		do_partial_rec3d       = bcast_number_to_all(do_partial_rec3d, Blockdata["main_node"], MPI_COMM_WORLD)
		if do_partial_rec3d ==1: partial_rec3d = True
		else:                    partial_rec3d = False
			
		update_data_assignment(cdata, srdata, iter_assignment, proc_list, Tracker["nosmearing"], Blockdata["myid"])
		mpi_barrier(MPI_COMM_WORLD)
		do3d_sorting_groups_nofsc_smearing_iter(srdata, partial_rec3d, iteration = total_iter)
		mpi_barrier(MPI_COMM_WORLD)
		
		local_peaks = [0.0 for im in xrange(number_of_groups*nima)]
		total_im    = 0
		local_kmeans_peaks = [ -1.0e23 for im in xrange(nima)]
		## compute peaks and save them in 1D list
		for iref in xrange(number_of_groups):
			if(Blockdata["myid"] == Blockdata["last_node"]):
				try: fsc143 = Tracker["fsc143"][iref]
				except:	fsc143 = 0.0
				try: fsc05 = Tracker["fsc05"][iref]
				except:	fsc05 = 0.0	
				ref_vol = get_im(os.path.join(Tracker["directory"],"vol_grp%03d_iter%03d.hdf"%(iref, total_iter)))
				nnn = ref_vol.get_xsize()
				if(Tracker["nxinit"] != nnn): ref_vol = fdecimate(ref_vol, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
				stat = Util.infomask(ref_vol, mask3D, False)
				ref_vol -= stat[0]
				if stat[1]!=0.0:Util.mul_scalar(ref_vol, 1.0/stat[1])
				ref_vol *=mask3D
			else: ref_vol = model_blank(Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"])
			bcast_EMData_to_all(ref_vol, Blockdata["myid"], Blockdata["last_node"])
			## Image comparison optimal solution is the larger one	
			if Tracker["constants"]["comparison_method"] =="cross": ref_peaks = compare_two_images_cross(cdata, ref_vol)
			else: ref_peaks = compare_two_images_eucd(cdata, ref_vol, fdata)
			for im in xrange(nima):
				local_peaks[total_im] = ref_peaks[im]
				total_im +=1
			mpi_barrier(MPI_COMM_WORLD)
		del ref_vol
		# pass to main_node
		if Blockdata["myid"] == Blockdata["main_node"]:
			dmatrix =[[ 0.0 for im in xrange(Tracker["total_stack"])] for iref in xrange(number_of_groups)]
			for im in xrange(len(local_peaks)): dmatrix[im//nima][im%nima + image_start] = local_peaks[im]
		else: dmatrix = 0
		if Blockdata["myid"] != Blockdata["main_node"]: wrap_mpi_send(local_peaks, Blockdata["main_node"], MPI_COMM_WORLD)
		else:
			for iproc in xrange(Blockdata["nproc"]):
				if iproc != Blockdata["main_node"]:
					local_peaks = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					iproc_nima  = proc_list[iproc][1] - proc_list[iproc][0]
					for im in xrange(len(local_peaks)): dmatrix[im/iproc_nima][im%iproc_nima + proc_list[iproc][0]] = local_peaks[im]
		dmatrix = wrap_mpi_bcast(dmatrix, Blockdata["main_node"], MPI_COMM_WORLD)
		last_iter_assignment = copy.copy(iter_assignment)
		iter_assignment = [-1 for iptl in xrange(Tracker["total_stack"])]
		for iorien in xrange(len(ptls_in_orien_groups)):
			if iorien%Blockdata["nproc"] == Blockdata["myid"]:
				local_assignment = do_assignment_by_dmatrix_orien_group_minimum_group_size(dmatrix, \
					ptls_in_orien_groups[iorien], Tracker["number_of_groups"], minimum_group_size_ratio)
				for iptl in xrange(len(ptls_in_orien_groups[iorien])):
					iter_assignment[ptls_in_orien_groups[iorien][iptl]] = local_assignment[iptl]
		mpi_barrier(MPI_COMM_WORLD)
		if Blockdata["myid"] != Blockdata["main_node"]: wrap_mpi_send(iter_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		else:
			for iproc in xrange(Blockdata["nproc"]):
				if iproc != Blockdata["main_node"]:
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for iptl in xrange(len(dummy)):
						if dummy[iptl] !=-1:iter_assignment[iptl] = dummy[iptl]
						else: pass		
		iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		if Blockdata["myid"] == Blockdata["main_node"]:
			last_score =  changed_nptls
			best_score, changed_nptls, keepgoing, best_assignmen, iter_assignment = \
			     AI_MGSKmeans(iter_assignment, last_iter_assignment, best_assignment, keepgoing, best_score, stopercnt, minimum_group_size, log)
			if abs(last_score - changed_nptls)<1.0:
				if  times_around_fixed_value == 0:
					fixed_value = changed_nptls
					times_around_fixed_value +=1
				else:
					if abs(changed_nptls - fixed_value)<1.0: times_around_fixed_value +=1
					else:
						times_around_fixed_value = 0
						fixed_value = changed_nptls
		else:
			iter_assignment = 0
			best_assignment = 0
			keepgoing       = 1
		iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		best_assignment = wrap_mpi_bcast(best_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		times_around_fixed_value = bcast_number_to_all(times_around_fixed_value, Blockdata["main_node"], MPI_COMM_WORLD)
		keepgoing = bcast_number_to_all(keepgoing,  Blockdata["main_node"], MPI_COMM_WORLD)
		total_iter +=1
		last_iter_assignment = copy.copy(iter_assignment)
		if times_around_fixed_value>=3: keepgoing = 0
		if keepgoing == 0: break
	# Finalize
	update_data_assignment(cdata, srdata, iter_assignment, proc_list, Tracker["nosmearing"], Blockdata["myid"])
	res_sort3d = get_sorting_all_params(cdata)
	del cdata
	del srdata
	del iter_assignment
	del last_iter_assignment
	del best_assignment
	if mask3D: del mask3D
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if best_score > Tracker["constants"]["stop_mgskmeans_percentage"]: 
			msg ="MGSKmeans stops with changed particles ratio %f  that is larger than user provieded stop percentage %f"%(best_score, stopercnt)
			premature  = 1
		else: msg = "MGSKmeans stops with changed particles ratio %f within %d iterations that is less than user provieded stop percentage %f"%(\
		        best_score, total_iter, stopercnt)
		print(line, msg)
		log.add(msg)
		partition, ali3d_params_list = parsing_sorting_params(partids, res_sort3d)
		write_text_row(partition, os.path.join(Tracker["directory"],"list.txt"))
		shutil.rmtree(os.path.join(Tracker["directory"], "tempdir"))
	
	else: partition = 0
	partition  = wrap_mpi_bcast(partition, Blockdata["main_node"])
	premature  = wrap_mpi_bcast(premature, Blockdata["main_node"])

	if(Blockdata["myid"] == Blockdata["last_node"]):
		if clean_volumes:
			for jter in xrange(total_iter):
				for igroup in xrange(Tracker["number_of_groups"]): 
					os.remove(os.path.join(Tracker["directory"], "vol_grp%03d_iter%03d.hdf"%(igroup,jter)))	
	if require_check_setting:
		if(Blockdata["myid"] == Blockdata["main_node"]): print("Too large changed particles, and the sorting settings, such as img_per_grp requires a check")
	return partition, premature
	
#####
def Kmeans_minimum_group_size_relaxing_orien_groups(original_data, partids, params, paramstructure, norm_per_particle, minimum_group_size, clean_volumes = False):
	global Tracker, Blockdata
	import shutil
	import numpy as np
	#<<<<---------- >>>>EQKmeans starts<<<<------------ 
	log	                    =  Logger()
	log                     =  Logger(BaseLogger_Files())
	log.prefix              =  Tracker["directory"]+"/"
	premature               =  0
	changed_nptls           =  100.0
	number_of_groups        =  Tracker["number_of_groups"]
	stopercnt               =  Tracker["constants"]["stop_mgskmeans_percentage"]
	total_iter              = 0
	require_check_setting   = False
	partial_rec3d           = False
	best_score              = 100.0
	best_assignment         = []
	orien_group_relaxation  = False
	###<<<<<<------------
	if Tracker["mask3D"]: # prepare mask
		mask3D = get_im(Tracker["mask3D"])
		if mask3D.get_xsize() != Tracker["nxinit"]: mask3D = fdecimate(mask3D, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
	else: 
		mask3D = model_circle(Tracker["constants"]["radius"], Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"])
		mask3D = fdecimate(mask3D, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:# Not true for sorting
			iter_assignment = []
			for im in xrange(len(lpartids[0])):iter_assignment.append(randint(0,number_of_groups-1))# simple version
		else: iter_assignment = lpartids[0]
	else: iter_assignment = 0
	iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"]) # initial assignment
	####
	total_stack             = len(iter_assignment)
	Tracker["total_stack"]  = total_stack
	minimum_group_size_ratio =  min((minimum_group_size*Tracker["number_of_groups"])/float(Tracker["total_stack"]), 0.9)
	nima                    = len(original_data)
	image_start, image_end  = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	
	norien_groups = Tracker["constants"]["orientation_groups"]
	Tracker["min_orien_group_size"] = Tracker["number_of_groups"]*Tracker["minimum_ptl_number"]
	angle_step = get_angle_step_from_number_of_orien_groups(norien_groups)
	ptls_in_orien_groups = get_orien_assignment_mpi(angle_step, partids, params, log)
		
	### printed info
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg = "------>>>> Kmeans clustering with constrained minimum group size <<<<--------"
		log.add(msg)
		msg = "total_stack:  %d K = : %d  nxinit: %d  CTF:  %s  Symmetry:  %s  stop percentage: %f  3-D mask: %s focus mask: %s  Comparison method: %s  minimum_group_size: %d orien  %d"% \
		   (Tracker["total_stack"], Tracker["number_of_groups"], Tracker["nxinit"],  Tracker["constants"]["CTF"], \
		     Tracker["constants"]["symmetry"], stopercnt, Tracker["mask3D"], Tracker["focus3D"], Tracker["constants"]["comparison_method"], minimum_group_size, len(ptls_in_orien_groups))
		log.add(msg)
		print(line, msg)
		print(" input value", Tracker["constants"]["minimum_grp_size"])
	###
	proc_list = [[None, None] for iproc in xrange(Blockdata["nproc"])]
	for iproc in xrange(Blockdata["nproc"]):
		iproc_image_start, iproc_image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], iproc)
		proc_list[iproc] = [iproc_image_start, iproc_image_end]
	compute_noise(Tracker["nxinit"])
	cdata, rdata, fdata = downsize_data_for_sorting(original_data, preshift = True, npad = 1, norms = norm_per_particle)# pay attentions to shifts!
	srdata = precalculate_shifted_data_for_recons3D(rdata, paramstructure, Tracker["refang"], \
	   Tracker["rshifts"], Tracker["delta"], Tracker["avgnorm"], Tracker["nxinit"], \
	     Tracker["constants"]["nnxo"], Tracker["nosmearing"], norm_per_particle,  Tracker["constants"]["nsmear"])
	del rdata
	last_iter_assignment = copy.copy(iter_assignment)
	iter       = 0
	total_iter = 0
	dmin       = 0.5
	nreduce_min_grp_size = 0
	while total_iter<Tracker["total_number_of_iterations"]:
		if(Blockdata["myid"] == Blockdata["main_node"]):
			msg = "Iteration %d particle assignment changed ratio  %f, orien relax: %r: norien_groups:  %d"\
			  %(total_iter, changed_nptls, orien_group_relaxation, len(ptls_in_orien_groups))
			log.add(msg)
			write_text_file(iter_assignment, os.path.join(Tracker["directory"], "assignment%03d.txt"%total_iter))
		if changed_nptls< 50.0: partial_rec3d = True
		else:                   partial_rec3d = False
		update_data_assignment(cdata, srdata, iter_assignment, proc_list, Tracker["nosmearing"], Blockdata["myid"])
		mpi_barrier(MPI_COMM_WORLD)
		do3d_sorting_groups_nofsc_smearing_iter(srdata, partial_rec3d, iteration = total_iter)
		mpi_barrier(MPI_COMM_WORLD)
		local_peaks = [0.0 for im in xrange(number_of_groups*nima)]
		total_im           = 0
		local_kmeans_peaks = [ -1.0e23 for im in xrange(nima)]
		## compute peaks and save them in 1D list
		for iref in xrange(number_of_groups):
			if(Blockdata["myid"] == Blockdata["last_node"]):
				try: fsc143 = Tracker["fsc143"][iref]
				except:	fsc143 = 0.0
				try: fsc05 = Tracker["fsc05"][iref]
				except:	fsc05 = 0.0	
				ref_vol = get_im(os.path.join(Tracker["directory"],"vol_grp%03d_iter%03d.hdf"%(iref, total_iter)))
				nnn = ref_vol.get_xsize()
				if(Tracker["nxinit"] != nnn): ref_vol = fdecimate(ref_vol, Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"], True, False)
				stat = Util.infomask(ref_vol, mask3D, False)
				ref_vol -= stat[0]
				if stat[1]!=0.0:Util.mul_scalar(ref_vol, 1.0/stat[1])
				ref_vol *=mask3D
			else: ref_vol = model_blank(Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"])
			bcast_EMData_to_all(ref_vol, Blockdata["myid"], Blockdata["last_node"])
			## Image comparison optimal solution is the larger one	
			if Tracker["constants"]["comparison_method"] =="cross": ref_peaks = compare_two_images_cross(cdata, ref_vol)
			else: ref_peaks = compare_two_images_eucd(cdata, ref_vol, fdata)
			for im in xrange(nima):
				local_peaks[total_im] = ref_peaks[im]
				total_im +=1
			mpi_barrier(MPI_COMM_WORLD)
		del ref_vol
		# pass to main_node
		if Blockdata["myid"] == Blockdata["main_node"]:
			dmatrix =[[ 0.0 for im in xrange(Tracker["total_stack"])] for iref in xrange(number_of_groups)]
			for im in xrange(len(local_peaks)): dmatrix[im//nima][im%nima + image_start] = local_peaks[im]
		else: dmatrix = 0
		if Blockdata["myid"] != Blockdata["main_node"]: wrap_mpi_send(local_peaks, Blockdata["main_node"], MPI_COMM_WORLD)
		else:
			for iproc in xrange(Blockdata["nproc"]):
				if iproc != Blockdata["main_node"]:
					local_peaks = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					iproc_nima  = proc_list[iproc][1] - proc_list[iproc][0]
					for im in xrange(len(local_peaks)): dmatrix[im/iproc_nima][im%iproc_nima + proc_list[iproc][0]] = local_peaks[im]
		dmatrix = wrap_mpi_bcast(dmatrix, Blockdata["main_node"], MPI_COMM_WORLD)
		last_iter_assignment = copy.copy(iter_assignment)
		iter_assignment = [-1 for iptl in xrange(Tracker["total_stack"])]
		for iorien in xrange(len(ptls_in_orien_groups)):
			if iorien%Blockdata["nproc"] == Blockdata["myid"]:
				local_assignment = do_assignment_by_dmatrix_orien_group_minimum_group_size(dmatrix, \
					ptls_in_orien_groups[iorien], Tracker["number_of_groups"], minimum_group_size_ratio)
				for iptl in xrange(len(ptls_in_orien_groups[iorien])):
					iter_assignment[ptls_in_orien_groups[iorien][iptl]] = local_assignment[iptl]
		mpi_barrier(MPI_COMM_WORLD)		
		if Blockdata["myid"] != Blockdata["main_node"]: wrap_mpi_send(iter_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		else:
			for iproc in xrange(Blockdata["nproc"]):
				if iproc != Blockdata["main_node"]:
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for iptl in xrange(len(dummy)):
						if dummy[iptl] !=-1:iter_assignment[iptl] = dummy[iptl]
						else: pass
			#iter_assignment = shake_assignment(iter_assignment, randomness_rate = 1.-Tracker["constants"]["eqk_shake"]/200.)#						
		mpi_barrier(MPI_COMM_WORLD)	
		iter_assignment = wrap_mpi_bcast(iter_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
		ratio, newindices, stable_clusters = compare_two_iterations(iter_assignment, last_iter_assignment, number_of_groups)
		#reset_assignment_to_previous_groups(iter_assignment, newindices)
		changed_nptls = 100.- ratio*100.
		if(Blockdata["myid"] == Blockdata["main_node"]):
			msg = "Iteration %d particle assignment changed ratio subject to induced randomness  %f "% \
				 (total_iter, changed_nptls )
		if best_score >= changed_nptls:
			best_score = changed_nptls
			best_assignment = copy.copy(iter_assignment)
		iter       +=1
		total_iter +=1
		#last_iter_assignment = copy.copy(iter_assignment)
		
		if changed_nptls < stopercnt and total_iter<20: 
			orien_group_relaxation = True
		if not orien_group_relaxation:
			if changed_nptls < stopercnt: 
				break
		else: 
			if changed_nptls < stopercnt: 
				if norien_groups>=4:
					norien_groups = norien_groups//2
					Tracker["min_orien_group_size"] = Tracker["number_of_groups"]*Tracker["minimum_ptl_number"]
					angle_step = get_angle_step_from_number_of_orien_groups(norien_groups)
					ptls_in_orien_groups = get_orien_assignment_mpi(angle_step, partids, params, log)
				else: break
	#Finalize
	if changed_nptls < stopercnt: update_data_assignment(cdata, srdata, iter_assignment, proc_list, Tracker["nosmearing"], Blockdata["myid"])
	else: update_data_assignment(cdata, srdata, best_assignment, proc_list, Tracker["nosmearing"], Blockdata["myid"])
	res_sort3d = get_sorting_all_params(cdata)
	del cdata
	del srdata
	del iter_assignment
	del last_iter_assignment
	del best_assignment
	if mask3D: del mask3D

	#if best_score > 15.0: require_check_setting = True
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if best_score > Tracker["constants"]["stop_mgskmeans_percentage"]: 
			msg ="MGSKmeans stop with changed particles ratio %f and image size %d"%(best_score,Tracker["nxinit"])
			premature  = 1
		else: msg = "MGSKmeans stop with changed particles ratio %f within %d iterations and actually used stop percentage is %f"%(\
		        best_score, total_iter, stopercnt)
		log.add(msg)
		Tracker["partition"], ali3d_params_list = parsing_sorting_params(partids, res_sort3d)
		write_text_row(Tracker["partition"], os.path.join(Tracker["directory"],"list.txt"))
		shutil.rmtree(os.path.join(Tracker["directory"], "tempdir"))
	else:Tracker["partition"] = 0
	Tracker["partition"] = wrap_mpi_bcast(Tracker["partition"], Blockdata["main_node"])
	premature  = wrap_mpi_bcast(premature, Blockdata["main_node"])
	if(Blockdata["myid"] == Blockdata["last_node"]):
		if clean_volumes:
			for jter in xrange(total_iter):
				for igroup in xrange(Tracker["number_of_groups"]): os.remove(os.path.join(Tracker["directory"], "vol_grp%03d_iter%03d.hdf"%(igroup,jter)))
	return Tracker["partition"], premature
#####

def do_assignment_by_dmatrix_orien_group_minimum_group_size(dmatrix, orien_group_members, number_of_groups, minimum_group_size_ratio):
	import numpy as np
	results = [[] for i in xrange(number_of_groups)]
	nima    = len(orien_group_members)
	minimum_group_size = int(minimum_group_size_ratio*nima/number_of_groups)
	submatrix = np.zeros((number_of_groups, nima))
	for i in xrange(number_of_groups):
		for j in xrange(len(orien_group_members)):
			submatrix[i][j] = dmatrix[i][orien_group_members[j]]*(-1.)# sort in descending order
	tmp_array = np.argsort(submatrix, axis = 1)
	rmatrix   = []
	for i in xrange(number_of_groups): rmatrix.append(tmp_array[i].tolist())
	del tmp_array
	while len(rmatrix[0])> nima - minimum_group_size*number_of_groups:
		tarray = []
		for i in xrange(number_of_groups): tarray.append(rmatrix[i][0])
		value_list, index_list = np.unique(np.array(tarray), return_index= True)
		duplicate_list = (np.setdiff1d(np.arange(number_of_groups), index_list)).tolist()
		index_list     = index_list.tolist()
		value_list     = value_list.tolist()
		if len(value_list)<  number_of_groups:
			for i in xrange(len(index_list)):
				if tarray[index_list[i]] ==  tarray[duplicate_list[0]]: duplicate_list.append(index_list[i])# find all duplicated ones
			shuffle(duplicate_list)
			duplicate_list.remove(duplicate_list[0])
			for i in xrange(len(duplicate_list)):# swap the first row with the next row
				index_column = 1
				while rmatrix[duplicate_list[i]][index_column] in value_list: index_column +=1 # search along column non-equal ones
				value_list.append(rmatrix[duplicate_list[i]][index_column])
				rmatrix[duplicate_list[i]][0], rmatrix[duplicate_list[i]][index_column] = rmatrix[duplicate_list[i]][index_column], rmatrix[duplicate_list[i]][0]
		for i in xrange(number_of_groups):
			results[i].append(rmatrix[i][0])
			for j in xrange(number_of_groups): rmatrix[i].remove(value_list[j]) # remove K elements from each column
	kmeans_ptl_list = (np.delete(np.array(range(nima)), np.array(results).ravel())).tolist()# ravel works only for even size
	del rmatrix
	for iptl in xrange(len(kmeans_ptl_list)):
		max_indexes = np.argwhere(submatrix[:, kmeans_ptl_list[iptl]]<=submatrix[:, kmeans_ptl_list[iptl]][submatrix[:, kmeans_ptl_list[iptl]].argmin()])
		if len(max_indexes) >1:
			t = range(len(max_indexes))
			shuffle(t)
			results[max_indexes[t[0]][0]].append(kmeans_ptl_list[iptl])
		else: results[max_indexes[0][0]].append(kmeans_ptl_list[iptl])
	iter_assignment = [-1 for i in xrange(nima)]
	for i in xrange(number_of_groups): 
		results[i].sort()
		for j in xrange(len(results[i])): iter_assignment[results[i][j]] = i
	del results
	del submatrix
	return iter_assignment
	
### various reading data
### 1
def get_shrink_data_sorting(partids, partstack, return_real = False, preshift = True, apply_mask = True, npad = 1):
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.
	#  The read data is properly distributed among MPI threads.
	# 10142015 --- preshift is set to True when doing 3-D sorting.
	# chunk_id are set when data is read in
	global Tracker, Blockdata
	from utilities      import wrap_mpi_bcast, read_text_row
	from fundamentals	import resample, fshift
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line,"get_shrink_data_sorting")
	mask2D		= model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	shrinkage 	= Tracker["nxinit"]/float(Tracker["constants"]["nnxo"])
	radius 		= int(Tracker["constants"]["radius"] * shrinkage +0.5)	
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			lpartids = lpartids[0]
			groupids = len(lpartids)*[-1]
		else:
			groupids = lpartids[0]
			lpartids = lpartids[1]
	else:  	
		lpartids   = 0
		groupids   = 0
	lpartids   = wrap_mpi_bcast(lpartids, Blockdata["main_node"])
	groupids   = wrap_mpi_bcast(groupids, Blockdata["main_node"])
	Tracker["total_stack"]  = len(lpartids)
	if(Blockdata["myid"] == Blockdata["main_node"]):  partstack = read_text_row(partstack)
	else:  partstack = 0
	partstack = wrap_mpi_bcast(partstack, Blockdata["main_node"])
	
	if(Tracker["total_stack"] < Blockdata["nproc"]): ERROR("Wrong MPI settings!", "get_shrink_data_sorting", 1, Blockdata["myid"])
	else: image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	lpartids  = lpartids[image_start:image_end]
	groupids  = groupids[image_start:image_end]
	nima      =	image_end - image_start
	data      = [None]*nima
	for im in xrange(nima):
		data[im] = get_im(Tracker["constants"]["orgstack"], lpartids[im])	
		try: phi, theta, psi, sx, sy, chunk_id, particle_group_id = partstack[lpartids[im]][0], partstack[lpartids[im]][1],\
		 partstack[lpartids[im]][2], partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], partstack[lpartids[im]][6]
		except: phi, theta, psi, sx, sy, chunk_id, particle_group_id = partstack[lpartids[im]][0], partstack[lpartids[im]][1],\
		 partstack[lpartids[im]][2], partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], -1		 
		if preshift:# always true
			data[im]  = fshift(data[im],sx,sy)
			sx = 0.0
			sy = 0.0
		st = Util.infomask(data[im], mask2D, False)
		data[im] -= st[0]
		data[im] /= st[1]
		if apply_mask: data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"])
		# FT
		data[im] = fft(data[im])
		nny =  data[im].get_ysize()
		if Tracker["constants"]["CTF"]:
			ctf_params = data[im].get_attr("ctf")
			data[im]   = fdecimate(data[im], Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			ctf_params.apix = ctf_params.apix/shrinkage
			data[im].set_attr('ctf', ctf_params)
			data[im].set_attr('ctf_applied', 0)
			if return_real :  data[im] = fft(data[im])
		else:
			ctf_params = data[im].get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				data[im].set_attr('ctf', ctf_params)
				data[im].set_attr('ctf_applied', 0)
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, True, False)
			apix = Tracker["constants"]["pixel_size"]
			data[im].set_attr('apix', apix/shrinkage)
		if not return_real:	data[im].set_attr("padffted",1)
		data[im].set_attr("npad",npad)
		set_params_proj(data[im],[phi, theta, psi, 0.0, 0.0])
		data[im].set_attr("chunk_id",chunk_id)
		data[im].set_attr("group",groupids[im])
		data[im].set_attr("particle_group", particle_group_id)
		if Tracker["applybckgnoise"]:
			data[im].set_attr("bckgnoise", Blockdata["bckgnoise"][particle_group_id])
			data[im].set_attr("qt", float(Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"]))
		else: data[im].set_attr("bckgnoise", Blockdata["bckgnoise"]) # constant list
	return data
###2
def get_shrink_data_sorting_smearing(partids, partstack, return_real = False, preshift = True, apply_mask = True, npad = 1):
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.
	#  The read data is properly distributed among MPI threads.
	# 10142015 --- preshift is set to True when doing 3-D sorting.
	# chunk_id are set when data is read in
	global Tracker, Blockdata
	from fundamentals	import resample, fshift
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line,"get_shrink_data_sorting")
	mask2D		= model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	shrinkage 	= Tracker["nxinit"]/float(Tracker["constants"]["nnxo"])
	radius 		= int(Tracker["constants"]["radius"] * shrinkage +0.5)
	
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			lpartids = lpartids[0]
			groupids = len(lpartids)*[-1]
		else:
			groupids = lpartids[0]
			lpartids = lpartids[1]
	else:  	
		lpartids   = 0
		groupids   = 0
	lpartids   = wrap_mpi_bcast(lpartids, Blockdata["main_node"])
	groupids   = wrap_mpi_bcast(groupids, Blockdata["main_node"])
	Tracker["total_stack"]  = len(lpartids)
	if(Blockdata["myid"] == Blockdata["main_node"]): partstack = read_text_row(partstack)
	else:  partstack = 0
	partstack = wrap_mpi_bcast(partstack, Blockdata["main_node"])
	if(Tracker["total_stack"] < Blockdata["nproc"]): ERROR("Wrong MPI settings!", "get_shrink_data_sorting", 1, Blockdata["myid"])
	else:   image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	lpartids  = lpartids[image_start:image_end]
	groupids  = groupids[image_start:image_end]
	nima      =	image_end - image_start
	data      = [None]*nima
	norm_per_particle = []
	for im in xrange(nima):
		data[im] = get_im(Tracker["constants"]["orgstack"], lpartids[im])	
		try: phi, theta, psi, sx, sy, chunk_id, particle_group_id, norm = partstack[lpartids[im]][0], partstack[lpartids[im]][1],\
		 partstack[lpartids[im]][2], partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], \
		   partstack[lpartids[im]][6], partstack[lpartids[im]][7]
		except: phi, theta, psi, sx, sy, chunk_id, particle_group_id, norm = partstack[lpartids[im]][0], partstack[lpartids[im]][1],\
		 partstack[lpartids[im]][2], partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], -1, 1
		if preshift:# always true
			data[im]  = fshift(data[im],sx,sy)
			sx = 0.0
			sy = 0.0
		st = Util.infomask(data[im], mask2D, False)
		data[im] -= st[0]
		data[im] /= st[1]	
		if apply_mask: data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"])
		# FT
		data[im] = fft(data[im])
		nny =  data[im].get_ysize()
		if Tracker["constants"]["CTF"] :
			ctf_params = data[im].get_attr("ctf")
			data[im]   = fdecimate(data[im], Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			ctf_params.apix = ctf_params.apix/shrinkage
			data[im].set_attr('ctf', ctf_params)
			data[im].set_attr('ctf_applied', 0)
			if return_real :  data[im] = fft(data[im])
		else:
			ctf_params = data[im].get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				data[im].set_attr('ctf', ctf_params)
				data[im].set_attr('ctf_applied', 0)
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, True, False)
			apix = Tracker["constants"]["pixel_size"]
			data[im].set_attr('apix', apix/shrinkage)
		if not return_real:	data[im].set_attr("padffted",1)
		data[im].set_attr("npad",npad)
		set_params_proj(data[im],[phi, theta, psi, 0.0, 0.0])
		data[im].set_attr("chunk_id",chunk_id)
		data[im].set_attr("group",groupids[im])
		data[im].set_attr("particle_group", particle_group_id)
		if Tracker["applybckgnoise"]:
			data[im].set_attr("bckgnoise", Blockdata["bckgnoise"][particle_group_id])
			data[im].set_attr("qt", float(Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"]))
		else: data[im].set_attr("bckgnoise", Blockdata["bckgnoise"]) # constant list
		norm_per_particle.append(norm)
	return data, norm_per_particle
###3
def get_data_prep_compare_rec3d(partids, partstack, return_real = False, preshift = True, npad = 1):
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.
	
	global Tracker, Blockdata
	from fundamentals	import resample, fshift, fft
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	from utilities      import model_circle, wrap_mpi_bcast, get_im, model_blank, set_params_proj
	# functions:
	# read in data
	# apply mask, and prepare focus projection if focus3D is specified
	# return  1. cdata: data for image comparison, always in Fourier format
	#         2. rdata: data for reconstruction, 4nn return real image

	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line,"read_data in ")		
	mask2D	  = model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	shrinkage = Tracker["nxinit"]/float(Tracker["constants"]["nnxo"])
	radius    = int(Tracker["constants"]["radius"] * shrinkage +0.5)
	if Tracker["applybckgnoise"]:
		oneover = []
		nnx = len(Blockdata["bckgnoise"][0])
		for i in xrange(len(Blockdata["bckgnoise"])):
			temp = [0.0]*nnx
			for k in xrange(nnx):
				if(Blockdata["bckgnoise"][i][k] > 0.0):  temp[k] = 1.0/sqrt(Blockdata["bckgnoise"][i][k])
			oneover.append(temp)
		del temp
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			lpartids = lpartids[0]
			groupids = len(lpartids)*[-1]
		else:
			groupids = lpartids[0]
			lpartids = lpartids[1]
	else:
		lpartids   = 0
		groupids   = 0
	lpartids = wrap_mpi_bcast(lpartids, Blockdata["main_node"])
	groupids = wrap_mpi_bcast(groupids, Blockdata["main_node"])
	Tracker["total_stack"] = len(lpartids)
	if(Blockdata["myid"] == Blockdata["main_node"]):  partstack = read_text_row(partstack)
	else:  partstack = 0
	partstack = wrap_mpi_bcast(partstack, Blockdata["main_node"])
	if(Tracker["total_stack"] < Blockdata["nproc"]):
		ERROR("number of processors in use is larger than the total number of particles", \
		  "get_data_and_prep", 1, Blockdata["myid"])
	else: image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	lpartids  = lpartids[image_start:image_end]
	groupids  = groupids[image_start:image_end]
	if Tracker["focus3D"]: # focus mask is applied
		if Blockdata["myid"] == Blockdata["main_node"]:
			focus3d     = get_im(Tracker["focus3D"])
			focus3d_nx  = focus3d.get_xsize()
			if focus3d_nx != Tracker["constants"]["nnxo"]: # So the decimated focus volume can be directly used
				focus3d = resample(focus3d, float(Tracker["constants"]["nnxo"])/float(focus3d_nx))
		else: focus3d = model_blank(Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"])
		bcast_EMData_to_all(focus3d, Blockdata["myid"], Blockdata["main_node"])
		focus3d = prep_vol(focus3d, 1, 1)
	#  Preprocess the data
	#  mask2D    =	model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	nima  = image_end - image_start
	cdata = [None]*nima
	rdata = [None]*nima
	for im in xrange(nima):
		image = get_im(Tracker["constants"]["orgstack"], lpartids[im])
		try: phi, theta, psi, sx, sy, chunk_id, particle_group_id  = partstack[lpartids[im]][0], partstack[lpartids[im]][1], partstack[lpartids[im]][2], \
			partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], partstack[lpartids[im]][6]
		except: phi, theta, psi, sx, sy, chunk_id, particle_group_id  = partstack[lpartids[im]][0], partstack[lpartids[im]][1], partstack[lpartids[im]][2], \
		  partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], -1 	  
		if preshift:# always true
			image = fshift(image,sx,sy)
			sx = 0.0
			sy = 0.0
		st = Util.infomask(image, mask2D, False)
		image -= st[0]
		image /= st[1]
		cimage = image.copy()
		if Tracker["applybckgnoise"]:
			if Tracker["applymask"]:
				if Tracker["constants"]["hardmask"]: cimage = cosinemask(cimage, radius = Tracker["constants"]["radius"])
				else:
					bckg = model_gauss_noise(1.0,Tracker["constants"]["nnxo"]+2,Tracker["constants"]["nnxo"])
					bckg.set_attr("is_complex",1)
					bckg.set_attr("is_fftpad",1)
					bckg = fft(filt_table(bckg, oneover[particle_group_id]))
					#  Normalize bckg noise in real space, only region actually used.
					st = Util.infomask(bckg, mask2D, False)
					bckg -= st[0]
					bckg /= st[1]
					cimage = cosinemask(cimage,radius = Tracker["constants"]["radius"], bckg = bckg)
		else:
			if Tracker["applymask"]: cimage  = cosinemask(cimage, radius = Tracker["constants"]["radius"])
		# FT
		image = fft(image)
		cimage = fft(cimage)		
		if Tracker["constants"]["CTF"] :
			ctf_params = image.get_attr("ctf")
			image = fdecimate(image, Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			cimage = fdecimate(cimage, Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			ctf_params.apix = ctf_params.apix/shrinkage
			image.set_attr('ctf', ctf_params)
			cimage.set_attr('ctf', ctf_params)
			image.set_attr('ctf_applied', 0)
			cimage.set_attr('ctf_applied', 0)
			if return_real:image = fft(image)
		else:
			ctf_params = image.get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				image.set_attr('ctf', ctf_params)
				image.set_attr('ctf_applied', 0)
				cimage.set_attr('ctf', ctf_params)
				cimage.set_attr('ctf_applied', 0)
			image = fdecimate(image, nxinit*npad, nxinit*npad, 1, True, False)
			cimage = fdecimate(cimage, nxinit*npad, nxinit*npad, 1, True, False)
			apix = Tracker["constants"]["pixel_size"]
			image.set_attr('apix', apix/shrinkage)
			cimage.set_attr('apix', apix/shrinkage)
		cimage.set_attr("padffted",1)
		cimage.set_attr("npad", npad)
		if not return_real:
			image.set_attr("padffted",1)
			image.set_attr("npad", npad)
		set_params_proj(image,[phi, theta, psi, 0.0, 0.0])
		image.set_attr("chunk_id", chunk_id)
		image.set_attr("group", groupids[im])
		image.set_attr("particle_group", particle_group_id)		
		set_params_proj(cimage,[phi, theta, psi, 0.0, 0.0])
		cimage.set_attr("chunk_id", chunk_id)
		cimage.set_attr("group", groupids[im])
		cimage.set_attr("particle_group", particle_group_id)
		rdata[im] =  image
		cdata[im] =  cimage
		if Tracker["applybckgnoise"]: 
			rdata[im].set_attr("bckgnoise", Blockdata["bckgnoise"][particle_group_id])
			if Tracker["constants"]["comparison_method"] == "cross": Util.mulclreal(cdata[im], Blockdata["unrolldata"][particle_group_id])                                
		if Tracker["focus3D"]:
			cdata[im] = fft(binarize(prgl(focus3d, [phi, theta, psi, 0.0, 0.0], 1, True), 1)*fft(cdata[im]))
			if Tracker["constants"]["CTF"]: cdata[im].set_attr("ctf", rdata[im].get_attr("ctf"))
		cdata[im].set_attr("is_complex",0)	
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line,"reading data finishes")
	return cdata, rdata
#####4
def get_shrink_data_final(nxinit, procid, original_data = None, oldparams = None, \
		return_real = False, preshift = False, apply_mask = True, nonorm = False, npad = 1):
	global Tracker, Blockdata
	"""
	This function will read from stack a subset of images specified in partids
	   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	So, the lengths of partids and partstack are the same.
	  The read data is properly distributed among MPI threads.
	
	Flow of data:
	1. Read images, if there is enough memory, keep them as original_data.
	2. Read current params
	3.  Apply shift
	4.  Normalize outside of the radius
	5.  Do noise substitution and cosine mask.  (Optional?)
	6.  Shrink data.
	7.  Apply CTF.
	
	"""
	#from fundamentals import resample
	from utilities    import get_im, model_gauss_noise, set_params_proj, get_params_proj
	from fundamentals import fdecimate, fshift, fft
	from filter       import filt_ctf, filt_table
	from applications import MPI_start_end
	from math         import sqrt
	
	mask2D  	= model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	nima 		= len(original_data)
	shrinkage 	= nxinit/float(Tracker["constants"]["nnxo"])
	#  Note these are in Fortran notation for polar searches
	#txm = float(nxinit-(nxinit//2+1) - radius -1)
	#txl = float(2 + radius - nxinit//2+1)
	radius 	= int(Tracker["constants"]["radius"]*shrinkage + 0.5)
	txm    	= float(nxinit-(nxinit//2+1) - radius)
	txl    	= float(radius - nxinit//2+1)

	if Blockdata["bckgnoise"] :
		oneover = []
		nnx = Blockdata["bckgnoise"][0].get_xsize()
		for i in xrange(len(Blockdata["bckgnoise"])):
			temp = [0.0]*nnx
			for k in xrange(nnx):
				if( Blockdata["bckgnoise"][i].get_value_at(k) > 0.0):  temp[k] = 1.0/sqrt(Blockdata["bckgnoise"][i].get_value_at(k))
			oneover.append(temp)
		del temp
	Blockdata["accumulatepw"][procid] = [None]*nima
	data = [None]*nima
	for im in xrange(nima):
		phi, theta, psi, sx, sy, wnorm = oldparams[im][0], oldparams[im][1], oldparams[im][2], oldparams[im][3], oldparams[im][4], oldparams[im][7]
		if preshift:
			sx = int(round(sx))
			sy = int(round(sy))
			data[im]  = cyclic_shift(original_data[im],sx,sy)
			#  Put rounded shifts on the list, note image has the original floats - check whether it may cause problems
			oldparams[im][3] = sx
			oldparams[im][4] = sy
			sx = 0.0
			sy = 0.0
		else:  data[im] = original_data[im].copy()
		st = Util.infomask(data[im], mask2D, False)
		data[im] -= st[0]
		data[im] /= st[1]
		if data[im].get_attr_default("bckgnoise", None) :  data[im].delete_attr("bckgnoise")
		#  Do bckgnoise if exists
		if Blockdata["bckgnoise"]:
			if apply_mask:
				if Tracker["constants"]["hardmask"]:
					data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"])
				else:
					bckg = model_gauss_noise(1.0,Tracker["constants"]["nnxo"]+2,Tracker["constants"]["nnxo"])
					bckg.set_attr("is_complex",1)
					bckg.set_attr("is_fftpad",1)
					bckg = fft(filt_table(bckg, oneover[data[im].get_attr("particle_group")]))
					#  Normalize bckg noise in real space, only region actually used.
					st = Util.infomask(bckg, mask2D, False)
					bckg -= st[0]
					bckg /= st[1]
					data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"], bckg = bckg)
		else:
			#  if no bckgnoise, do simple masking instead
			if apply_mask:  data[im] = cosinemask(data[im],radius = Tracker["constants"]["radius"] )
		#  Apply varadj
		if not nonorm: Util.mul_scalar(data[im], Tracker["avgvaradj"][procid]/wnorm)
		#  FT
		data[im] = fft(data[im])
		sig = Util.rotavg_fourier( data[im] )
		Blockdata["accumulatepw"][procid][im] = sig[len(sig)//2:]+[0.0]
		if Tracker["constants"]["CTF"] :
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, False, False)
			ctf_params = original_data[im].get_attr("ctf")
			ctf_params.apix = ctf_params.apix/shrinkage
			data[im].set_attr('ctf', ctf_params)
			data[im].set_attr('ctf_applied', 0)
			if return_real: data[im] = fft(data[im])
		else:
			ctf_params = original_data[im].get_attr_default("ctf", False)
			if ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				data[im].set_attr('ctf', ctf_params)
				data[im].set_attr('ctf_applied', 0)
			data[im] = fdecimate(data[im], nxinit*npad, nxinit*npad, 1, True, False)
			apix = Tracker["constants"]["pixel_size"]
			data[im].set_attr('apix', apix/shrinkage)
			
		#  We have to make sure the shifts are within correct range, shrinkage or not
		set_params_proj(data[im],[phi,theta,psi,max(min(sx*shrinkage,txm),txl),max(min(sy*shrinkage,txm),txl)])
		if not return_real: data[im].set_attr("padffted",1)
		data[im].set_attr("npad",npad)
		if Blockdata["bckgnoise"]:
			temp = Blockdata["bckgnoise"][data[im].get_attr("particle_group")]
			###  Do not adjust the values, we try to keep everything in the same Fourier values.
			data[im].set_attr("bckgnoise", [temp[i] for i in xrange(temp.get_xsize())])
	return data
###5
def read_data_for_sorting(partids, partstack, previous_partstack):
	# The function will read from stack a subset of images specified in partids
	# and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.
	global Tracker, Blockdata
	from fundamentals	import resample, fshift
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	from utilities      import wrap_mpi_bcast, read_text_row, get_im, set_params_proj
	# functions:
	# read in data
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			lpartids = lpartids[0]
			groupids = len(lpartids)*[-1]
		else:
			groupids = lpartids[0]
			lpartids = lpartids[1]
	else:  	
		lpartids   = 0
		groupids   = 0
	lpartids = wrap_mpi_bcast(lpartids, Blockdata["main_node"])
	groupids = wrap_mpi_bcast(groupids, Blockdata["main_node"])
	Tracker["total_stack"] = len(lpartids)
	if(Blockdata["myid"] == Blockdata["main_node"]): partstack = read_text_row(partstack)
	else:  partstack = 0
	partstack = wrap_mpi_bcast(partstack, Blockdata["main_node"])
	if(Blockdata["myid"] == Blockdata["main_node"]): previous_partstack = read_text_row(previous_partstack)
	else:  previous_partstack = 0
	previous_partstack = wrap_mpi_bcast(previous_partstack, Blockdata["main_node"])
	if(Tracker["total_stack"] < Blockdata["nproc"]): ERROR("number of processors in use is larger than the total number of particles", \
		  "get_data_and_prep", 1, Blockdata["myid"])
	else: image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	lpartids          = lpartids[image_start:image_end]
	groupids          = groupids[image_start:image_end]
	nima              = image_end - image_start
	data              = [None]*nima
	norm_per_particle = [ None for im in xrange(nima)]
	for im in xrange(nima):
		image = get_im(Tracker["constants"]["orgstack"], lpartids[im])
		try: phi, theta, psi, sx, sy, chunk_id, particle_group_id, mnorm = partstack[lpartids[im]][0], \
		   partstack[lpartids[im]][1], partstack[lpartids[im]][2], \
			partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], \
			   partstack[lpartids[im]][6], partstack[lpartids[im]][7]
		except:
			phi, theta, psi, sx, sy, chunk_id, particle_group_id, mnorm  = partstack[lpartids[im]][0], \
			    partstack[lpartids[im]][1], partstack[lpartids[im]][2], \
		  partstack[lpartids[im]][3], partstack[lpartids[im]][4], partstack[lpartids[im]][5], -1, 1.
		sx1, sy1 = previous_partstack[lpartids[im]][3], previous_partstack[lpartids[im]][4]
		set_params_proj(image,[phi, theta, psi, 0.0, 0.0])
		image.set_attr("chunk_id", chunk_id)
		image.set_attr("group", groupids[im])
		image.set_attr("particle_group", particle_group_id)
		image.set_attr("previous_shifts", [sx1, sy1])
		image.set_attr("current_shifts", [sx, sy])
		norm_per_particle[im] = mnorm
		data[im] = image
	return data, norm_per_particle
###6 read paramstructure

def read_paramstructure_for_sorting(partids, paramstructure_dict_file, paramstructure_dir):
	global Tracker, Blockdata
	from utilities    import read_text_row, read_text_file, wrap_mpi_bcast
	from applications import MPI_start_end
	if( Blockdata["myid"] == Blockdata["main_node"]):lcore = read_text_file(partids, -1)
	else: lcore = 0
	lcore   = wrap_mpi_bcast(lcore, Blockdata["main_node"])
	if len(lcore) == 1: lcore = lcore[0]
	else: lcore = lcore[1]
	psize   = len(lcore)
	oldparamstructure  = []	
	im_start, im_end   = MPI_start_end(psize, Blockdata["nproc"], Blockdata["myid"])
	lcore              = lcore[im_start:im_end]
	nima               = len(lcore)
	if( Blockdata["myid"] == Blockdata["main_node"]): tmp_list = read_text_row(paramstructure_dict_file)
	else: tmp_list = 0
	tmp_list = wrap_mpi_bcast(tmp_list, Blockdata["main_node"])
	pdict    = {}
	for im in xrange(len(lcore)):pdict[im] = tmp_list[lcore[im]]
	oldparamstructure             =  []
	nptl                          =  0
	last_old_paramstructure_file  =  None
	mpi_barrier(MPI_COMM_WORLD)
	for iproc in xrange(Blockdata["nproc"]):
		if (Blockdata["myid"] == iproc): #always read oldparamstructure sequentially
			while nptl < nima:
				[jason_of_cpu_id, chunk_id, iteration, ptl_id_on_cpu, global_index] = pdict[nptl]
				old_paramstructure_file = os.path.join(paramstructure_dir, "oldparamstructure_%d_%03d_%03d.json"%(chunk_id, jason_of_cpu_id, iteration))
				if old_paramstructure_file != last_old_paramstructure_file:
					fout = open(old_paramstructure_file,'r')
					paramstructure = convert_json_fromunicode(json.load(fout))
					fout.close()
				last_old_paramstructure_file = old_paramstructure_file
				oldparamstructure.append(paramstructure[ptl_id_on_cpu])	
				nptl +=1
			mpi_barrier(MPI_COMM_WORLD)
	return oldparamstructure
	
###7 copy oldparamstructures from meridien
def copy_oldparamstructure_from_meridien_MPI(selected_iteration, log):
	global Tracker, Blockdata
	from utilities    import read_text_row, cmdexecute, write_text_row, read_text_file,wrap_mpi_bcast
	from applications import MPI_start_end
	import json
	Tracker["directory"] = os.path.join(Tracker["constants"]["masterdir"], "main%03d"%selected_iteration)
	Tracker["paramstructure_dir"] = os.path.join(Tracker["directory"], "oldparamstructure")
	old_refinement_iter_directory = os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iteration)
	old_refinement_previous_iter_directory = os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%(selected_iteration-1))
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]):
		if not os.path.exists(Tracker["paramstructure_dir"]):
			os.mkdir(os.path.join(Tracker["constants"]["masterdir"], "main%03d"%selected_iteration))
			os.mkdir(Tracker["paramstructure_dir"])
	Tracker["refang"] = read_text_row(os.path.join(old_refinement_iter_directory, "refang.txt"))
	if( Blockdata["myid"] == Blockdata["main_node"]): write_text_row(Tracker["refang"], os.path.join(Tracker["directory"], "refang.txt"))
	Tracker["rshifts"] = read_text_row(os.path.join(old_refinement_iter_directory, "rshifts.txt"))
	if( Blockdata["myid"] == Blockdata["main_node"]): write_text_row(Tracker["refang"], os.path.join(Tracker["directory"], "rshifts.txt"))
	my_last_params = read_text_file(os.path.join(old_refinement_previous_iter_directory, "params_%03d.txt"%(selected_iteration-1)), -1)
	my_parstack    = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "refinement_parameters.txt"), -1)
	if( Blockdata["myid"] == Blockdata["main_node"]):
		my_parstack[3:5]= my_last_params[3:5]
		write_text_file(my_parstack, os.path.join(Tracker["constants"]["masterdir"], "previous_refinement_parameters.txt"))
	Tracker["previous_parstack"] = os.path.join(Tracker["constants"]["masterdir"], "previous_refinement_parameters.txt")
	nproc_previous = 0
	procid         = 0
	old_refinement_iter_dir = os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iteration)
	if Blockdata["myid"] == Blockdata["main_node"]:
		while os.path.exists(os.path.join(old_refinement_iter_dir,"oldparamstructure","oldparamstructure_%01d_%03d_%03d.json"%(procid, nproc_previous, selected_iteration))):
			nproc_previous += 1
	nproc_previous = bcast_number_to_all(nproc_previous, Blockdata["main_node"], MPI_COMM_WORLD)
	Blockdata["nproc_previous"] = nproc_previous
	oldparamstructure =[[], []]
	local_dict = {}
	for procid in xrange(2):
		smearing_list = []
		if( Blockdata["myid"] == Blockdata["main_node"]): lcore = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "chunk_%d.txt"%procid))
		else: lcore = 0
		lcore = wrap_mpi_bcast(lcore, Blockdata["main_node"], MPI_COMM_WORLD)	
		psize = len(lcore)
		oldparamstructure[procid] = []
		im_start, im_end   = MPI_start_end(psize, Blockdata["nproc"], Blockdata["myid"])
		local_lcore = lcore[im_start:im_end]
		istart_old_proc_id = -1
		iend_old_proc_id = -1
		plist = []
		
		for iproc_old in xrange(nproc_previous):
			im_start_old, im_end_old = MPI_start_end(psize, nproc_previous, iproc_old)
			if (im_start>= im_start_old) and im_start <=im_end_old: istart_old_proc_id = iproc_old
			if (im_end>= im_start_old) and im_end <=im_end_old: iend_old_proc_id = iproc_old
			plist.append([im_start_old, im_end_old])
		ptl_on_this_cpu = im_start
		nptl_total = 0
		
		for iproc_index_old in xrange(istart_old_proc_id, iend_old_proc_id+1):
			fout = open(os.path.join(Tracker["constants"]["refinement_dir"],"main%03d"%selected_iteration, "oldparamstructure", "oldparamstructure_%01d_%03d_%03d.json"%(procid, \
			 iproc_index_old, selected_iteration)),'r')
			oldparamstructure_on_old_cpu = convert_json_fromunicode(json.load(fout))
			fout.close()
			mlocal_id_on_old = ptl_on_this_cpu - plist[iproc_index_old][0]
			while (mlocal_id_on_old<len(oldparamstructure_on_old_cpu)) and (ptl_on_this_cpu<im_end):
				oldparamstructure[procid].append(oldparamstructure_on_old_cpu[mlocal_id_on_old])
				local_dict [local_lcore[nptl_total]] = [Blockdata["myid"], procid, selected_iteration, nptl_total, ptl_on_this_cpu]
				ptl_on_this_cpu  +=1
				mlocal_id_on_old +=1
				nptl_total       +=1
				
		del oldparamstructure_on_old_cpu
		mpi_barrier(MPI_COMM_WORLD)
	
		for icpu in xrange(Blockdata["nproc"]):#dump to disk one by one
			if  Blockdata["myid"] == icpu:
				fout = open(os.path.join(Tracker["constants"]["masterdir"], "main%03d"%selected_iteration, "oldparamstructure", "oldparamstructure_%01d_%03d_%03d.json"%(procid, \
					Blockdata["myid"], selected_iteration)),'w')
				json.dump(oldparamstructure[procid], fout)
				fout.close()
				mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		
	# output number of smearing
	smearing_dict = {}
	tchunk = []
	for procid in xrange(2):
		if Blockdata["myid"] == Blockdata["main_node"]:
			chunk = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "chunk_%d.txt"%procid))
			chunk_size = len(chunk)
			smearing_list =[ None for i in xrange(chunk_size) ]
		else: chunk_size = 0
		chunk_size = bcast_number_to_all(chunk_size, Blockdata["main_node"], MPI_COMM_WORLD)
		local_smearing_list = []
		for im in xrange(len(oldparamstructure[procid])):local_smearing_list.append(len(oldparamstructure[procid][im][2]))
			
		if Blockdata["myid"] == Blockdata["main_node"]:
			im_start_old, im_end_old = MPI_start_end(chunk_size, Blockdata["nproc"], Blockdata["main_node"])
			for im in xrange(len(local_smearing_list)): smearing_list[im_start_old+im] = local_smearing_list[im]
		mpi_barrier(MPI_COMM_WORLD)
		
		if  Blockdata["myid"] != Blockdata["main_node"]:
			wrap_mpi_send(local_smearing_list, Blockdata["main_node"], MPI_COMM_WORLD)
		else:
			for iproc in xrange(Blockdata["nproc"]):
				if iproc != Blockdata["main_node"]:
					im_start_old, im_end_old = MPI_start_end(chunk_size, Blockdata["nproc"], iproc)
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for idum in xrange(len(dummy)): smearing_list[idum + im_start_old] = dummy[idum]
				else: pass
			
			write_text_file(smearing_list, os.path.join(Tracker["constants"]["masterdir"], "smearing_%d.txt"%procid))
			for im in xrange(len(chunk)): smearing_dict[chunk[im]] =  smearing_list[im]
			tchunk +=chunk
		mpi_barrier(MPI_COMM_WORLD)
	if Blockdata["myid"] == Blockdata["main_node"]:
		tchunk.sort()
		all_smearing = [None]*len(tchunk)
		for im in xrange(len(tchunk)): all_smearing[im] = smearing_dict[tchunk[im]]
		write_text_file(all_smearing, os.path.join(Tracker["constants"]["masterdir"], "all_smearing.txt"))
		msg =" averaged smearing:  %f"%(sum(all_smearing)/float(len(all_smearing)))
		print(msg)
		log.add(msg)
		full_dict_list = [ None for im in xrange(Tracker["constants"]["total_stack"])]
		for key, value in local_dict.iteritems():full_dict_list[key] = value
	mpi_barrier(MPI_COMM_WORLD)
	for icpu in xrange(Blockdata["nproc"]):
		if Blockdata["myid"] == icpu and Blockdata["myid"] != Blockdata["main_node"]: wrap_mpi_send(local_dict, Blockdata["main_node"], MPI_COMM_WORLD)
		elif Blockdata["myid"] != icpu and Blockdata["myid"] == Blockdata["main_node"]:
			local_dict = wrap_mpi_recv(icpu, MPI_COMM_WORLD)
			for key, value in local_dict.iteritems():
				full_dict_list[key] = value
		else: pass
		mpi_barrier(MPI_COMM_WORLD)
	Tracker["paramstructure_dict"] = os.path.join(Tracker["constants"]["masterdir"], "paramstructure_dict.txt")
	if Blockdata["myid"] == Blockdata["main_node"]: write_text_row(full_dict_list, Tracker["paramstructure_dict"])
	return
	
### 8
def precalculate_shifted_data_for_recons3D(prjlist, paramstructure, refang, rshifts, delta, avgnorms, nxinit, nnxo, nosmearing, norm_per_particle = None, upweighted=False, nsmear =-1):
	from utilities    import random_string, get_im, findall, info, model_blank
	from filter	      import filt_table
	from fundamentals import fshift
	import types
	import datetime
	import copy
	if norm_per_particle == None: norm_per_particle = len(prjlist)*[1.0]
	nnx = prjlist[0].get_xsize()
	nny = prjlist[0].get_ysize()
	if not nosmearing:
		recdata_list = [[] for im in xrange(len(prjlist))]	
		rshifts_shrank = copy.deepcopy(rshifts)
		for im in xrange(len(rshifts_shrank)):
			rshifts_shrank[im][0] *= float(nxinit)/float(nnxo)
			rshifts_shrank[im][1] *= float(nxinit)/float(nnxo)
		nshifts = len(rshifts_shrank)
	for im in xrange(len(prjlist)):
		bckgn = prjlist[im].get_attr("bckgnoise")
		ct = prjlist[im].get_attr("ctf")
		group_id = prjlist[im].get_attr("group")
		if nosmearing:
			phi,theta,psi,s2x,s2y = get_params_proj(prjlist[im], xform = "xform.projection")
			prjlist[im].set_attr("wprob", 1.0)
			prjlist[im].set_attr("group", group_id)
			prjlist[im].set_attr_dict( {"bckgnoise":bckgn, "ctf":ct})
			prjlist[im].set_attr_dict({"padffted":1, "is_fftpad":1,"is_fftodd":0, "is_complex_ri":1, "is_complex":1})
			if not upweighted:prjlist[im] = filt_table(prjlist[im], bckgn)
			set_params_proj(prjlist[im],[ phi, theta, psi, 0.0, 0.0], xform = "xform.projection")
		else:
			avgnorm = avgnorms[prjlist[im].get_attr("chunk_id")]
			#if nsmear <=0.0: numbor = len(paramstructure[im][2])
			#else:         numbor = 1
			numbor      = len(paramstructure[im][2])
			ipsiandiang = [ paramstructure[im][2][i][0]/1000  for i in xrange(numbor) ]
			allshifts   = [ paramstructure[im][2][i][0]%1000  for i in xrange(numbor) ]
			probs       = [ paramstructure[im][2][i][1] for i in xrange(numbor) ]
			tdir = list(set(ipsiandiang))
			data = [None]*nshifts
			for ii in xrange(len(tdir)):
				#  Find the number of times given projection direction appears on the list, it is the number of different shifts associated with it.
				lshifts = findall(tdir[ii], ipsiandiang)
				toprab  = 0.0
				for ki in xrange(len(lshifts)):toprab += probs[lshifts[ki]]
				recdata = EMData(nny,nny,1,False)
				recdata.set_attr("is_complex",0)
				for ki in xrange(len(lshifts)):
					lpt = allshifts[lshifts[ki]]
					if(data[lpt] == None):
						data[lpt] = fshift(prjlist[im], rshifts_shrank[lpt][0], rshifts_shrank[lpt][1])
						data[lpt].set_attr("is_complex",0)
					Util.add_img(recdata, Util.mult_scalar(data[lpt], probs[lshifts[ki]]/toprab))
				recdata.set_attr_dict({"padffted":1, "is_fftpad":1,"is_fftodd":0, "is_complex_ri":1, "is_complex":1}) # preset already
				if not upweighted:recdata = filt_table(recdata, bckgn)
				recdata.set_attr_dict( {"bckgnoise":bckgn, "ctf":ct})
				ipsi = tdir[ii]%100000
				iang = tdir[ii]/100000
				set_params_proj(recdata,[refang[iang][0],refang[iang][1], refang[iang][2]+ipsi*delta, 0.0, 0.0], xform = "xform.projection")
				recdata.set_attr("wprob", toprab*avgnorm/norm_per_particle[im])
				recdata.set_attr("group", group_id)
				recdata_list[im].append(recdata)
	if nosmearing:return prjlist
	else:
		del bckgn, recdata, tdir, ipsiandiang, allshifts, probs, data
		return recdata_list
##### read data/paramstructure ends
###<<<----downsize data---->>>>
def downsize_data_for_sorting(original_data, return_real = False, preshift = True, npad = 1, norms = None):
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.
	global Tracker, Blockdata
	from fundamentals	import resample, fshift, cyclic_shift
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	# functions:
	# read in data
	# apply mask, and prepare focus projection if focus3D is specified
	# return  1. cdata: data for image comparison, always in Fourier format
	#         2. rdata: data for reconstruction, 4nn return real image
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line,"downsize_data_for_sorting ")		
	mask2D		= model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	shrinkage 	= Tracker["nxinit"]/float(Tracker["constants"]["nnxo"])
	radius      = int(Tracker["constants"]["radius"] * shrinkage +0.5)
	if Tracker["applybckgnoise"]:
		oneover = []
		nnx     = len(Blockdata["bckgnoise"][0])
		for i in xrange(len(Blockdata["bckgnoise"])):
			temp = [0.0]*nnx
			for k in xrange(nnx):
				if(Blockdata["bckgnoise"][i][k] > 0.0): temp[k] = 1.0/sqrt(Blockdata["bckgnoise"][i][k])
			oneover.append(temp)
		del temp
	if Tracker["focus3D"]: # focus mask is applied
		if Blockdata["myid"] == Blockdata["main_node"]:
			focus3d    = get_im(Tracker["focus3D"])
			focus3d_nx = focus3d.get_xsize()
			if focus3d_nx != Tracker["nxinit"]: # So the decimated focus volume can be directly used
				focus3d = resample(focus3d, float(Tracker["nxinit"])/float(focus3d_nx))
		else: focus3d = model_blank(Tracker["nxinit"], Tracker["nxinit"], Tracker["nxinit"])
		bcast_EMData_to_all(focus3d, Blockdata["myid"], Blockdata["main_node"])
		focus3d = prep_vol(focus3d, 1, 1)
	#  Preprocess the data
	nima   = len(original_data)
	cdata  = [None]*nima
	rdata  = [None]*nima
	fdata  = [None]*nima	# focusmask projections
	for im in xrange(nima):
		image = original_data[im].copy()
		chunk_id = image.get_attr("chunk_id")
		try: group_id = image.set_attr("group", groupids[im])
		except: pass
		particle_group_id = image.get_attr("particle_group")
		phi,theta,psi,s2x,s2y = get_params_proj(image, xform = "xform.projection")
		[sx, sy]   = image.get_attr("previous_shifts")
		[sx1, sy1] = image.get_attr("current_shifts")
		rimage = cyclic_shift(image, int(round(sx)), int(round(sy)))
		cimage = fshift(image, sx1, sy1)		
		st = Util.infomask(rimage, mask2D, False)
		rimage -= st[0]
		rimage /= st[1]
		st = Util.infomask(cimage, mask2D, False)
		cimage -= st[0]
		cimage /= st[1]
		
		if not Tracker["nosmearing"] and norms: cimage *= Tracker["avgnorm"][chunk_id]/norms[im] #norm correction
		
		if Tracker["applybckgnoise"]:
			if Tracker["applymask"]:
				if Tracker["constants"]["hardmask"]: cimage = cosinemask(cimage, radius = Tracker["constants"]["radius"])
				else:
					bckg = model_gauss_noise(1.0,Tracker["constants"]["nnxo"]+2,Tracker["constants"]["nnxo"])
					bckg.set_attr("is_complex",1)
					bckg.set_attr("is_fftpad",1)
					bckg = fft(filt_table(bckg, oneover[particle_group_id]))
					#  Normalize bckg noise in real space, only region actually used.
					st = Util.infomask(bckg, mask2D, False)
					bckg -= st[0]
					bckg /= st[1]
					cimage = cosinemask(cimage,radius = Tracker["constants"]["radius"], bckg = bckg)
		else:
			if Tracker["applymask"]:cimage  = cosinemask(cimage, radius = Tracker["constants"]["radius"])
			else: pass
		# FT
		rimage  = fft(rimage)
		cimage  = fft(cimage)
		if Tracker["constants"]["CTF"] :
			ctf_params = rimage.get_attr("ctf")
			rimage      = fdecimate(rimage, Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			cimage     = fdecimate(cimage, Tracker["nxinit"]*npad, Tracker["nxinit"]*npad, 1, False, False)
			ctf_params.apix = ctf_params.apix/shrinkage
			rimage.set_attr('ctf', ctf_params)
			cimage.set_attr('ctf', ctf_params)
			rimage.set_attr('ctf_applied', 0)
			cimage.set_attr('ctf_applied', 0)
			if return_real :  rimage = fft(rimage)
		else:
			ctf_params = rimage.get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				rimage.set_attr('ctf', ctf_params)
				rimage.set_attr('ctf_applied', 0)
				cimage.set_attr('ctf', ctf_params)
				cimage.set_attr('ctf_applied', 0)
				
			rimage  = fdecimate(rimage, nxinit*npad, nxinit*npad, 1, True, False)
			cimage = fdecimate(cimage, nxinit*npad, nxinit*npad, 1, True, False)
			apix   = Tracker["constants"]["pixel_size"]
			rimage.set_attr('apix', apix/shrinkage)
			cimage.set_attr('apix', apix/shrinkage)
		
		cimage.set_attr("padffted",1)
		cimage.set_attr("npad", npad)
		if not return_real:	
			rimage.set_attr("padffted",1)
			rimage.set_attr("npad", npad)
			
		set_params_proj(rimage,[phi, theta, psi, 0.0, 0.0])
		rimage.set_attr("chunk_id", chunk_id)
		#image.set_attr("group", groupids[im])
		rimage.set_attr("particle_group", particle_group_id)
		
		set_params_proj(cimage,[phi, theta, psi, 0.0, 0.0])
		cimage.set_attr("chunk_id", chunk_id)
		#cimage.set_attr("group", groupids[im])
		cimage.set_attr("particle_group", particle_group_id)
		rdata[im] =  rimage
		cdata[im] =  cimage		
		if Tracker["applybckgnoise"]:
			rdata[im].set_attr("bckgnoise", Blockdata["bckgnoise"][particle_group_id])
		else:
			rdata[im].set_attr("bckgnoise",  Blockdata["bckgnoise"])
			cdata[im].set_attr("bckgnoise",  Blockdata["bckgnoise"])                    
		if Tracker["focus3D"]:
			focusmask = binarize(prgl(focus3d, [phi, theta, psi, 0.0, 0.0], 1, True), 1)
			cdata[im] = fft(focusmask*fft(cdata[im]))
			if Tracker["constants"]["CTF"]: cdata[im].set_attr("ctf", rdata[im].get_attr("ctf"))
			fdata[im] = focusmask
		cdata[im].set_attr("is_complex",0)
	return cdata, rdata, fdata
##<<<----for 3D----->>>>
def downsize_data_for_rec3D(original_data, particle_size, return_real = False, npad = 1):
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack with optional CTF application and shifting of the data.
	# So, the lengths of partids and partstack are the same.	
	global Tracker, Blockdata
	from fundamentals	import resample, fshift
	from filter			import filt_ctf
	from applications	import MPI_start_end
	from EMAN2          import Region
	# functions:
	# read in data
	# apply mask, and prepare focus projection if focus3D is specified
	# return  1. cdata: data for image comparison, always in Fourier format
	#         2. rdata: data for reconstruction, 4nn return real image
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]): print(line, "downsize_data_for_rec3D ")		
	nima       = len(original_data)
	rdata      = [None]*nima
	mask2D     = model_circle(Tracker["constants"]["radius"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
	shrinkage  = particle_size/float(Tracker["constants"]["nnxo"])
	radius     = int(Tracker["constants"]["radius"] * shrinkage +0.5)
	for im in xrange(nima):
		image = original_data[im].copy()
		chunk_id = image.get_attr("chunk_id")
		try: particle_group_id = image.get_attr("particle_group")
		except: particle_group_id = -1
		phi,theta,psi,s2x,s2y = get_params_proj(image, xform = "xform.projection")
		[sx, sy] = image.get_attr("previous_shifts") # always for rec3D
		if Tracker["nosmearing"]: image = fshift(image, s2x, s2y)
		else: image = cyclic_shift(image, int(round(sx)), int(round(sy)))
		st = Util.infomask(image, mask2D, False)
		image -= st[0]
		image /= st[1]
		image  = fft(image)
		if Tracker["constants"]["CTF"]:
			ctf_params = image.get_attr("ctf")
			image = fdecimate(image, particle_size*npad, particle_size*npad, 1, False, False)
			ctf_params.apix = ctf_params.apix/shrinkage
			image.set_attr('ctf', ctf_params)
			image.set_attr('ctf_applied', 0)
		else:
			ctf_params = image.get_attr_default("ctf", False)
			if  ctf_params:
				ctf_params.apix = ctf_params.apix/shrinkage
				image.set_attr('ctf', ctf_params)
				image.set_attr('ctf_applied', 0)
			image = fdecimate(image, particle_size*npad, particle_size*npad, 1, True, False)
			apix  = Tracker["constants"]["pixel_size"]
			image.set_attr('apix', apix/shrinkage)		
		if not return_real:	
			image.set_attr("padffted",1)
			image.set_attr("npad", npad)
		image.set_attr("chunk_id", chunk_id)
		image.set_attr("particle_group", particle_group_id)
		set_params_proj(image,[phi, theta, psi, 0.0, 0.0])
		rdata[im] =  image
		if Tracker["applybckgnoise"]: rdata[im].set_attr("bckgnoise", Blockdata["bckgnoise"][rdata[im].get_attr("particle_group")])
		else: rdata[im].set_attr("bckgnoise", Blockdata["bckgnoise"])
	return rdata
### end of downsize

###<<<--- comparison	    
def compare_two_images_eucd(data, ref_vol, fdata):
	global Tracker, Blockdata
	peaks   = len(data)*[None]
	ny      = data[0].get_ysize()
	ref_vol = prep_vol(ref_vol, npad = 2, interpolation_method = 1)
	ctfs    = [ctf_img_real(ny, q.get_attr('ctf')) for q in data]
	qt = float(Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"])
	for im in xrange(len(data)):
		phi, theta, psi, s2x, s2y = get_params_proj(data[im], xform = "xform.projection")
		if Tracker["focus3D"]:
			rtemp = prgl(ref_vol,[phi, theta, psi, 0.0,0.0], 1, True)
			rtemp = fft(rtemp*fdata[im])
		else:
			rtemp = prgl(ref_vol,[phi, theta, psi, 0.0,0.0], 1, False)
		rtemp.set_attr("is_complex",0)
		if data[im].get_attr("is_complex") ==1: data[im].set_attr("is_complex",0)
		
		if Tracker["applybckgnoise"]:
			peaks[im] = -Util.sqed(data[im], rtemp, ctfs[im], Blockdata["unrolldata"][data[im].get_attr("particle_group")])/qt
		else:
			peaks[im] = -Util.sqed(data[im], rtemp, ctfs[im], Blockdata["unrolldata"])/qt
	return peaks
#
def compare_two_images_cross(data, ref_vol):
	global Tracker, Blockdata
	ny    = data[0].get_ysize()
	peaks = len(data)*[None]
	volft = prep_vol(ref_vol, 2, 1)
	ctfs  = [None for im in xrange(len(data))]
	for im in xrange(len(data)): ctfs[im]  = ctf_img_real(ny, data[im].get_attr('ctf'))
	#  Ref is in reciprocal space
	for im in xrange(len(data)):
		phi, theta, psi, s2x, s2y = get_params_proj(data[im], xform = "xform.projection")
		ref = prgl( volft, [phi, theta, psi, 0.0, 0.0], 1, False)
		Util.mulclreal(ref, ctfs[im])
		ref.set_attr("is_complex", 0)
		ref.set_value_at(0,0,0.0)
		nrmref = sqrt(Util.innerproduct(ref, ref, None))
		if data[im].get_attr("is_complex") ==1: data[im].set_attr("is_complex",0)
		if Tracker["focus3D"]: peaks[im] = Util.innerproduct(ref, data[im], None)/nrmref
		else:
			if Tracker["applybckgnoise"]:  peaks[im] = Util.innerproduct(ref, data[im], Blockdata["unrolldata"][data[im].get_attr("particle_group")])/nrmref
			else:                          peaks[im] = Util.innerproduct(ref, data[im], None)/nrmref
	return peaks
	
###<<<---various utilities
def clusters_to_plist(clusters, pall):
	# clusters contains the original ids
	pdict = {}
	plist = []
	qlist = []
	for igrp in xrange(len(clusters)):
		clusters[igrp].tolist()
		for a in clusters[igrp]: 
			pdict[pall[a]] = igrp
			plist.append(pall[a])
	plist      = sorted(plist)
	assignment = [ None for im in xrange(len(plist))]
	for im in xrange(len(plist)):
		assignment[im] = pdict[plist[im]]
		qlist.append([pdict[plist[im]], plist[im]])
	a =  set(pall)
	b =  set(plist)
	unaccounted = list(a.difference(b))
	return [assignment, plist], qlist, unaccounted
	
#####<<<<--------------------utilities of creating random assignments
def create_nrandom_lists(partids, number_of_groups, number_of_runs):
	# the second column denotes orignal particle IDs
	# the first column is randomized group ID 
	global Tracker, Blockdata
	import copy
	import random
	from   utilities import wrap_mpi_bcast, read_text_file, write_text_file
	if Blockdata["myid"] == Blockdata["main_node"]:
		random_assignment = []
		data_list = read_text_file(partids, -1)
		if len(data_list)==1: sorting_data_list = data_list[0]
		else: sorting_data_list= data_list[1]
		random.seed()
		group_size = len(sorting_data_list)//number_of_groups
		for index_of_random in xrange(number_of_runs):
			particle_dict = {}
			ll = copy.deepcopy(sorting_data_list)
			random.shuffle(ll)
			group_list = []
			for index_of_groups in xrange(number_of_groups):
				if index_of_groups != number_of_groups-1:
					for iparticle in ll[index_of_groups*group_size:(index_of_groups+1)*group_size]:
						particle_dict[iparticle] = index_of_groups
						group_list.append(index_of_groups)
				else:
					for iparticle in ll[index_of_groups*group_size:]:
						particle_dict[iparticle] = index_of_groups
						group_list.append(index_of_groups)
			assignment = []
			for im in xrange(len(sorting_data_list)):
				assignment.append([particle_dict[sorting_data_list[im]], sorting_data_list[im]])
			random_assignment.append(assignment)
			del assignment
			del ll
	else:
		random_assignment = 0
	random_assignment = wrap_mpi_bcast(random_assignment , Blockdata["main_node"])
	return  random_assignment

def create_nrandom_lists_from_given_pids(work_dir, partids, number_of_groups, number_of_runs):
	# the second column denotes orignal particle IDs
	# the first column is randomized group ID 
	global Tracker, Blockdata
	import copy
	import random
	from   utilities import wrap_mpi_bcast, read_text_file, write_text_file
	if Blockdata["myid"] == Blockdata["main_node"]:
		random_assignment = []
		data_list = read_text_file(partids, -1)
		if len(data_list)==1: sorting_data_list= data_list[0]
		else: sorting_data_list = data_list[1]
		random.seed()
		group_size = len(sorting_data_list)//number_of_groups
		for index_of_random in xrange(number_of_runs):
			particle_dict = {}
			ll = copy.deepcopy(sorting_data_list)
			random.shuffle(ll)
			group_list = []
			for index_of_groups in xrange(number_of_groups):
				if index_of_groups != number_of_groups -1:
					for iparticle in ll[index_of_groups*group_size:(index_of_groups+1)*group_size]:
						particle_dict[iparticle] = index_of_groups
						group_list.append(index_of_groups)
				else:
					for iparticle in ll[index_of_groups*group_size:]:
						particle_dict[iparticle] = index_of_groups
						group_list.append(index_of_groups)
			assignment = []
			for im in xrange(len(sorting_data_list)):
				assignment.append([particle_dict[sorting_data_list[im]], sorting_data_list[im]])
			write_text_row(assignment, os.path.join(work_dir,"independent_index_%03d.txt"%index_of_random))
			random_assignment.append(assignment)
			del assignment
			del ll
	else: random_assignment = 0
	random_assignment = wrap_mpi_bcast(random_assignment, Blockdata["main_node"])
	return  random_assignment

def	reassign_nrandom_lists(Accounted_on_disk, Unaccounted_on_disk, nrandom_trials):
	global Tracker, Blockdata
	import random
	if Blockdata["myid"] == Blockdata["main_node"]:
		ptl_dict = {}
		accounted = read_text_file(Accounted_on_disk, -1)
		number_of_groups = max(accounted[0]) + 1
		groups = [[] for igrp in xrange(number_of_groups)]
		unaccounted = read_text_file(Unaccounted_on_disk)
		for im in xrange(len(accounted[0])):
			groups[accounted[0][im]].append(accounted[1][im])
			ptl_dict[accounted[1][im]] = accounted[0][im]
		accounted_members = sorted(accounted[1])
		if len(unaccounted)>1: unaccounted = sorted(unaccounted)
		full_list = (accounted_members + unaccounted)
		full_list.sort()
		total_stack = len(full_list)
		group_size = total_stack//number_of_groups
	else:
		number_of_groups = 0
		total_stack      = 0
		unaccounted      = 0
		groups           = 0
	number_of_groups = bcast_number_to_all(number_of_groups, Blockdata["main_node"], MPI_COMM_WORLD)
	total_stack      = bcast_number_to_all(total_stack, Blockdata["main_node"], MPI_COMM_WORLD)
	unaccounted      = wrap_mpi_bcast(unaccounted, Blockdata["main_node"], MPI_COMM_WORLD)
	groups           = wrap_mpi_bcast(groups, Blockdata["main_node"], MPI_COMM_WORLD)
	###-----
	if len(unaccounted)<100*Blockdata["nproc"]:
		if Blockdata["myid"] == Blockdata["main_node"]:
			assignment_list = []
			for indep in xrange(nrandom_trials):
				unaccounted_members = copy.deepcopy(unaccounted)
				new_groups = copy.deepcopy(groups)
				new_groups = assign_unaccounted_elements(unaccounted_members, new_groups, total_stack)
				alist, plist = merge_classes_into_partition_list(new_groups)
				tmp_assignment = [[],[]]
				for im in xrange(len(plist)):
					for jm in xrange(2):
						tmp_assignment[jm].append(plist[im][jm])
				assignment_list.append(tmp_assignment)
				del unaccounted_members
				del new_groups
		else: assignment_list = 0
		assignment_list = wrap_mpi_bcast(assignment_list, Blockdata["main_node"], MPI_COMM_WORLD)
		if Blockdata["myid"] == Blockdata["main_node"]: del ptl_dict
	else:
		assignment_list = []
		for indep in xrange(nrandom_trials):
			unaccounted_members = copy.deepcopy(unaccounted)
			new_groups = copy.deepcopy(groups)
			new_groups = assign_unaccounted_elements_mpi(unaccounted_members, new_groups, total_stack)
			alist, plist = merge_classes_into_partition_list(new_groups)
			tmp_assignment = [[],[]]
			for im in xrange(len(plist)):
				for jm in xrange(2):
					tmp_assignment[jm].append(plist[im][jm])
			assignment_list.append(tmp_assignment)
			del unaccounted_members
			del new_groups
			mpi_barrier(MPI_COMM_WORLD)
	return assignment_list
	
def resize_groups_from_stable_members_mpi(Accounted_on_disk, Unaccounted_on_disk):
	global Tracker, Blockdata
	import random
	if Blockdata["myid"] == Blockdata["main_node"]:
		ptl_dict   = {}
		accounted  = read_text_file(Accounted_on_disk, -1)
		number_of_groups = max(accounted[0]) + 1
		groups = [[] for igrp in xrange(number_of_groups)]
		unaccounted = read_text_file(Unaccounted_on_disk)
		for im in xrange(len(accounted[0])):
			groups[accounted[0][im]].append(accounted[1][im])
			ptl_dict[accounted[1][im]] = accounted[0][im]
		accounted_members = sorted(accounted[1])
		if len(unaccounted)>1:
			unaccounted = sorted(unaccounted)
		full_list = accounted_members + unaccounted
		full_list = sorted(full_list)
		total_stack = len(full_list)
		group_size = int(float(total_stack)/number_of_groups)
	else:
		number_of_groups = 0
		total_stack      = 0
		accounted_members = 0
	number_of_groups = bcast_number_to_all(number_of_groups, Blockdata["main_node"], MPI_COMM_WORLD)
	total_stack = bcast_number_to_all(total_stack, Blockdata["main_node"], MPI_COMM_WORLD)
	accounted_members = wrap_mpi_bcast(accounted_members, Blockdata["main_node"], MPI_COMM_WORLD)
	
	###-----
	if Blockdata["myid"] == Blockdata["main_node"]:
		assignment_list = []
		for indep in xrange(1):
			print("after iter %d"%indep)
			unaccounted_members = copy.deepcopy(unaccounted)
			new_groups = copy.deepcopy(groups)
			new_groups = assign_unaccounted_elements(unaccounted_members, new_groups, total_stack)
			print ("unaccounted, resize", len(unaccounted_members))
			assignment = [None for iptl in xrange(len(full_list))]
			for im in xrange(len(full_list)): assignment[im] = ptl_dict[full_list[im]]
			assignment_list = [assignment, full_list]
			del unaccounted_members

	else: assignment_list = 0
	mpi_barrier(MPI_COMM_WORLD)
	assignment_list = wrap_mpi_bcast(assignment_list, Blockdata["main_node"], MPI_COMM_WORLD)
	if Blockdata["myid"] == Blockdata["main_node"]: del ptl_dict
	return assignment_list

def find_smallest_group(clusters):
	min_size =[len(clusters[0]), [0]]
	for ic in xrange(1, len(clusters)):
		if len(cluster[ic]) < min_size[0]: min_size = [len(clusters[ic]), [ic]]
		elif len(cluster[ic]) == min_size[0]: min_size[1].append(ic)
	if len(min_size[1])>=1: shuffle(min_size[1])
	return min_size[1][0]

def assign_unaccounted_elements(glist, clusters):
	# assign unaccounted particles by group probabilities
	import random
	import copy
	ulist = copy.deepcopy(glist)
	while len(ulist)>0:
		shuffle(ulist)
		im = find_smallest_group(clusters)
		clusters[im].append(ulist[0])
		del ulist[0]
	del ulist
	return clusters
	
def assign_unaccounted_elements_even(glist, clusters, total_data):
	# assign unaccounted particles by group probabilities
	import random
	import copy
	while len(ulist)>0:
		im =  random.randint(0, (len(clusters)-1))
		shuffle(ulist)
		clusters[im].append(ulist[0])
		del ulist[0]
	del ulist
	return clusters

def assign_unaccounted_elements_mpi(glist, clusters, img_per_grp):
	# assign unaccounted particles by group probabilities
	global Tracker, Blockdata
	import random
	import copy
	#if Blockdata["myid"]== Blockdata["main_node"]:print("refilling: assign_unaccounted_elements_mpi")	
	icut = 3*img_per_grp//2
	if Blockdata["myid"]== Blockdata["main_node"]:
		for ic in xrange(len(clusters)):
			if len(clusters)>(3*img_per_grp//2):
				shuffle(clusters[ic])
				glist +=clusters[ic][icut:]
	else:
		glist    = 0
		clusters = 0
	clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	glist    = wrap_mpi_bcast(glist, Blockdata["main_node"], MPI_COMM_WORLD)
	
	if len(glist) <= Blockdata["nproc"]*30:
		if Blockdata["myid"]== Blockdata["main_node"]:
			clusters = assign_unaccounted_inverse_proportion_to_size(glist, clusters, img_per_grp)
		else: clusters = 0
		clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	else:
		slist = []
		clist = []
		for ic in xrange(len(clusters)):
			if len(clusters[ic])<=img_per_grp:
				slist.append(max(1.- float(len(clusters[ic]))/float(img_per_grp), 0.05))
			else: slist.append(0.05)
		uplist = copy.deepcopy(glist)
		image_start, image_end = MPI_start_end(len(uplist), Blockdata["nproc"], Blockdata["myid"])
		uplist = uplist[image_start:image_end]
		nsize  = len(uplist)//3
		for ichunk in xrange(3):
			if ichunk !=2: ulist = uplist[ichunk*nsize:(ichunk+1)*nsize]
			else: ulist = uplist[ichunk*nsize:]
			while len(ulist)>0:
				im =  random.randint(0, len(clusters)-1)
				shuffle(ulist)
				if slist[im] > random.random():
					clusters[im].append(ulist[0])
					if len(clusters[ic])<=img_per_grp:
						slist[im] = max(1.- float(len(clusters[im]))/float(img_per_grp), 0.05)
					else: slist[im] = 0.05
					del ulist[0]
					if len(ulist)== 0: break
				else: continue
			mpi_barrier(MPI_COMM_WORLD)
			if Blockdata["myid"]!= Blockdata["main_node"]:
				 wrap_mpi_send(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			else:
				for iproc in xrange(Blockdata["nproc"]):
					if iproc != Blockdata["main_node"]:
						dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
						for ic in xrange(len(clusters)):clusters[ic]+=dummy[ic]
			mpi_barrier(MPI_COMM_WORLD)
			if Blockdata["myid"]== Blockdata["main_node"]:
				for ic in  xrange(len(clusters)): 
					clusters[ic] = list(set(clusters[ic]))
					if len(clusters[ic])<=img_per_grp:
						slist[ic] = max(1.- float(len(clusters[ic]))/float(img_per_grp), 0.05)
					else: slist[ic] = 0.05
			else:
				slist    = 0 
				clusters = 0
			slist    = wrap_mpi_bcast(slist, Blockdata["main_node"], MPI_COMM_WORLD)
			clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	return clusters

def swap_elements_by_probability(clusters, unaccounted_list, total_stack, minimum_grp_size, swap_ratio, log_file):
	global Tracker, Blockdata
	import random
	slist = [0.0 for ic in xrange(len(clusters))]
	tot   = 0
	for ic in xrange(len(clusters)):
		slist[ic] = float(len(clusters[ic]))/float(total_stack)
		tot +=len(clusters[ic])
	rlist   = []
	swapped = [[] for ic in xrange(len(clusters))]
	if Blockdata["myid"] == Blockdata["main_node"]:
		total_swap = int(tot*swap_ratio/100.)
		while total_swap>0:
			im =  random.randint(0, (len(clusters)-1))
			if slist[im] > random.random():
				if len(clusters[im])>= minimum_grp_size: # swap only those with large group size
					shuffle(unaccounted_list)
					swapped[im]+=[unaccounted_list[0]]
					del unaccounted_list[0]
					one_cluster = clusters[im]
					shuffle(one_cluster)
					rlist.append(one_cluster[0])
					del one_cluster[0]
					clusters[im] = one_cluster
					slist[im] = float(len(clusters[im]))/float(total_stack)
				total_swap -=1
			else: continue	
		unaccounted_list +=rlist
		unaccounted_list.sort()
		for ic in xrange(len(clusters)):
			msg = " cluster ID %3d    swapped elements %6d"%(ic,len(swapped[ic]))
			log_file.add(msg)
			print(msg)
			one_cluster = clusters[ic]
			one_cluster +=swapped[ic]
			one_cluster.sort()
			clusters[ic] = one_cluster
	else:
		clusters = 0
		unaccounted_list = 0
		total_stack = 0
	clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
	return clusters, unaccounted_list
	
def swap_elements_by_percentage(clusters, unaccounted_list, total_stack, swap_ratio):
	global Tracker, Blockdata
	import random
	if Blockdata["myid"] == Blockdata["main_node"]:
		tota = 0
		for ic in xrange(len(clusters)):
			tota +=len(clusters[ic])
		tot = int(tota*swap_ratio/100.)
		rlist = []
		new_clusters  = []
		for ic in xrange(len(clusters)):
			one_cluster = clusters[ic]
			shuffle(one_cluster)
			nc = int(len(one_cluster)*swap_ratio/100.)
			shuffle(unaccounted_list)
			rlist +=one_cluster[0:nc]
			del one_cluster[0:nc]
			one_cluster +=unaccounted_list[0:nc]
			one_cluster.sort()
			new_clusters.append(one_cluster)
			del unaccounted_list[0:nc]
		clusters = copy.deepcopy(new_clusters)
		del new_clusters
		unaccounted_list +=rlist
		msg = "NUACC: %d swap ratio: %f swap elements:  %d"%(len(unaccounted_list), swap_ratio, int(tot*swap_ratio))
		log_file.add(msg)
		print(msg)
		### reassign ulist into alist randomly while evenly
	else:
		clusters = 0
		unaccounted_list = 0
	clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
	return clusters, unaccounted_list
	
def check_unicorn_cluster(clusters, minimum_grp_size):
	is_unicorn_cluster = 0
	nc  = 0
	tot = 0
	for ic in xrange(len(clusters)):
		tot += len(clusters[ic])
		if len(clusters[ic]) < minimum_grp_size + len(clusters): nc +=1
	if tot//minimum_grp_size>2*len(clusters) and nc+1==len(clusters):is_unicorn_cluster =1
	return is_unicorn_cluster

def refilling_global_scheme_mpi(clusters, unaccounted_list, number_of_clusters, log_file, swap_ratio):
	global Tracker, Blockdata
	#if Blockdata["myid"] == Blockdata["main_node"]:
	#	msg = "refilling_global_scheme_mpi"
	#	#print(msg)
	#	log_file.add(msg)
	m     = 0
	NACC  = 0
	NUACC = len(unaccounted_list)
	for cluster in clusters: NACC += len(cluster)	
	swap_ratio /=100.
	N  = NUACC + NACC
	m = number_of_clusters - len(clusters)
	if Blockdata["myid"] == Blockdata["main_node"]:
		msg = "NACC %d NUACC %d  K %d m %d  number_of_clusters %d"%(NACC, NUACC, (len(clusters)), m, number_of_clusters)
		log_file.add(msg)
		#print(msg)
	# shake
	if swap_ratio > 0.0:
		if Blockdata["myid"] == Blockdata["main_node"]:
			if int(swap_ratio*NACC) > NUACC:
				msg = "shake_clusters_small_NUACC"
				log_file.add(msg)
				unaccounted_list, clusters = shake_clusters_small_NUACC(\
						 unaccounted_list, clusters, swap_ratio)
			else:
				msg = "shake_clusters_large_NUACC"
				log_file.add(msg)
				unaccounted_list, clusters = shake_clusters_large_NUACC(\
						 unaccounted_list, clusters, swap_ratio)
		else:
			unaccounted_list = 0
			clusters         = 0
		clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
		unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
	
	avg_size = N//number_of_clusters
	m = number_of_clusters - len(clusters)
	if Blockdata["myid"] == Blockdata["main_node"]:
		large_clusters = []
		for ic in xrange(len(clusters)):
			if len(clusters[ic]) > 2*avg_size:
				large_clusters.append(clusters[ic])
	else: large_clusters = 0
	large_clusters = wrap_mpi_bcast(large_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
	L = len(large_clusters)
	
	if m == 0 and L == 0:
		if Blockdata["myid"] == Blockdata["main_node"]:
			msg = "m %d  L %d"%(m, L)
			log_file.add(msg)
			msg ="assign_unaccounted_elements_mpi"
			log_file.add(msg)
		out_clusters = assign_unaccounted_elements_mpi(unaccounted_list, clusters, avg_size)
	else:
		if m !=0: empty_clusters =[[] for ie in xrange(m)]
		else: empty_clusters = []
		msg ="fill_no_large_groups_and_unaccounted_to_m_and_rcluster_mpi"
		if Blockdata["myid"] == Blockdata["main_node"]:
			log_file.add(msg)
		out_clusters = fill_no_large_groups_and_unaccounted_to_m_and_rcluster_mpi(\
				 unaccounted_list, empty_clusters, clusters, NUACC, NACC)
	for i in xrange(len(out_clusters)): out_clusters[i].sort()
	return out_clusters

def select_fixed_size_cluster_from_alist(ulist, img_per_grp):
	cluster = []
	shuffle(ulist)
	cluster += ulist[0:img_per_grp]
	del ulist[0:img_per_grp]
	return cluster, ulist

def shake_clusters_small_NUACC(glist, clusters, shake_ratio):
	slist = [None for i in xrange(len(clusters))]
	temp_list = []
	for ic in xrange(len(clusters)):
		slist[ic] = int(shake_ratio*len(clusters[ic]))
		#print("ZZZZ   %d"%slist[ic])
		shuffle(clusters[ic])
		temp_list +=clusters[ic][0:slist[ic]]
		del clusters[ic][0:slist[ic]]
	temp_list +=glist
	for ic in xrange(len(clusters)):
		shuffle(temp_list)
		clusters[ic] +=temp_list[0:slist[ic]]
		del temp_list[0:slist[ic]]
	return temp_list, clusters
		
def shake_clusters_large_NUACC(glist, clusters, shake_ratio):
	import copy
	slist = [None for i in xrange(len(clusters))]
	temp_list = []
	ulist = copy.deepcopy(glist)
	for ic in xrange(len(clusters)):
		#print("cluster ID %d  size %d"%(ic, len(clusters[ic])))
		slist[ic] = int(shake_ratio*len(clusters[ic]))
		shuffle(clusters[ic])
		temp_list +=clusters[ic][0:slist[ic]]
		del clusters[ic][0:slist[ic]]
	for ic in xrange(len(clusters)):
		shuffle(ulist)
		clusters[ic] +=ulist[0:slist[ic]]
		del ulist[0:slist[ic]]
	ulist +=temp_list
	shuffle(ulist)
	return ulist, clusters

def even_assignment_alist_to_mclusters(glist, number_of_groups):
	# evenly assign glist to clusters
	import copy
	if number_of_groups >0:
		clusters = [[] for i in xrange(number_of_groups)]
		ulist = copy.deepcopy(glist)
		nc = 0
		while len(ulist)>0:
			im =  nc%number_of_groups
			shuffle(ulist)
			clusters[im].append(ulist[0])
			del ulist[0]
			nc +=1
		return clusters
	else: return []
	
def fill_large_groups_and_unaccounted_to_m_and_rclusters(\
        large_groups, unaccounted_list, empty_clusters, other_clusters, NUACC, NACC):
	clusters = []
	L = len(large_groups)
	m = len(empty_clusters)
	r = len(other_clusters)
	N =  NUACC + NACC
	number_of_groups = L + m + r
	avg_size   =  N//number_of_groups
	mlist      = [0 for i in xrange(L)]
	NACC_large = 0
	for ic in xrange(L): NACC_large += len(large_groups[ic])
	if m > 0:
		if len(unaccounted_list)//avg_size -1 > 0:
			J = len(unaccounted_list)//avg_size -1
			#print(" J %d K %d"%(J, number_of_groups))
			for ij in xrange(J):
				ucluster, unaccounted_list= select_fixed_size_cluster_from_alist(unaccounted_list, avg_size)
				clusters.append(ucluster)
			for il in xrange(L): mlist[il] = int(len(large_groups[il])/float(NACC_large)*(m-J))+1
			nacc_large_clusters = []
			for il in xrange(L):
				mclusters = even_assignment_alist_to_mclusters(large_groups[il], mlist[il])
				if len(mclusters)>0:
					for mcluster in mclusters: nacc_large_clusters.append(mcluster)
				del mclusters
			for il in xrange(len(nacc_large_clusters)):
				if len(nacc_large_clusters[il])< avg_size:
					other_clusters.append(nacc_large_clusters[il])
				else:
					shuffle(nacc_large_clusters[il])
					clusters.append(nacc_large_clusters[il][0:avg_size])
					for ir in xrange(len(nacc_large_clusters[il][avg_size:])):
						ucluster.append(nacc_large_clusters[il][ir])
			other_clusters = assign_unaccounted_inverse_proportion_to_size(ucluster, other_clusters, avg_size)
			for cluster in other_clusters: clusters.append(cluster)
		else:
			nacc_large_clusters = []
			ucluster            = []
			for il in xrange(L):
				mlist[il] = int(len(large_groups[il])/float(NACC_large)*m + 0.5)+1
			for il in xrange(L):
				mclusters = even_assignment_alist_to_mclusters(large_groups[il], mlist[il])
				if len(mclusters) > 0:
					for mcluster in mclusters: nacc_large_clusters.append(mcluster)
				del mclusters
			for il in xrange(len(nacc_large_clusters)):
				if len(nacc_large_clusters[il])< avg_size:
					other_clusters.append(nacc_large_clusters[il])
				else:
					shuffle(nacc_large_clusters[il])
					clusters.append(nacc_large_clusters[il][0:avg_size])
					for ir in xrange(len(nacc_large_clusters[il][avg_size:])):
						ucluster.append(nacc_large_clusters[il][ir])
			#print("UCLUSTER", len(ucluster), len(unaccounted_list), len(other_clusters))
			ucluster += unaccounted_list
			other_clusters = assign_unaccounted_inverse_proportion_to_size(ucluster, other_clusters, avg_size)
			for cluster in other_clusters: clusters.append(cluster)
	else:
		for il in xrange(L):
			cluster, ulist = select_fixed_size_cluster_from_alist(ulist, avg_size)
			clusters.append(cluster)
			unaccounted_list +=ulist
		other_clusters = assign_unaccounted_inverse_proportion_to_size(unaccounted_list, other_clusters, avg_size)
		for cluster in other_clusters: clusters.append(cluster)
	return clusters

def fill_large_groups_and_unaccounted_to_m_and_rclusters_mpi(\
        large_groups, unaccounted_list, empty_clusters, other_clusters, NUACC, NACC):
	global Tracker, Blockdata
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]:
		print(line, "refilling: fill_large_groups_and_unaccounted_to_m_and_rclusters_mpi")
	clusters = []
	L = len(large_groups)
	m = len(empty_clusters)
	r = len(other_clusters)
	N =  NUACC + NACC
	number_of_groups = L + m + r
	avg_size   =  N//number_of_groups
	mlist      = [0 for i in xrange(L)]
	NACC_large = 0
	for ic in xrange(L): NACC_large += len(large_groups[ic])
	if m > 0:
		if len(unaccounted_list)//avg_size -1 > 0:
			J = len(unaccounted_list)//avg_size -1
			if Blockdata["myid"] == Blockdata["main_node"]:
				#print(" J %d K %d"%(J, number_of_groups))
				for ij in xrange(J):
					ucluster, unaccounted_list= select_fixed_size_cluster_from_alist(unaccounted_list, avg_size)
					clusters.append(ucluster)
			else: 
				clusters = 0
				unaccounted_list = 0
			clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
			for il in xrange(L): mlist[il] = int(len(large_groups[il])/float(NACC_large)*(m-J))+1
			nacc_large_clusters = []
			if Blockdata["myid"] == Blockdata["main_node"]:
				for il in xrange(L):
					mclusters = even_assignment_alist_to_mclusters(large_groups[il], mlist[il])
					if len(mclusters)>0:
						for mcluster in mclusters: nacc_large_clusters.append(mcluster)
					del mclusters
			else: mclusters = 0
			nacc_large_clusters = wrap_mpi_bcast(nacc_large_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			if Blockdata["myid"] == Blockdata["main_node"]:
				for il in xrange(len(nacc_large_clusters)):
					if len(nacc_large_clusters[il])< avg_size:
						other_clusters.append(nacc_large_clusters[il])
					else:
						shuffle(nacc_large_clusters[il])
						clusters.append(nacc_large_clusters[il][0:avg_size])
						for ir in xrange(len(nacc_large_clusters[il][avg_size:])):
							ucluster.append(nacc_large_clusters[il][ir])
			else: 
				ucluster = 0
				clusters = 0
				other_clusters = 0
			clusters       = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			ucluster       = wrap_mpi_bcast(ucluster, Blockdata["main_node"], MPI_COMM_WORLD)
			other_clusters = wrap_mpi_bcast(other_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			other_clusters = assign_unaccounted_elements_mpi(ucluster, other_clusters, avg_size)
			for cluster in other_clusters: clusters.append(cluster)
		else:
			nacc_large_clusters = []
			ucluster            = []
			for il in xrange(L):
				mlist[il] = int(len(large_groups[il])/float(NACC_large)*m + 0.5)+1
			if Blockdata["myid"] == Blockdata["main_node"]:
				for il in xrange(L):
					mclusters = even_assignment_alist_to_mclusters(large_groups[il], mlist[il])
					if len(mclusters) > 0:
						for mcluster in mclusters: nacc_large_clusters.append(mcluster)
					del mclusters
			else: nacc_large_clusters = 0
			nacc_large_clusters = wrap_mpi_bcast(nacc_large_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			if Blockdata["myid"] == Blockdata["main_node"]:
				for il in xrange(len(nacc_large_clusters)):
					if len(nacc_large_clusters[il])< avg_size:
						other_clusters.append(nacc_large_clusters[il])
					else:
						shuffle(nacc_large_clusters[il])
						clusters.append(nacc_large_clusters[il][0:avg_size])
						for ir in xrange(len(nacc_large_clusters[il][avg_size:])):
							ucluster.append(nacc_large_clusters[il][ir])
				#print("UCLUSTER", len(ucluster), len(unaccounted_list), len(other_clusters))
				ucluster += unaccounted_list
			else:
				ucluster       = 0
				other_clusters = 0
				clusters       = 0
			other_clusters = wrap_mpi_bcast(other_clusters, Blockdata["main_node"], MPI_COMM_WORLD)	
			ucluster = wrap_mpi_bcast(ucluster, Blockdata["main_node"], MPI_COMM_WORLD)
			clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)	
			other_clusters = assign_unaccounted_elements_mpi(ucluster, other_clusters, avg_size)
			for cluster in other_clusters: clusters.append(cluster)
	else:
		if Blockdata["myid"] == Blockdata["main_node"]:
			for il in xrange(L):
				cluster, ulist = select_fixed_size_cluster_from_alist(large_groups, avg_size)
				clusters.append(cluster)
				unaccounted_list +=ulist
		else:
			unaccounted_list = 0
			clusters   = 0
		unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
		clusters = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
		other_clusters = assign_unaccounted_elements_mpi(unaccounted_list, other_clusters, avg_size)
		for cluster in other_clusters: clusters.append(cluster)
	return clusters

def fill_no_large_groups_and_unaccounted_to_m_and_rcluster_mpi(\
		unaccounted_list, empty_clusters, clusters, NUACC, NACC):
	global Tracker, Blockdata
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]:
		print(line, "refilling: fill_no_large_groups_and_unaccounted_to_m_and_rcluster_mpi")
		
	N = NUACC + NACC
	m = len(empty_clusters)
	number_of_groups = m + len(clusters)
	avg_size = N//number_of_groups
	if m*avg_size < NUACC - avg_size:
		if Blockdata["myid"] == Blockdata["main_node"]:
			for ic in xrange(len(clusters)):
				shuffle(clusters[ic])
				if len(clusters[ic])> avg_size:
					unaccounted_list +=clusters[ic][avg_size:]
					del clusters[ic][avg_size:]
			shuffle(unaccounted_list)
			print(line, "fill_no_large_groups_and_unaccounted_to_m_and_rcluster")
			print(line, "NUACC %d NACC %d  m %d  avg_size %d  K %d"%(NUACC, NACC, m, avg_size, number_of_groups))
		else: unaccounted_list = 0
		unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
		clusters     = wrap_mpi_bcast(clusters, Blockdata["main_node"], MPI_COMM_WORLD)
		tmp_clusters = []
		if m > 0:
			if Blockdata["myid"] == Blockdata["main_node"]:
				print(line, "refill groups from unaccounted elements")
				for im in xrange(m):
					cluster, unaccounted_list = select_fixed_size_cluster_from_alist(unaccounted_list, avg_size//2)
					tmp_clusters.append(cluster)
			else: tmp_clusters = 0
			tmp_clusters     = wrap_mpi_bcast(tmp_clusters, Blockdata["main_node"], MPI_COMM_WORLD)
			unaccounted_list = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)	 
		if len(tmp_clusters)>0:
			for cluster in tmp_clusters: clusters.append(cluster)
		clusters = assign_unaccounted_elements_mpi(unaccounted_list, clusters, avg_size)
		del unaccounted_list
	else:
		for a in empty_clusters: clusters.append(a)
		clusters = assign_unaccounted_elements_mpi(unaccounted_list, clusters, avg_size)
		del unaccounted_list
	return clusters

def assign_unaccounted_inverse_proportion_to_size(glist, clusters, img_per_grp):
	# assign unaccounted particles by group probabilities, single processor version
	import random
	import copy
	ulist = copy.deepcopy(glist)
	number_of_groups = len(clusters)
	slist = []
	#print("unaccounted  %d  K %d  avg_size %d"%(len(glist), len(clusters), img_per_grp)) 
	for ic in xrange(len(clusters)):
		if len(clusters[ic])<=img_per_grp:
			slist.append(max(1.- float(len(clusters[ic]))/float(img_per_grp), 0.05))
		else: slist.append(0.05)
	nc = 0
	#print(slist)
	while len(ulist)>0:
		im = random.randint(0, number_of_groups - 1)
		shuffle(ulist)
		r = random.uniform(0.0, 1.0)
		if r<slist[im]:
			clusters[im].append(ulist[0])
			if len(clusters[im])<=img_per_grp:
				slist[im] = max(1.- float(len(clusters[im])/float(img_per_grp)), 0.05)
			else: slist[im] = 0.05
			del ulist[0]
			if len(ulist)==0: break
		else: continue
	print(slist)	
	del ulist
	return clusters

def swap_accounted_with_unaccounted_elements_mpi(accounted_file, unaccounted_file, log_file, number_of_groups, swap_ratio):
	global Tracker, Blockdata
	import random
	import copy
	checking_flag = 0
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		p1 = read_text_row(accounted_file)
		if len(p1) <= 1: checking_flag = 1
	checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
	
	if checking_flag == 0:
		tot = 0
		if Blockdata["myid"] == Blockdata["main_node"]:
			p1 = read_text_row(accounted_file)
			clusters, npart  = split_partition_into_ordered_clusters(p1)
			unaccounted_list = read_text_file(unaccounted_file)
			total_stack = len(unaccounted_list)
			for any in clusters: total_stack +=len(any)
		else: 
			clusters = 0
			unaccounted_list = 0
			total_stack      = 0	
		clusters          = wrap_mpi_bcast(clusters, Blockdata["main_node"],         MPI_COMM_WORLD)
		total_stack       = bcast_number_to_all(total_stack, Blockdata["main_node"], MPI_COMM_WORLD)
		unaccounted_list  = wrap_mpi_bcast(unaccounted_list, Blockdata["main_node"], MPI_COMM_WORLD)
		clusters = refilling_global_scheme_mpi(clusters, unaccounted_list, number_of_groups, log_file, swap_ratio)
	
		if Blockdata["myid"] == Blockdata["main_node"]:
			dlist, assignment_list    = merge_classes_into_partition_list(clusters)
			converted_assignment_list = [[],[]]
			for im in xrange(len(assignment_list)):
				for jm in xrange(2): 
					converted_assignment_list[jm].append(assignment_list[im][jm])
		else: converted_assignment_list = 0
		converted_assignment_list = wrap_mpi_bcast(converted_assignment_list, Blockdata["main_node"], MPI_COMM_WORLD)
	else: 
		assignment_list = create_nrandom_lists(unaccounted_file, number_of_groups, 1)
		assignment_list = assignment_list[0]
		converted_assignment_list = [[],[]]
		for jm in xrange(2):
			for im in xrange(len(assignment_list)):
				converted_assignment_list[jm].append(assignment_list[im][jm])
	return converted_assignment_list
		
def patch_to_do_k_means_match_clusters_asg_new(ptp1, ptp2):
	from statistics import k_means_match_clusters_asg_new
	# patch ad hoc elements to make equal number of classes for two partitions and thus two_way comparison becomes feasible
	patch_elements = []
	if len(ptp1) != len(ptp2):
		for i in xrange(len(ptp1)): ptp1[i] = array(ptp1[i],"int32")
		for i in xrange(len(ptp2)):	ptp2[i] = array(ptp2[i],"int32")
		alist = []
		blist = []
		for a in ptp1:
			if len(a)>0: alist.append(max(a))
		for b in ptp2: 
			if len(b)>0: blist.append(max(b))
		if len(alist)>0 and len(blist)>0:
			max_number = max(max(alist), max(blist))
		else:  exit() # This would never happen
		if len(ptp1) > len(ptp2):
			ndiff = len(ptp1) - len(ptp2)
			for indiff in xrange(ndiff):
				l = []
				l.append(max_number+indiff+1)
				patch_elements.append(max_number+indiff+1)
				l = array(l,"int32")
				ptp2.append(l)
		else:
			ndiff = len(ptp2)-len(ptp1)
			for indiff in xrange(ndiff):
				l = []
				l.append(max_number+indiff+1)
				patch_elements.append(max_number + indiff + 1)
				l = array(l,"int32")
				ptp1.append(l)
	else:
		for i in xrange(len(ptp1)):
			ptp1[i] = array(ptp1[i],"int32")
			ptp2[i] = array(ptp2[i],"int32")
	newindeces, list_stable, nb_tot_objs = k_means_match_clusters_asg_new(ptp1, ptp2)
	new_list_stable = []
	for a in list_stable:
		a.tolist()
		if len(a)>0: new_list_stable.append(a) # remove empty ones
	return newindeces, new_list_stable, nb_tot_objs, patch_elements
	
def do_boxes_two_way_comparison_new(nbox, input_box_parti1, input_box_parti2, depth, log_main):
	global Tracker, Blockdata
	import json
	line  = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	msg_pipe  = '----------------------------------------------------------------------------' 
	msg       = ' >>>>>>> do_boxes_two_way_comparison_new  between nbox %d and nbox %d<<<<<< '%(nbox, nbox+1)
	msg_pipe1 = '+++++++++++++                                                    ++++++++++++' 
	stop_generation  = 0
	print(line, msg_pipe)
	print(line, msg)
	print(line, msg_pipe1)
	log_main.add(msg_pipe)
	log_main.add(msg)
	log_main.add(msg_pipe1)
	msg = '========================= between box two way comparison gen: %d layer: %d nbox:  %d nbox: %d ==========================='%(Tracker["current_generation"], \
	      Tracker["depth"], nbox, nbox+1)
	print(line, msg)
	log_main.add(msg)
	msg = 'two box runs to be compared are entirely independent'
	print(line, msg)
	log_main.add(msg)
	msg = '**************** Simulation of random reproducibility estimation ******************* '
	log_main.add(msg)
	## used by single node only
	bad_clustering =  0
	ipair = 0
	core1 = read_text_row(input_box_parti1)
	ptp1, tmp1 = split_partition_into_ordered_clusters(core1)
	core2 = read_text_row(input_box_parti2)
	ptp2, tmp2 = split_partition_into_ordered_clusters(core2)
	#### before comparison we do a simulation
	NT = 200
	import numpy as np
	alist   = []
	blist   = []
	plist1  = []
	plist2  = []
	
	for i1 in xrange(len(ptp1)):
		#plist1.append([nsize, nsize + len(ptp1[i1])])
		#nsize += len(ptp1[i1])
		alist += ptp1[i1]
	
	for i1 in xrange(len(ptp2)):
		#plist2.append([nsize, nsize + len(ptp2[i1])])
		#nsize += len(ptp2[i1])
		blist += ptp2[i1]
	max_num = max(alist+blist)+1
	alist = np.array(alist, "int32")
	blist = np.array(blist, "int32")
	
	k = min(len(ptp1), len(ptp2))
	if len(ptp1)>k:
		for i1 in xrange(len(ptp1)-k): 
			ptp1.append([max_num+i1])
	elif len(ptp2)>k:
		for i1 in xrange(len(ptp2)-k): 
			ptp2.append([max_num+i1])
	nsize = 0
	for i1 in xrange(len(ptp1)):
		plist1.append([nsize, nsize + len(ptp1[i1])])
		nsize += len(ptp1[i1])
	nsize = 0
	for i1 in xrange(len(ptp2)):
		plist2.append([nsize, nsize + len(ptp2[i1])])
		nsize += len(ptp2[i1])
	
	tlist = []
	clist = [[] for i in xrange(k)]
	for iter_simu in xrange(NT):
		new_clusters1 = []
		new_clusters2 = []
		np.random.shuffle(alist)
		np.random.shuffle(blist)	
		for j in xrange(k):new_clusters1.append(alist[plist1[j][0]:plist1[j][1]])
		for j in xrange(k):new_clusters2.append(blist[plist2[j][0]:plist2[j][1]])
		for j in xrange(k): new_clusters1[j] = np.sort(new_clusters1[j])
		for j in xrange(k): new_clusters2[j] = np.sort(new_clusters2[j])
		newindeces, list_stable, nb_tot_objs = k_means_match_clusters_asg_new(new_clusters1,new_clusters2)
		tlist.append(nb_tot_objs/float((np.union1d(alist, blist)).size)*100.)	
		for j in xrange(len(newindeces)):
			if list_stable[j].size > 0:
				clist[j].append(float((np.intersect1d(new_clusters1[newindeces[j][0]], new_clusters2[newindeces[j][1]])).size)\
				  /float((np.union1d(new_clusters1[newindeces[j][0]], new_clusters2[newindeces[j][1]])).size)*100.)
	t = table_stat(tlist)
	msg = 'random reproducibility of total: %5.3f'%(round(t[0], 4))
	log_main.add(msg)
	for l in xrange(len(clist)):
		if len(clist[l])>0:
			msg = 'random reproducibility per group:  %5.3f   %8d '%(round(table_stat(clist[l])[0], 4), (plist1[l][1]-plist1[l][0]))
			log_main.add(msg)
	msg = '***********************************************************************************'
	log_main.add(msg)
	## before comparison
	msg = 'P0 '
	msg1 ='GID'
	length = max(len(ptp1), len(ptp2))
	for im in xrange(length):
		try:    msg +='{:8d} '.format(len(ptp1[im]))
		except: pass
		msg1 +='{:8d} '.format(im)
	print(line, msg1)
	log_main.add(msg1)
	print(line, msg)
	log_main.add(msg)
	msg = 'P1 '
	for im in xrange(len(ptp2)): msg +='{:8d} '.format(len(ptp2[im]))
	print(line, msg)
	log_main.add(msg)
	
	try: assert(len(core1) ==len(core2))
	except: ERROR("two partitions have non-equal length", "do_boxes_two_way_comparison", 1, 0)
	full_list  = []
	for a in core1: full_list.append(a[1])
	full_list.sort()
	total_data = len(full_list)
	minimum_group_size = total_data
	maximum_group_size = 0
	
	newindeces, list_stable, nb_tot_objs, patch_elements = patch_to_do_k_means_match_clusters_asg_new(ptp1, ptp2)
	ratio_unaccounted  = 100. - nb_tot_objs/float(total_data)*100.
	ratio_accounted    = nb_tot_objs/float(total_data)*100.
	new_list           = []
	print_matching_pairs(newindeces, log_main)
	
	###
	"""
	if Tracker["current_generation"] == 0:
		faked_list = sorted(list_stable, key=len, reverse=True)
		minimum_grp_size_cut = len(faked_list[0])- 2 # reset
	else:
		minimum_grp_size_cut = Tracker["constants"]["minimum_grp_size"]
	"""
	
	tmsg ="betweenboxes_comparison: box%d   box%d generation%d layer%d percentage accounted:  %f "%(nbox, nbox+1, Tracker["current_generation"], Tracker["depth"], round(ratio_accounted,3))
	Tracker["current_iter_ratio"] = ratio_accounted
	score_list = [ ]
	nclass = 0
	###
	if depth >1:
		msg = 'Cluster intersections of P0 and P1 form new clusters and are checked by user provided minimum_grp_size %d. '%Tracker["constants"]["minimum_grp_size"]
	else:
		msg = 'Cluster intersections of P0 and P1 form new clusters and are checked by user provided minimum_grp_size %d. Rejected clusters are dismissed'%Tracker["constants"]["minimum_grp_size"]
	print(line, msg)
	log_main.add(msg)
	###
	
	msg = '{:^10} {:^5} {:^5} {:^10} {:^10} {:^15} {:^15}'.format('New GID', 'P0 ID',  'P1 ID', 'GSIZE', 'status', 'R ratio of P0', 'R ratio of P1')
	print(line, msg)
	log_main.add(msg)
	
	for index_of_any in xrange(len(list_stable)):
		any = list_stable[index_of_any]
		any.tolist()
		any.sort()
		score1 = float(len(any))*100./float(len(ptp1[newindeces[index_of_any][0]]))
		score2 = float(len(any))*100./float(len(ptp2[newindeces[index_of_any][1]]))
		
		if len(any) >= Tracker["constants"]["minimum_grp_size"]:
			score_list.append([score1, score2])
			minimum_group_size = min(minimum_group_size, len(any))
			maximum_group_size = max(maximum_group_size, len(any))
			new_list.append(any)
			nclass +=1
			#msg ="   %3d     %8d    %6.3f    %6.3f"%(nclass, len(any), score1, score2)
			msg ='{:^10d} {:^5d} {:^5d} {:^10d}  {:^10} {:^15.3f} {:^15.3f}'.format(index_of_any, int(newindeces[index_of_any][0]), int(newindeces[index_of_any][1]), len(any),'accepted', round(score1,3), round(score2,3))
			log_main.add(msg)
		else:
			#msg ="group %d with size %d is rejected and sent back into unaccounted ones"%(index_of_any, len(any))
			msg ='{:^10d} {:^5d} {:^5d} {:^10d}  {:^10} {:^15.3f} {:^15.3f}'.format(index_of_any, int(newindeces[index_of_any][0]), int(newindeces[index_of_any][1]), len(any), 'rejected', round(score1,3), round(score2,3))
			log_main.add(msg)
	
	if nclass == 0:
		print(line, tmsg)
		log_main.add(tmsg)
		### redo two way comparison
		if depth >1:
			msg = "No cluster is larger than user provided minimum_grp_size %d. However sorting keeps the old results, eliminates the samllest one, and continues"%Tracker["constants"]["minimum_grp_size"]
			log_main.add(msg)
			print(msg)
			ptp1, ucluster1 = split_partition_into_ordered_clusters_split_ucluster(core1)
			ptp2, ucluster2 = split_partition_into_ordered_clusters_split_ucluster(core2)
			newindeces, list_stable, nb_tot_objs, patch_elements = patch_to_do_k_means_match_clusters_asg_new(ptp1, ptp2)
			if len(list_stable)>3:# No change for two groups
				fake_list = sorted(list_stable, key=len)
				list_stable.remove(fake_list[0])
			list_stable = sorted(list_stable, key=len, reverse=True)
			accounted_list, new_index = merge_classes_into_partition_list(list_stable)
			a = set(full_list)
			b = set(accounted_list)
			unaccounted_list = sorted(list(a.difference(b)))
			msg = '========================================================================================================================= \n'
			print(line, msg)
			log_main.add(msg)
			return minimum_group_size, maximum_group_size, new_index, unaccounted_list, bad_clustering, stop_generation
		else:
			bad_clustering = 1
			msg = "No cluster is larger than user provided minimum_grp_size %d. This could be due to 1. Your data might be quite uniform; 2. Your minimum_grp_size is too large; 3. K is too large;"\
			                   %Tracker["constants"]["minimum_grp_size"]
			log_main.add(msg)
			print(line, msg)
			msg = '========================================================================================================================= \n'
			print(line, msg)
			log_main.add(msg)
			return minimum_group_size, maximum_group_size, [ ], full_list, bad_clustering, stop_generation
	elif nclass == 1: # Force to stop this generation, and output the cluster; do not do any other box comparison
		stop_generation  = 1
		accounted_list, new_index = merge_classes_into_partition_list(new_list)
		a = set(full_list)
		b = set(accounted_list)
		unaccounted_list = sorted(list(a.difference(b)))
		msg ='Only one cluster is found. Output it and stop this generation.'
		print(line, msg)
		log_main.add(msg)
		box1_dir =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"], "layer%d"%Tracker["depth"], "nbox%d"%nbox)
		box2_dir =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"], "layer%d"%Tracker["depth"], "nbox%d"%(nbox+1))
		gendir   =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"])
		fout = open(os.path.join(box1_dir,"freq_cutoff.json"),'r')
		freq_cutoff_dict1 = convert_json_fromunicode(json.load(fout))
		fout.close()
		fout = open(os.path.join(box2_dir,"freq_cutoff.json"),'r')
		freq_cutoff_dict2 = convert_json_fromunicode(json.load(fout))
		fout.close()
		try:
			fout = open(os.path.join(gendir,"freq_cutoff.json"),'r')
			freq_cutoff_dict3 = convert_json_fromunicode(json.load(fout))
			fout.close()
			freq_cutoff_dict3 = {}
		except: freq_cutoff_dict3 = {}
		ncluster = 0
		for im in xrange(len(newindeces)):
			try:
				f1 = freq_cutoff_dict1["Cluster_%03d.txt"%newindeces[im][0]] 
				f2 = freq_cutoff_dict2["Cluster_%03d.txt"%newindeces[im][1]]
				freq_cutoff_dict3["Cluster_%03d.txt"%ncluster] = min(f1, f2)
				ncluster +=1
			except: pass
		fout = open(os.path.join(gendir,"freq_cutoff.json"),'w')
		json.dump(freq_cutoff_dict3, fout)
		fout.close()
		msg = '========================================================================================================================= \n'
		print(line, msg)
		log_main.add(msg)
		return minimum_group_size, maximum_group_size, new_index, unaccounted_list, bad_clustering, stop_generation
	else:
		if len(new_list) >= len(list_stable)-1: # all passes size checking, even the outliers group
			accounted_list, new_index = merge_classes_into_partition_list(new_list)
			a = set(full_list)
			b = set(accounted_list)
			unaccounted_list = sorted(list(a.difference(b)))
			msg ='all non-unaccounted groups pass the size checking'
		else:#drop off the smallest one, and decrease K by one
			if len(list_stable) >3:
				fake_list = sorted(list_stable, key=len)
				list_stable.remove(fake_list[0])
			list_stable = sorted(list_stable, key=len, reverse=True)
			accounted_list, new_index = merge_classes_into_partition_list(list_stable)
			a = set(full_list)
			b = set(accounted_list)
			unaccounted_list = sorted(list(a.difference(b)))
			msg ='Not all non-unaccounted groups pass the size checking'
		print(line, msg)
		log_main.add(msg)
		mmsg =" minimum group size: %d maximum group size: %d NACC: %d NUACC: %d "%(minimum_group_size, maximum_group_size, len(accounted_list), len(unaccounted_list))
		tmsg +=mmsg
		print(line, tmsg)
		log_main.add(tmsg)
		
		if depth <= 1: # the last layer
			box1_dir =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"], "layer%d"%Tracker["depth"], "nbox%d"%nbox)
			box2_dir =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"], "layer%d"%Tracker["depth"], "nbox%d"%(nbox+1))
			gendir   =  os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%Tracker["current_generation"])
			fout = open(os.path.join(box1_dir,"freq_cutoff.json"),'r')
			freq_cutoff_dict1 = convert_json_fromunicode(json.load(fout))
			fout.close()
			fout = open(os.path.join(box2_dir,"freq_cutoff.json"),'r')
			freq_cutoff_dict2 = convert_json_fromunicode(json.load(fout))
			fout.close()
			try:
				fout = open(os.path.join(gendir,"freq_cutoff.json"),'r')
				freq_cutoff_dict3 = convert_json_fromunicode(json.load(fout))
				fout.close()
				freq_cutoff_dict3 = {}
			except: freq_cutoff_dict3 = {}
			ncluster = 0
			for im in xrange(len(newindeces)):
				try:
					f1 = freq_cutoff_dict1["Cluster_%03d.txt"%newindeces[im][0]] 
					f2 = freq_cutoff_dict2["Cluster_%03d.txt"%newindeces[im][1]]
					freq_cutoff_dict3["Cluster_%03d.txt"%ncluster] = min(f1, f2)
					ncluster +=1
				except: pass
			fout = open(os.path.join(gendir,"freq_cutoff.json"),'w')
			json.dump(freq_cutoff_dict3, fout)
			fout.close()
			msg = '========================================================================================================================= \n'
			print(line, msg)
			log_main.add(msg)
		else:
			msg = '========================================================================================================================= \n'
			print(line, msg)
			log_main.add(msg)
		return minimum_group_size, maximum_group_size, new_index, unaccounted_list, bad_clustering, stop_generation
		
def split_partition_into_ordered_clusters_split_ucluster(partition):
	# split groupids from indexes of particles
	# reindex groups
	ucluster   = []
	clusters   = []
	cluster_id = []
	for im in xrange(len(partition)):
		if  partition[im][0] not in cluster_id:cluster_id.append(partition[im][0])
	####
	cluster_dict      = {}
	group_change_dict = {}
	new_group_id      = 0
	if len(cluster_id)>1: cluster_id.sort()
	for icluster in xrange(len(cluster_id)):
		one_cluster = []
		for a in partition:
			if a[0]== icluster: 
				one_cluster.append(a[1])
				cluster_dict[a[1]] = icluster
		one_cluster.sort()
		if icluster<len(cluster_id)-1: clusters.append(one_cluster)
		else:  ucluster.append(one_cluster)
		group_change_dict[icluster] = new_group_id
		new_group_id +=1
	# create a partition list:
	return clusters, ucluster[0]

def do_withinbox_two_way_comparison(partition_dir, nbox, nrun, niter, log_main):
	global Tracker, Blockdata
	import numpy as np
	## for single node only
	line  = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	msg_pipe  ='--------------------------------------------------'
	msg       =' >>>>>>> do_withinbox_two_way_comparison <<<<<<<< '
	msg_pipe1 ='-----++++++                          +++++--------'
	print(line, msg_pipe)
	print(line, msg)
	print(line, msg_pipe1 )
	log_main.add(msg_pipe)
	log_main.add(msg)
	log_main.add(msg_pipe1)
	msg = '==========   withinboxrun ID  gen: %d layer: %d nbox: %d nrun: %d niter: %d ========================'%(Tracker["current_generation"], \
	      Tracker["depth"], nbox, nrun, niter)
	print(line, msg)
	log_main.add(msg)
	msg = 'two runs to be compared inside the box are only independent in the first iteration'
	print(line, msg)
	log_main.add(msg)
	smsg =' withinboxrun ID: generation %d layer %d nbox %d nrun %d niter %d freq_cutoff %f '%(Tracker["current_generation"], \
	      Tracker["depth"], nbox, nrun, niter, round(Tracker["freq_fsc143_cutoff"], 4))
	      
	ipair = 0
	line  = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	core1 = read_text_row(os.path.join(partition_dir, "partition_%03d.txt"%(2*ipair)))
	ptp1, tmp1 = split_partition_into_ordered_clusters( core1)
	core2 = read_text_row(os.path.join(partition_dir, "partition_%03d.txt"%(2*ipair+1)))
	ptp2, tmp2 = split_partition_into_ordered_clusters( core2)
	
	## before comparison
	msg = 'P0 '
	msg1 ='GID'
	for im in xrange(len(ptp1)):
		msg +='{:8d} '.format(len(ptp1[im]))
		msg1 +='{:8d} '.format(im)
	print(line, msg1)
	log_main.add(msg1)
	print(line, msg)
	log_main.add(msg)
	msg = 'P1 '
	for im in xrange(len(ptp2)): msg +='{:8d} '.format(len(ptp2[im]))
	print(line, msg)
	log_main.add(msg)
    ####
	try: assert(len(core1) ==len(core2))
	except: ERROR("two partitions have non-equal length", "do_withinbox_two_way_comparison", 1, 0)
	full_list  = []
	for a in core1: full_list.append(a[1])
	full_list.sort()
	total_data = len(full_list)
	minimum_group_size = total_data
	maximum_group_size = 0
	
	newindeces, list_stable, nb_tot_objs, patch_elements = patch_to_do_k_means_match_clusters_asg_new(ptp1, ptp2)
	ratio_unaccounted  = 100.-nb_tot_objs/float(total_data)*100.
	ratio_accounted    = nb_tot_objs/float(total_data)*100.
	print_matching_pairs(newindeces, log_main)
	
	smsg += '{} {}{} {} {}{} {} {}'.format(' accounted ratio between', 'P', 2*ipair, 'and', 'P', 2*ipair+1, 'is', round(ratio_accounted,2))
	Tracker["current_iter_ratio"] = ratio_accounted
	score_list = [ ]
	nclass     = 0
	msg = 'Cluster intersections of P0 and P1 form new clusters and are checked by MGR group size. Rejected ones will be reassigned from the unaccounted elements'
	print(line, msg)
	log_main.add(msg)
	msg = '{:^10} {:^5} {:^5} {:^10} {:^10} {:^10} {:^15} {:^15} {:^15}'.format('New GID', 'P0 ID',  'P1 ID', 'GSIZE', 'MGRSIZE', 'status', 'R ratio of P0', 'R ratio of P1', 'reproducibility')
	print(line, msg)
	log_main.add(msg)
	
	current_MGR = get_MGR_from_two_way_comparison(newindeces, ptp1, ptp2, total_data)
	stable_clusters   = []
	selected_clusters = []
	
	for index_of_any in xrange(len(list_stable)):
		any = list_stable[index_of_any]
		any.tolist()
		any.sort()
		score1 = float(len(any))*100./float(len(ptp1[newindeces[index_of_any][0]]))
		score2 = float(len(any))*100./float(len(ptp2[newindeces[index_of_any][1]]))
		score3 = float((np.intersect1d(ptp1[newindeces[index_of_any][0]], ptp2[newindeces[index_of_any][1]])).size)\
			  /float((np.union1d(ptp1[newindeces[index_of_any][0]], ptp2[newindeces[index_of_any][1]])).size)*100.
		if len(any) > current_MGR[index_of_any]:
			score_list.append([score1, score2])
			minimum_group_size = min(minimum_group_size, len(any))
			maximum_group_size = max(maximum_group_size, len(any))
			nclass +=1
			msg ='{:^10d} {:^5d} {:^5d} {:^10d} {:^10d} {:^10} {:^15.3f} {:^15.3f} {:^15.3f}'.format(index_of_any, int(newindeces[index_of_any][0]), \
			     int(newindeces[index_of_any][1]), len(any), current_MGR[index_of_any],'accepted', round(score1,3), round(score2,3), round(score3,3))
			log_main.add(msg)
			selected_clusters.append(any)
			print(msg)
		else:
			msg ='{:^10d} {:^5d} {:^5d} {:^10d} {:^10d} {:^10} {:^15.3f} {:^15.3f} {:^15.3f}'.format(index_of_any, int(newindeces[index_of_any][0]), \
			     int(newindeces[index_of_any][1]), len(any), current_MGR[index_of_any], 'rejected', round(score1,3), round(score2,3), round(score3,3))
			log_main.add(msg)
			print(msg)
			
	accounted_list, new_index = merge_classes_into_partition_list(selected_clusters)
	a = set(full_list)
	b = set(accounted_list)
	unaccounted_list = sorted(list(a.difference(b)))
	write_text_row(new_index, os.path.join(partition_dir, "Accounted.txt"))
	write_text_file(unaccounted_list, os.path.join(partition_dir, "Unaccounted.txt"))
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	min_size_msg =" current minimum group size: %d maximum group size: %d"%(minimum_group_size, maximum_group_size)
	smsg +=' {} {} {} {}'.format('NACC:', len(accounted_list), 'NUACC:', len(unaccounted_list))
	smsg += min_size_msg
	log_main.add(smsg)
	msg = '========================================================================================================================='
	print(line, msg+'\n')
	log_main.add(msg+'\n')
	return minimum_group_size, maximum_group_size, selected_clusters, unaccounted_list, ratio_accounted, len(list_stable)

#####	
def split_partition_into_clusters(sorting_res):
	# split groupids from indexes of particles
	id_list        = []
	clusters       = []
	ptp            = []
	final_class_id = 0
	for igen in xrange(len(sorting_res)):
		cluster_id =[]
		for im in xrange(len(sorting_res[igen])):
			#id_list.append(sorting_res[igen][im][1])
			if  sorting_res[igen][im][0] not in cluster_id:
				cluster_id.append(sorting_res[igen][im][0])
		for b in cluster_id:
			one_cluster = []
			for a in sorting_res[igen]:
				if a[0]==b:	one_cluster.append(a[1])
			clusters.append(one_cluster)
			final_class_id +=1
	return clusters

def split_partition_into_ordered_clusters(partition):
	# split groupids from indexes of particles
	# reindex groups
	clusters   = []
	cluster_id = []
	for im in xrange(len(partition)):
		if partition[im][0] not in cluster_id:cluster_id.append(partition[im][0])
	####
	cluster_dict      = {}
	group_change_dict = {}
	new_group_id      = 0
	for icluster in xrange(len(cluster_id)):
		one_cluster = []
		for a in partition:
			if a[0]== icluster: 
				one_cluster.append(a[1])
				cluster_dict[a[1]] = icluster
		#if len(one_cluster)>= Tracker["constants"]["minimum_grp_size"]: # clean small ones
		one_cluster.sort()
		clusters.append(one_cluster)
		group_change_dict[icluster] = new_group_id
		new_group_id +=1
		
	# create a partition list:
	new_partition = [] 
	for iptl in xrange(len(partition)):
		gid = group_change_dict[cluster_dict[partition[iptl][1]]]
		if gid >-1: new_partition.append([group_change_dict[cluster_dict[partition[iptl][1]]], partition[iptl][1]])
	return clusters, new_partition
	 
def prep_ptp_single(all_lists, full_list):
	# full_list contains the initial input indexes
	# the assignment is aligned to full_list
	# convert classes into a single list ptp denoted by group id
	ad_hoc_group_ID = len(all_lists)+1
	ad_hoc_particle_exists = False
	a = set([])
	for b in all_lists: a.union(b)
	c = set(full_list)
	if list(a.difference(c)) !=[]: ERROR("Accounted and unaccounted in total do not match the total number of particles", "prep_ptp_single", 1, Blockdata["myid"])
	else:
		pdict = {}
		for iclass in xrange(len(all_lists)):
			for iptl in xrange(len(all_lists[iclass])): pdict[all_lists[iclass][iptl]] = iclass
		assignment = []
		for im in xrange(len(full_list)):
			#pdict[full_list[im]]
			try: group_ID =  pdict[full_list[im]]
			except:
				group_ID = ad_hoc_group_ID
				ad_hoc_particle_exists = True
			assignment.append(group_ID)
		if ad_hoc_particle_exists: ptp = convertasi(assignment, ad_hoc_group_ID)
		else: ptp = convertasi(assignment, len(all_lists)+1)
		del pdict
	return ptp

def merge_classes_into_partition_list(classes_list):
	# keep the order of classes
	group_dict = {}
	data_list  = []
	new_index  = []
	if len(classes_list)>0:
		for index_of_class in xrange(len(classes_list)):
			for index_of_particle in xrange(len(classes_list[index_of_class])):
				data_list.append(classes_list[index_of_class][index_of_particle])
				group_dict[classes_list[index_of_class][index_of_particle]] = index_of_class
		data_list = sorted(data_list)
		for index_of_particle in xrange(len(data_list)):new_index.append([group_dict[data_list[index_of_particle]], data_list[index_of_particle]])
		del group_dict
	else:
		data_list = []
		new_index = [[]]
	return data_list, new_index

def adjust_fsc_to_full_data_set(fsc_to_be_adjusted, n1, n):
	q = float(n1)/float(n)
	fsc_sub = [None for i in xrange(len(fsc_to_be_adjusted))]
	for i in xrange(len(fsc_to_be_adjusted)):
		y = fsc_to_be_adjusted[i]
		fsc_sub[i] = y/(y*(1.-q)+q)
	return fsc_sub
	
def get_sorting_all_params(data):
	global Tracker, Blockdata
	from utilities    import wrap_mpi_bcast
	from applications import MPI_start_end
	if Blockdata["myid"] == Blockdata["main_node"]:	total_attr_value_list = [[]]*Tracker["total_stack"]
	else: total_attr_value_list = 0
	for myproc in xrange(Blockdata["nproc"]):
		attr_value_list = 0
		if Blockdata["myid"] == myproc:	attr_value_list = get_sorting_attr_stack(data)
		attr_value_list = wrap_mpi_bcast(attr_value_list, myproc)
		if Blockdata["myid"] == Blockdata["main_node"]:
			image_start,image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], myproc)
			total_attr_value_list = fill_in_mpi_list(total_attr_value_list, attr_value_list, image_start,image_end)
		mpi_barrier(MPI_COMM_WORLD)
	total_attr_value_list = wrap_mpi_bcast(total_attr_value_list, Blockdata["main_node"])
	return total_attr_value_list
	
def get_sorting_attr_stack(data_in_core):
	# get partitioned group ID and xform.projection parameters
	from utilities import get_params_proj
	attr_value_list = []
	for idat in xrange(len(data_in_core)): attr_value_list.append([data_in_core[idat].get_attr("group"), get_params_proj(data_in_core[idat],xform = "xform.projection")])
	return attr_value_list
	
def fill_in_mpi_list(mpi_list, data_list, index_start, index_end):
	for index in xrange(index_start, index_end): mpi_list[index] = data_list[index - index_start]
	return mpi_list
	
def parsing_sorting_params(partid, sorting_params_list):
	from utilities import read_text_file
	group_list        = []
	ali3d_params_list = []
	partid_list       = read_text_file(partid, -1)
	if len(partid_list)==1:
		for ielement in xrange(len(sorting_params_list)):
			group_list.append([sorting_params_list[ielement][0], partid_list[0][ielement]])
			ali3d_params_list.append(sorting_params_list[ielement][1:])
	elif len(partid_list)==2:
		for ielement in xrange(len(sorting_params_list)):
			group_list.append([sorting_params_list[ielement][0], partid_list[1][ielement]])
			ali3d_params_list.append(sorting_params_list[ielement][1:])
	else: ERROR("wrong columns", "parsing_sorting_params", 1, 0)
	return group_list, ali3d_params_list

def convertasi(asig, number_of_groups):
	from numpy import array
	p = []
	for k in xrange(number_of_groups):
		l = []
		for i in xrange(len(asig)):
			if( asig[i]== k ): l.append(i)
		l = array(l,"int32")
		l.sort()
		p.append(l)
	return p

def extract_groups_from_partitions(partition_list, number_of_groups):
	# Given multiple partitions in partition_list
	ptp=[None]*len(partition_list)
	for ipt in xrange(len(partition_list)):
		assignment  =[-1]*len(partition_list[ipt])
		for index_of_particle in xrange(len(partition_list[ipt])): assignment[index_of_particle] = partition_list[ipt][index_of_particle][0]
		ptp[ipt] = convertasi(assignment, number_of_groups)
	org_id = []
	for a in partition_list[0]:# extract org id from the first partition
		org_id.append(a[1])
	org_id = sorted(org_id)
	return ptp, org_id
		
def update_data_partition(cdata, rdata, partids):
	# update particle clustering partitions of independent EQKmeans run
	global Tracker, Blockdata
	from utilities import wrap_mpi_bcast
	import copy
	if( Blockdata["myid"] == Blockdata["main_node"]):
		lpartids = read_text_file(partids, -1)
		if len(lpartids) == 1:
			lpartids = lpartids[0]
			groupids = len(lpartids)*[-1]
		else:
			groupids = lpartids[0]
			lpartids = lpartids[1]
	else:  	
		lpartids   = 0
		groupids   = 0
	lpartids = wrap_mpi_bcast(lpartids, Blockdata["main_node"])
	groupids = wrap_mpi_bcast(groupids, Blockdata["main_node"])
	
	assignment = copy.copy(groupids)
	try: assert(Tracker["total_stack"] == len(groupids))
	except: ERROR("total stack in Tracker does not agree with the one is just read in", "update_data_partition", 1, Blockdata["myid"])
	image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])	
	nima = image_end - image_start
	assert(nima == len(cdata))
	groupids  = groupids[image_start:image_end]
	for im in xrange(nima):
		cdata[im].set_attr("group",groupids[im])
		rdata[im].set_attr("group",groupids[im])
	return assignment
	
def partition_data_into_orientation_groups_nompi(refa_vecs, data_vecs):
	orien_assignment = [ None for im in xrange(len(data_vecs))]
	for im in xrange(len(data_vecs)):
		max_dist = -999.0
		for jm in xrange(len(refa_vecs)):
			this_dis = get_dist1(data_vecs[im], refa_vecs[jm])
			if this_dis > max_dist:
				max_dist = this_dis
				orien_assignment[im] = jm
	return orien_assignment
	
### dmatrix and refangles partition
def get_dist1(vec1, vec2):
	sum_dot = 0.0
	for icomp in xrange(len(vec1)): sum_dot +=vec1[icomp]*vec2[icomp]
	return sum_dot

def find_neighborhood(refa_vecs, minor_groups):
	matched_oriens  = [ [None, None] for i in xrange(len(minor_groups))]
	for iproj in xrange(len(minor_groups)):
		max_value = -999.0
		for jproj in xrange(len(refa_vecs)):
			if jproj not in minor_groups:
				this_dis = get_dist1(refa_vecs[minor_groups[iproj]], refa_vecs[jproj])
				if this_dis > max_value:
					max_value = this_dis
					matched_oriens[iproj] = [minor_groups[iproj], jproj]
	return matched_oriens
	
def reassign_ptls_in_orien_groups(assigned_ptls_in_groups, matched_pairs):
	tmplist = []
	for iorien in xrange(len(matched_pairs)):
		if matched_pairs[iorien][1] !=None and matched_pairs[iorien][0]!= None:
			assigned_ptls_in_groups[matched_pairs[iorien][1]] +=assigned_ptls_in_groups[matched_pairs[iorien][0]]
			tmplist.append(matched_pairs[iorien][0])
	reassignment = []
	for iorien in xrange(len(assigned_ptls_in_groups)):
		if iorien not in tmplist: reassignment.append(sorted(assigned_ptls_in_groups[iorien]))
	return reassignment

def findall_dict(value, L, start=0):
	"""
	 return a list of all indices of a value on the list L beginning from position start
	"""
	positions = []
	lL = len(L) - 1
	i = start - 1
	while(i < lL):
		i +=1
		try:
			if value == L[i]: positions.append(i) 
		except: pass 
	return positions
		
def get_orien_assignment_mpi(angle_step, partids, params, log_main):
	global Tracker, Blockdata
	from applications import MPI_start_end
	from utilities    import even_angles, wrap_mpi_recv, wrap_mpi_bcast, wrap_mpi_send, read_text_row, read_text_file, getvec
	sym_class = Blockdata["symclass"]
	"""
	if Blockdata["myid"] == Blockdata["main_node"]:
		msg = " Generate sampling orientations for MGSKmeans with angular step %f  "%(angle_step)
		log_main.add(msg)
		print(msg)
	"""
	image_start, image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], Blockdata["myid"])
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		orien_group_assignment = [None for im in xrange(Tracker["total_stack"])]
	else:  orien_group_assignment = 0
	refa = sym_class.even_angles(angle_step, theta1 = Tracker["tilt1"], theta2 = Tracker["tilt2"])
	
	shakenumber = uniform( -Tracker["constants"]["shake"], Tracker["constants"]["shake"])
	shakenumber = round(shakenumber, 5)
	rangle = angle_step*shakenumber
	refa = Blockdata["symclass"].reduce_anglesets(rotate_params(refa, [-rangle,-rangle,-rangle]))
	
	refa_vecs = []
	for i in xrange(len(refa)):
		tmp = getvec(refa[i][0], refa[i][1])
		refa_vecs.append(tmp)
		
	if Blockdata["main_node"] == Blockdata["myid"]:
		params  = read_text_row(params)
		partids = read_text_file(partids, -1)
		if len(partids) == 1: partids = partids[0]
		else: partids = partids[1]
		data_angles = [[None, None] for im in xrange(len(partids))]
		for im in xrange(len(partids)): 
			data_angles[im] = getvec(params[partids[im]][0], params[partids[im]][1])
		del params
		del partids
	else: data_angles = 0
	data_angles = wrap_mpi_bcast(data_angles, Blockdata["main_node"], MPI_COMM_WORLD)
	
	data_angles = data_angles[image_start: image_end]
	local_orien_group_assignment = partition_data_into_orientation_groups_nompi(refa_vecs, data_angles)
	if Blockdata["myid"] == Blockdata["main_node"]: orien_group_assignment[image_start:image_end] = local_orien_group_assignment[:]
	else:  orien_group_assignment = 0	
	if Blockdata["main_node"] != Blockdata["myid"]: wrap_mpi_send(local_orien_group_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
	else:
		for iproc in xrange(Blockdata["nproc"]):
			iproc_image_start, iproc_image_end = MPI_start_end(Tracker["total_stack"], Blockdata["nproc"], iproc)
			if iproc != Blockdata["main_node"]:
				dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
				orien_group_assignment[iproc_image_start:iproc_image_end] = dummy[:]
				del dummy
	mpi_barrier(MPI_COMM_WORLD)
	orien_group_assignment = wrap_mpi_bcast(orien_group_assignment, Blockdata["main_node"], MPI_COMM_WORLD)
	ptls_in_orien_groups = [ None for iref in xrange(len(refa_vecs))]
	for iorien in xrange(len(refa_vecs)):
		if iorien%Blockdata["nproc"] == Blockdata["myid"]: ptls_in_orien_groups[iorien] = findall_dict(iorien, orien_group_assignment)
	mpi_barrier(MPI_COMM_WORLD)
	
	for iorien in xrange(len(refa_vecs)):
		if iorien%Blockdata["nproc"]!= Blockdata["main_node"]:
			if iorien%Blockdata["nproc"]==Blockdata["myid"]: wrap_mpi_send(ptls_in_orien_groups[iorien], Blockdata["main_node"], MPI_COMM_WORLD)
			if Blockdata["myid"] ==Blockdata["main_node"]: ptls_in_orien_groups[iorien] = wrap_mpi_recv(iorien%Blockdata["nproc"], MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)	
	mpi_barrier(MPI_COMM_WORLD)
	mpi_barrier(MPI_COMM_WORLD)
	zero_member_group_found = 0
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		small_groups = []
		for iorien in xrange(len(refa_vecs)):
			if len(ptls_in_orien_groups[iorien]) <Tracker["min_orien_group_size"]:small_groups.append(iorien)
			if len(ptls_in_orien_groups[iorien]) == 0:
				zero_member_group_found += 1
		matched_pairs = find_neighborhood(refa_vecs, small_groups)
		if len(matched_pairs)>=1:
			ptls_in_orien_groups = reassign_ptls_in_orien_groups(ptls_in_orien_groups, matched_pairs)
	else: ptls_in_orien_groups = 0
	zero_member_group_found = bcast_number_to_all(zero_member_group_found, Blockdata["main_node"], MPI_COMM_WORLD)
	ptls_in_orien_groups = wrap_mpi_bcast(ptls_in_orien_groups, Blockdata["main_node"], MPI_COMM_WORLD)
	
	del refa_vecs, refa
	del local_orien_group_assignment
	del data_angles
	del orien_group_assignment
	del sym_class
	return ptls_in_orien_groups

def get_angle_step_from_number_of_orien_groups(orien_groups):
	global Tracker, Blockdata
	from string import atof
	sym_class = Blockdata["symclass"]
	N = orien_groups
	angle_step = 180.
	while len(sym_class.even_angles(angle_step))< N:
		angle_step /=2.
	while len(sym_class.even_angles(angle_step))> N:
		angle_step +=0.1
	del sym_class
	return angle_step
	
#####<<<<<<<<<<<--------------orientation groups	
def compare_two_iterations(assignment1, assignment2, number_of_groups):
	# compare two assignments during clustering, either iteratively or independently
	import numpy as np
	assigned_groups1 =[[] for i in xrange(number_of_groups)]
	for im in xrange(len(assignment1)):assigned_groups1[assignment1[im]].append(im)
	res1 = []
	for iref in xrange(number_of_groups):
		a = np.array(assigned_groups1[iref],"int32")
		a.sort()
		res1.append(a)
	assigned_groups2 =[[] for i in xrange(number_of_groups)]
	for im in xrange(len(assignment2)): assigned_groups2[assignment2[im]].append(im)
	res2 = []
	for iref in xrange(number_of_groups):
		a = np.array(assigned_groups2[iref],"int32")
		a.sort()
		res2.append(a)
		del a
	newindeces, list_stable, nb_tot_objs = k_means_match_clusters_asg_new(res1, res2)
	del res1
	del res2
	return float(nb_tot_objs)/len(assignment1), newindeces, list_stable
	
def update_data_assignment(cdata, rdata, assignment, proc_list, nosmearing, myid):
	nima = len(cdata)
	groupids  = assignment[proc_list[myid][0]:proc_list[myid][1]]
	for im in xrange(nima):
		try: previous_group = cdata[im].get_attr("group")
		except: previous_group = -1
		cdata[im].set_attr("group", groupids[im])
		if nosmearing:
			rdata[im].set_attr("group", groupids[im])
			rdata[im].set_attr("previous_group", previous_group) 
		else:
			for jm in xrange(len(rdata[im])):
				rdata[im][jm].set_attr("previous_group", previous_group) 
				rdata[im][jm].set_attr("group", groupids[im])
	return
	
def update_rdata_assignment(assignment, proc_list, myid, rdata):
	nima = len(rdata)
	groupids = assignment[proc_list[myid][0]:proc_list[myid][1]]
	for im in xrange(nima): rdata[im].set_attr("group", groupids[im])
	return
	
def MPI_volume_start_end(number_of_groups, ncolor, mycolor):
	igroup_start = int(round(float(number_of_groups)/ncolor*mycolor))
	igroup_end   = int(round(float(number_of_groups)/ncolor*(mycolor+1)))
	return igroup_start, igroup_end
	
## conversion
def copy_refinement_tracker(tracker_refinement):
	global Tracker, Blockdata
	for key, value in Tracker:
		try:
			value_refinement = tracker_refinement[key]
			#if value != value_refinement:
			#	if Blockdata["myid"] == Blockdata["main_node"]:
			#		print(key, " in sorting set as ", value, ", while in refinement, it is set as ", value_refinement)
			if value == None and value_refinement != None: Tracker[key] = value_refinement
		except:
			if Blockdata["myid"] == Blockdata["main_node"]: print(key, " in sorting set as ", value, ", while in refinement, it is set as ", value_refinement)
	return
	
def print_dict(dict, theme):
	print("                       ")
	print("                       ")
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	print(line,theme)
	spaces = "                    "
	exclude = ["nodes", "yr", "output", "shared_comm", "bckgnoise", "myid", "myid_on_node", "accumulatepw", \
	     "chunk_dict", "PW_dict", "full_list", "rshifts", "refang", "chunk_dict", "PW_dict", "full_list", "rshifts", \
	        "refang", "sorting_data_list", "partition", "constants", "random_assignment"]
	for key, value in sorted( dict.items() ):
		pt = True
		for ll in exclude:
			if(key == ll):
				pt = False
				break
		if pt:  print("                    => ", key+spaces[len(key):],":  ",value)
# --------------------------------------------------------------------------		
# - "Tracker" (dictionary) object
#   Keeps the current state of option settings and dataset 
#   (i.e. particle stack, reference volume, reconstructed volume, and etc)
#   Each iteration is allowed to add new fields/keys
#   if necessary. This happes especially when type of 3D Refinement or metamove changes.
#   Conceptually, each iteration will be associated to a specific Tracker state.
#   Therefore, the list of Tracker state represents the history of process.
#
#   This can be used to restart process from an arbitrary iteration.
##<<<-----------rec3d for sorting------->>>>>>>>>
def stepone(tvol, tweight):
	global Tracker, Blockdata
	tvol.set_attr("is_complex",1)
	ovol = Util.shrinkfvol(tvol,2)
	owol = Util.shrinkfvol(tweight,2)
	if( Tracker["constants"]["symmetry"] != "c1" ):
		ovol = ovol.symfvol(Tracker["constants"]["symmetry"], -1)
		owol = owol.symfvol(Tracker["constants"]["symmetry"], -1)
	return Util.divn_cbyr(ovol,owol)
	
def steptwo_mpi(tvol, tweight, treg, cfsc = None, regularized = True, color = 0):
	global Tracker, Blockdata
	if( Blockdata["color"] != color ):return model_blank(1)  #  This should not be executed if called properly
	if( Blockdata["myid_on_node"] == 0 ):
		nz = tweight.get_zsize()
		ny = tweight.get_ysize()
		nx = tweight.get_xsize()
		tvol.set_attr_dict({"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1})
		if regularized:
			nr = len(cfsc)
			limitres = 0
			for i in xrange(nr):
				cfsc[i] = min(max(cfsc[i], 0.0), 0.999)
				if( cfsc[i] == 0.0 ):
					limitres = i-1
					break
			if( limitres == 0 ): limitres = nr-2;
			ovol = reshape_1d(cfsc, nr, 2*nr)
			limitres = 2*min(limitres, Tracker["maxfrad"])  # 2 on account of padding, which is always on
			maxr2 = limitres**2
			for i in xrange(limitres+1, len(ovol), 1):   ovol[i] = 0.0
			ovol[0] = 1.0
			it = model_blank(2*nr)
			for i in xrange(2*nr):  it[i] = ovol[i]
			del ovol
			#  Do not regularize first four
			for i in xrange(5):  treg[i] = 0.0
			Util.reg_weights(tweight, treg, it)
			del it
		else:
			limitres = 2*min(Tracker["constants"]["nnxo"]//2, Tracker["maxfrad"])
			maxr2 = limitres**2
		#  Iterative weights
		if( Tracker["constants"]["symmetry"] != "c1" ):
			tvol    = tvol.symfvol(Tracker["constants"]["symmetry"], limitres)
			tweight = tweight.symfvol(Tracker["constants"]["symmetry"], limitres)

	else:
		tvol = model_blank(1)
		tweight = model_blank(1)
		nz    = 0
		ny    = 0
		nx    = 0
		maxr2 = 0
	nx    = bcast_number_to_all(nx, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	ny    = bcast_number_to_all(ny, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	nz    = bcast_number_to_all(nz, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	maxr2 = bcast_number_to_all(maxr2, source_node = 0, mpi_comm = Blockdata["shared_comm"])

	vol_data = get_image_data(tvol)
	we_data =  get_image_data(tweight)
	#  tvol is overwritten, meaning it is also an output
	n_iter =10
	ifi = mpi_iterefa( vol_data.__array_interface__['data'][0] ,  we_data.__array_interface__['data'][0] , nx, ny, nz, maxr2, \
			Tracker["constants"]["nnxo"], Blockdata["myid_on_node"], color, Blockdata["no_of_processes_per_group"],  Blockdata["shared_comm"])###3, n_iter)
	if( Blockdata["myid_on_node"] == 0 ):
		#  Either pad or window in F space to 2*nnxo
		nx = tvol.get_ysize()
		if( nx > 2*Tracker["constants"]["nnxo"]): tvol = fdecimate(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], False, False)
		elif(nx < 2*Tracker["constants"]["nnxo"]): tvol = fpol(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], RetReal = False, normalize = False)
		tvol = fft(tvol)
		tvol = cyclic_shift(tvol,Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		tvol = Util.window(tvol, Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		tvol.div_sinc(1)
		tvol = cosinemask(tvol, Tracker["constants"]["nnxo"]//2-1,5, None)
		return tvol
	else:  return None
	
def steptwo_mpi_filter(tvol, tweight, treg, cfsc = None, cutoff_freq = 0.45, aa = 0.01, regularized = True, color = 0):
	global Tracker, Blockdata
	cutoff_freq2, aa = estimate_tanhl_params(cutoff_freq, aa, 2*Tracker["constants"]["nnxo"])
	if( Blockdata["color"] != color ):return model_blank(1)  #  This should not be executed if called properly
	if( Blockdata["myid_on_node"] == 0 ):
		nz = tweight.get_zsize()
		ny = tweight.get_ysize()
		nx = tweight.get_xsize()
		tvol.set_attr_dict({"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1})
		if regularized:
			nr = len(cfsc)
			limitres = 0
			for i in xrange(nr):
				cfsc[i] = min(max(cfsc[i], 0.0), 0.999)
				if( cfsc[i] == 0.0 ):
					limitres = i-1
					break
			if( limitres == 0 ): limitres = nr-2;
			ovol = reshape_1d(cfsc, nr, 2*nr)
			limitres = 2*min(limitres, Tracker["maxfrad"])  # 2 on account of padding, which is always on
			maxr2 = limitres**2
			for i in xrange(limitres+1, len(ovol), 1):   ovol[i] = 0.0
			ovol[0] = 1.0
			it = model_blank(2*nr)
			for i in xrange(2*nr):  it[i] = ovol[i]
			del ovol
			#  Do not regularize first four
			for i in xrange(5):  treg[i] = 0.0
			Util.reg_weights(tweight, treg, it)
			del it
		else:
			limitres = 2*min(Tracker["constants"]["nnxo"]//2, Tracker["maxfrad"])
			maxr2 = limitres**2
		#  Iterative weights
		if( Tracker["constants"]["symmetry"] != "c1" ):
			tvol    = tvol.symfvol(Tracker["constants"]["symmetry"], limitres)
			tweight = tweight.symfvol(Tracker["constants"]["symmetry"], limitres)

	else:
		tvol = model_blank(1)
		tweight = model_blank(1)
		nz    = 0
		ny    = 0
		nx    = 0
		maxr2 = 0
	nx    = bcast_number_to_all(nx, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	ny    = bcast_number_to_all(ny, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	nz    = bcast_number_to_all(nz, source_node = 0, mpi_comm = Blockdata["shared_comm"])
	maxr2 = bcast_number_to_all(maxr2, source_node = 0, mpi_comm = Blockdata["shared_comm"])

	vol_data = get_image_data(tvol)
	we_data =  get_image_data(tweight)
	#  tvol is overwritten, meaning it is also an output
	n_iter =10
	ifi = mpi_iterefa( vol_data.__array_interface__['data'][0] ,  we_data.__array_interface__['data'][0] , nx, ny, nz, maxr2, \
			Tracker["constants"]["nnxo"], Blockdata["myid_on_node"], color, Blockdata["no_of_processes_per_group"],  Blockdata["shared_comm"])####, n_iter)	
	if( Blockdata["myid_on_node"] == 0 ):
		from filter       import  filt_tanl
		#  Either pad or window in F space to 2*nnxo
		tvol = filt_tanl(tvol, cutoff_freq2, aa)
		nx = tvol.get_ysize()
		if( nx > 2*Tracker["constants"]["nnxo"]):  tvol = fdecimate(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], False, False)
		elif(nx < 2*Tracker["constants"]["nnxo"]): tvol = fpol(tvol, 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], 2*Tracker["constants"]["nnxo"], RetReal = False, normalize = False)
		tvol = fft(tvol)
		tvol = cyclic_shift(tvol,Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		tvol = Util.window(tvol, Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"],Tracker["constants"]["nnxo"])
		tvol.div_sinc(1)
		tvol = cosinemask(tvol, Tracker["constants"]["nnxo"]//2-1,5, None)
		return tvol
	else:  return None
####<<<<<-----------	
def recons3d_4nnsorting_MPI(myid, main_node, prjlist, random_subset, CTF = True, upweighted = True, mpi_comm= None, target_size=-1):
	"""
		recons3d_4nn_ctf - calculate CTF-corrected 3-D reconstruction from a set of projections using three Eulerian angles, two shifts, and CTF settings for each projeciton image
		Input
			list_of_prjlist: list of lists of projections to be included in the reconstruction
	"""
	from utilities		import reduce_EMData_to_root, random_string, get_im, findall, model_blank, info, get_params_proj
	from filter			import filt_table
	from reconstruction import insert_slices_pdf
	from fundamentals	import fft
	from statistics	    import fsc
	from EMAN2			import Reconstructors
	from mpi			import MPI_COMM_WORLD, mpi_barrier
	import types
	import datetime
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	imgsize = prjlist[0].get_ysize()  # It can be Fourier, so take y-size
	refvol  = model_blank(target_size)
	refvol.set_attr("fudge", 1.0)
	if CTF: do_ctf = 1
	else: do_ctf = 0
	fftvol = EMData()
	weight = EMData()
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r = Reconstructors.get( "nn4_ctfw", params )
	r.setup()
	#if norm_per_particle == None: norm_per_particle = len(prjlist)*[1.0]
	for im in xrange(len(prjlist)):
		phi, theta, psi, s2x, s2y = get_params_proj(prjlist[im], xform = "xform.projection") # shifts are already applied 
		if random_subset == 2:
			bckgn = target_size*[1.]
			if prjlist[im].get_attr("is_complex") == 0:	prjlist[im] = fft(prjlist[im]) 
			prjlist[im].set_attr_dict({"padffted":1, "is_complex":1})
			if not upweighted:  prjlist[im] = filt_table(prjlist[im], bckgn)
			prjlist[im].set_attr("bckgnoise", bckgn)
			r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)
		else:
			if prjlist[im].get_attr("chunk_id") == random_subset:
				#try:	bckgn = prjlist[im].get_attr("bckgnoise")
				bckgn = target_size*[1.]
				if prjlist[im].get_attr("is_complex")==0: prjlist[im] = fft(prjlist[im])
				prjlist[im].set_attr_dict({"padffted":1, "is_complex":1})
				if not upweighted:  prjlist[im] = filt_table(prjlist[im], bckgn)
				prjlist[im].set_attr("bckgnoise", bckgn)
				r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)		
	#  clean stuff
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if myid == main_node: dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else: return None, None, None

def recons3d_4nnsorting_group_MPI(myid, main_node, prjlist, random_subset, group_ID, CTF = True, upweighted = True, mpi_comm= None, target_size=-1):
	"""
		recons3d_4nn_ctf - calculate CTF-corrected 3-D reconstruction from a set of projections using three Eulerian angles, two shifts, and CTF settings for each projeciton image
		Input
			list_of_prjlist: list of lists of projections to be included in the reconstruction
	"""
	from utilities      import reduce_EMData_to_root, random_string, get_im, findall
	from EMAN2          import Reconstructors
	from utilities      import model_blank, info
	from filter		    import filt_table
	from mpi            import MPI_COMM_WORLD, mpi_barrier
	from statistics     import fsc 
	from reconstruction import insert_slices_pdf
	from fundamentals   import fft
	import datetime, types
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	imgsize = prjlist[0].get_ysize()  # It can be Fourier, so take y-size
	refvol = model_blank(target_size)
	refvol.set_attr("fudge", 1.0)
	if CTF: do_ctf = 1
	else:   do_ctf = 0
	fftvol = EMData()
	weight = EMData()
	try:    qt = projlist[0].get_attr("qt")
	except: qt = 1.0
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r = Reconstructors.get( "nn4_ctfw", params )
	r.setup()
	for im in xrange(len(prjlist)):
		phi, theta, psi, s2x, s2y = get_params_proj(prjlist[im], xform = "xform.projection") # shifts are already applied
		if prjlist[im].get_attr("group") == group_ID:
			if random_subset == 2:
				try:	bckgn = prjlist[im].get_attr("bckgnoise")
				except:	bckgn = target_size*[1.]
				if prjlist[im].get_attr("is_complex") == 0:	image = fft(prjlist[im])
				else: image =  prjlist[im].copy()
				image.set_attr_dict({"padffted":1, "is_complex":1})
				if not upweighted:  image = filt_table(image, bckgn)
				image.set_attr("bckgnoise", bckgn)
				r.insert_slice(image, Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)
			else:
				if prjlist[im].get_attr("chunk_id") == random_subset:
					try:     bckgn = prjlist[im].get_attr("bckgnoise")
					except:	 bckgn = target_size*[1.]
					if prjlist[im].get_attr("is_complex")==0: image = fft(prjlist[im])
					else: image =  prjlist[im].copy()
					image.set_attr_dict({"padffted":1, "is_complex":1})
					if not upweighted:  image = filt_table(image, bckgn)              
					image.set_attr("bckgnoise", bckgn)
					r.insert_slice(image, Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)	
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if myid == main_node: dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else: return None, None, None

def do3d_sorting(procid, data, myid, mpi_comm = -1):
	global Tracker, Blockdata
	if (mpi_comm == -1): mpi_comm = MPI_COMM_WORLD
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if(procid == 0):
		if(Blockdata["no_of_groups"] >1):
			if(Blockdata["myid"] == Blockdata["nodes"][procid]):
				if os.path.exists(os.path.join(Tracker["directory"], "tempdir")): print("tempdir exists")
				else:
					try: os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
					except:  print("tempdir exists")
		else:
			if myid == Blockdata["main_node"]:
				if not os.path.exists(os.path.join(Tracker["directory"],"tempdir")): 
					try: os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
					except: print("tempdir exists")
				else: print("tempdir exists")
	mpi_barrier(mpi_comm)
	
	if(Blockdata["myid"] == Blockdata["main_node"]):print(line, "do3d_sorting")
	tvol, tweight, trol = recons3d_4nnsorting_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][procid], prjlist = data,\
		random_subset = procid, CTF = Tracker["constants"]["CTF"], upweighted = False, target_size = (2*Tracker["nxinit"]+3), mpi_comm  = mpi_comm)
		
	if(Blockdata["no_of_groups"] >1):
		if(Blockdata["myid"] == Blockdata["nodes"][procid]):
			if(procid == 0):
				if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")):os.mkdir(os.path.join(Tracker["directory"],"tempdir"))
			tvol.set_attr("is_complex",0)
			tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%01d.hdf"%procid))
			tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%01d.hdf"%procid))
			trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%01d.hdf"%procid))
	else:
		if myid == Blockdata["main_node"]:
			tvol.set_attr("is_complex",0)
			tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%01d.hdf"%procid))
			tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%01d.hdf"%procid))
			trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%01d.hdf"%procid))
	mpi_barrier(mpi_comm)
	return
			
def do3d_sorting_group_insertion(data, randomset=2):
	global Tracker, Blockdata
	if(Blockdata["myid"] == Blockdata["last_node"]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")):os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] ==  Blockdata["main_node"]:print(line, "start backprojection of %d volumes"%Tracker["number_of_groups"])
	if randomset ==1:
		if Blockdata["myid"] == Blockdata["main_node"]:print(line, "mode1: start backprojection of %d volumes"%Tracker["number_of_groups"])		
		for index_of_groups in xrange(Tracker["number_of_groups"]):
			for procid in xrange(2, 3):
				tvol, tweight, trol = recons3d_4nnsorting_group_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][0],\
				  prjlist = data,  random_subset = procid, group_ID = index_of_groups, CTF = Tracker["constants"]["CTF"],\
					upweighted = False, target_size = (2*Tracker["nxinit"]+3))
				
				if(Blockdata["myid"] == Blockdata["nodes"][procid]):
					tvol.set_attr("is_complex",0)
					tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d.hdf"%(procid, index_of_groups)))
					tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d.hdf"%(procid, index_of_groups)))
					trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d.hdf"%(procid, index_of_groups)))
				mpi_barrier(MPI_COMM_WORLD)
	else:
		if Blockdata["myid"] == Blockdata["main_node"]:print(line, "mode2: start backprojection of %d volumes"%Tracker["number_of_groups"])		
		for index_of_groups in xrange(Tracker["number_of_groups"]):
			for procid in xrange(2):
				tvol, tweight, trol = recons3d_4nnsorting_group_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][procid],  \
				  prjlist = data, random_subset = procid, group_ID = index_of_groups, CTF = Tracker["constants"]["CTF"],\
					upweighted = False, target_size = (2*Tracker["nxinit"]+3))
				
				if(Blockdata["myid"] == Blockdata["nodes"][procid]):
					tvol.set_attr("is_complex",0)
					tag =7007
					send_EMData(tvol,    Blockdata["last_node"], tag, MPI_COMM_WORLD)
					send_EMData(tweight, Blockdata["last_node"], tag, MPI_COMM_WORLD)
					send_EMData(trol,    Blockdata["last_node"], tag, MPI_COMM_WORLD)
					
				elif Blockdata["myid"] == Blockdata["last_node"]:
					tag =7007
					tvol    = recv_EMData(Blockdata["nodes"][procid], tag, MPI_COMM_WORLD)
					tweight = recv_EMData(Blockdata["nodes"][procid], tag, MPI_COMM_WORLD)
					trol    = recv_EMData(Blockdata["nodes"][procid], tag, MPI_COMM_WORLD)
					tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d.hdf"%(procid, index_of_groups)))
					tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d.hdf"%(procid, index_of_groups)))
					trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d.hdf"%(procid, index_of_groups)))
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
	return
	
def do3d_sorting_groups_trl_iter(data, iteration):
	global Tracker, Blockdata
	from utilities import get_im, write_text_row, bcast_number_to_all, wrap_mpi_bcast
	keepgoing = 1
	if(Blockdata["myid"] == Blockdata["last_node"]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	mpi_barrier(MPI_COMM_WORLD)
	do3d_sorting_group_insertion(data)
	print("done step1")
	fsc143             = 0
	fsc05              = 0
	Tracker["fsc143"]  = 0
	Tracker["fsc05"]   = 0
	res_05             = Tracker["number_of_groups"]*[0]
	res_143            = Tracker["number_of_groups"]*[0]
	#####
	if Blockdata["no_of_groups"]>1:
		sub_main_node_list = [-1 for i in xrange(Blockdata["no_of_groups"])]
		for index_of_colors in xrange(Blockdata["no_of_groups"]):
			for iproc in xrange(Blockdata["nproc"]-1):
				if Blockdata["myid"]== iproc:
					if Blockdata["color"] == index_of_colors and Blockdata["myid_on_node"] == 0:
						sub_main_node_list[index_of_colors] = Blockdata["myid"]
					wrap_mpi_send(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
				if Blockdata["myid"] == Blockdata["last_node"]:
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for im in xrange(len(dummy)):
						if dummy[im]>-1: sub_main_node_list[im] = dummy[im]
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		#print("done step2")
		wrap_mpi_bcast(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
		#if Blockdata["myid"] == Blockdata["last_node"]:
		#	print("MMM", sub_main_node_list)
		####		
		if Tracker["number_of_groups"]%Blockdata["no_of_groups"] == 0: 
			nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]
		else: nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]+1
	
		big_loop_colors = [[] for i in xrange(nbig_loop)]
		big_loop_groups = [[] for i in xrange(nbig_loop)]
		nc = 0
		while nc <Tracker["number_of_groups"]:
			im =  nc//Blockdata["no_of_groups"]
			jm =  nc%Blockdata["no_of_groups"]
			big_loop_colors[im].append(jm)
			big_loop_groups[im].append(nc)
			nc +=1
		if Blockdata["myid"] == Blockdata["last_node"]:
			print(big_loop_groups, big_loop_colors)
		#####
		for iloop in xrange(nbig_loop):
			#print("step 4", Tracker["directory"])
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0_%d.hdf")%index_of_group)
					tweight2 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0_%d.hdf")%index_of_group)
					treg2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0_%d.hdf")%index_of_group)
					tag         = 7007
					send_EMData(tvol2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(tweight2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(treg2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
				elif (Blockdata["myid"] == sub_main_node_list[index_of_colors]):
					tag      = 7007
					tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				#print("step 5")
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				Tracker["maxfrad"] = Tracker["nxinit"]//2
				if Blockdata["color"] == index_of_colors:
					if( Blockdata["myid_on_node"] != 0):
						tvol2 		= model_blank(1)
						tweight2 	= model_blank(1)
						treg2		= model_blank(1)
					tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = index_of_colors) # has to be False!!!
					del tweight2, treg2
					#if( Blockdata["myid_on_node"] == 0):
					#	tvol2 = cosinemask(tvol2, radius = Tracker["constants"]["radius"])
				mpi_barrier(Blockdata["shared_comm"])
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				#print("step 6")
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if (Blockdata["color"] == index_of_colors) and (Blockdata["myid_on_node"] == 0):
					tag = 7007
					send_EMData(tvol2, Blockdata["last_node"], tag, MPI_COMM_WORLD)
				elif(Blockdata["myid"] == Blockdata["last_node"]):
					tag = 7007
					tvol2 = recv_EMData(sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_0_grp%03d_iter%03d.hdf"%(index_of_group,iteration)))
					del tvol2
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1_%d.hdf")%index_of_group)
					tweight2 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1_%d.hdf")%index_of_group)
					treg2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "trol_1_%d.hdf"%index_of_group))
					tag      = 7007
					send_EMData(tvol2,    sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					send_EMData(tweight2, sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					send_EMData(treg2,    sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
				elif (Blockdata["myid"] == sub_main_node_list[index_of_colors]):
					tag      = 7007
					tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				Tracker["maxfrad"] = Tracker["nxinit"]//2
				if Blockdata["color"] == index_of_colors:
					if( Blockdata["myid_on_node"] != 0):
						tvol2 		= model_blank(1)
						tweight2 	= model_blank(1)
						treg2		= model_blank(1)
					tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = index_of_colors) # has to be False!!!
					del tweight2, treg2
					#if( Blockdata["myid_on_node"] == 0):
					#	tvol2 = cosinemask(tvol2, radius = Tracker["constants"]["radius"])
				mpi_barrier(Blockdata["shared_comm"])
			mpi_barrier(MPI_COMM_WORLD)
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if (Blockdata["color"] == index_of_colors) and (Blockdata["myid_on_node"] == 0):
					tag = 7007
					send_EMData(tvol2, Blockdata["last_node"], tag, MPI_COMM_WORLD)
				elif(Blockdata["myid"] == Blockdata["last_node"]):
					tag = 7007
					tvol2 = recv_EMData(sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_1_grp%03d_iter%03d.hdf"%(index_of_group,iteration)))
					del tvol2
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
	else:
		Tracker["maxfrad"] = Tracker["nxinit"]//2
		for index_of_group in xrange(Tracker["number_of_groups"]):
			for iprocid in xrange(2):
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d.hdf")%(iprocid, index_of_group))
					tweight2 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d.hdf")%(iprocid, index_of_group))
					treg2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d.hdf"%(iprocid, index_of_group)))
					tag      = 7007
					send_EMData(tvol2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
					send_EMData(tweight2, Blockdata["main_node"], tag, MPI_COMM_WORLD)
					send_EMData(treg2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
				elif (Blockdata["myid"] == Blockdata["main_node"]):
					tag      = 7007
					tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
				if( Blockdata["myid"] != Blockdata["main_node"]):
					tvol2 		= model_blank(1)
					tweight2 	= model_blank(1)
					treg2		= model_blank(1)
				tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = 0) # has to be False!!!
				del tweight2, treg2
				if( Blockdata["myid"] == Blockdata["main_node"]):
					#tvol2 = cosinemask(tvol2, radius = Tracker["constants"]["radius"])
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_%d_grp%03d_iter%03d.hdf"%(iprocid, index_of_group,iteration)))
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
	keepgoing = bcast_number_to_all(keepgoing, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD) # always check 
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
	if keepgoing == 0: ERROR("do3d_sorting_groups_trl_iter  %s"%os.path.join(Tracker["directory"], "tempdir"),"do3d_sorting_groups_trl_iter", 1, Blockdata["myid"]) 
	return
	
# Three ways of importing refinement results
def get_input_from_sparx_ref3d(log_main):# case one
	# import SPARX results
	global Tracker, Blockdata
	import json
	from shutil import copyfile
	from  string import split, atoi
	import_from_sparx_refinement = 1
	selected_iter      = 0
	Tracker_refinement = 0
	checking_flag      = 0
	if Blockdata["myid"] == Blockdata["main_node"]:
		if not os.path.exists (Tracker["constants"]["refinement_dir"]): checking_flag = 1
	checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
	if checking_flag: ERROR("SPARX refinement dir does not exist", "get_input_from_sparx_ref3d", 1, Blockdata["myid"])
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]:
		msg = "Import results from SPARX 3-D refinement"
		print(line, msg)
		log_main.add(msg)
		if Tracker["constants"]["niter_for_sorting"] == -1: # take the best solution to do sorting
			msg = "Search in the directory %s ......"%Tracker["constants"]["refinement_dir"]
			print(line, msg)
			log_main.add(msg)
			niter_refinement = 0
			while os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%niter_refinement)) and os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"],"main%03d"%niter_refinement, "Tracker_%03d.json"%niter_refinement)):
				niter_refinement +=1
			niter_refinement -=1
			if niter_refinement !=0:
				fout = open(os.path.join(Tracker["constants"]["refinement_dir"],"main%03d"%niter_refinement, "Tracker_%03d.json"%niter_refinement),'r')
				Tracker_refinement 	= convert_json_fromunicode(json.load(fout))
				fout.close()
				selected_iter = Tracker_refinement["constants"]["best"]
			else: import_from_sparx_refinement = 0
		else:
			msg = "Try to load json file ...%s"%os.path.join(Tracker["constants"]["refinement_dir"],"main%03d"%Tracker["constants"]["niter_for_sorting"],\
			 "Tracker_%03d.json"%Tracker["constants"]["niter_for_sorting"])
			print(line, msg)
			log_main.add(msg)
			try:
				fout = open(os.path.join(Tracker["constants"]["refinement_dir"],"main%03d"%Tracker["constants"]["niter_for_sorting"], \
				"Tracker_%03d.json"%Tracker["constants"]["niter_for_sorting"]),'r')
				Tracker_refinement	= convert_json_fromunicode(json.load(fout))
				fout.close()
				selected_iter = Tracker["constants"]["niter_for_sorting"]
			except:	import_from_sparx_refinement = 0
	else: selected_iter = -1	
	selected_iter = bcast_number_to_all(selected_iter, Blockdata["main_node"], MPI_COMM_WORLD)
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	if import_from_sparx_refinement == 0:	
		ERROR("The best solution is not found","get_input_from_sparx_ref3d", "get_input_from_sparx_ref3d", 1, Blockdata["myid"])
		from mpi import mpi_finalize
		mpi_finalize()
		exit()			
	Tracker_refinement = wrap_mpi_bcast(Tracker_refinement, Blockdata["main_node"], communicator = MPI_COMM_WORLD)
	# Check orgstack, set correct path
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	
	if Blockdata["myid"] == Blockdata["main_node"]:
		refinement_dir_path, refinement_dir_name = os.path.split(Tracker["constants"]["refinement_dir"])	
		if Tracker_refinement["constants"]["stack"][0:4]=="bdb:": refinement_stack = "bdb:"+os.path.join(refinement_dir_path, Tracker_refinement["constants"]["stack"][4:])
		else: refinement_stack = os.path.join(refinement_dir_path, Tracker_refinement["constants"]["stack"])
		if not Tracker["constants"]["orgstack"]: # Use refinement stack if instack is not provided
			msg = "refinement stack  %s"%refinement_stack
			print(line, msg)
			log_main.add(msg)
			Tracker["constants"]["orgstack"] = refinement_stack #Tracker_refinement["constants"]["stack"]
			print(line, "The refinement image stack is %s"%Tracker_refinement["constants"]["stack"])
			try: image = get_im(Tracker["constants"]["orgstack"], 0)
			except:
				print(line, "Fail to read image stack")	
				import_from_sparx_refinement = 0
		else:
			if Tracker["constants"]["orgstack"] == Tracker_refinement["constants"]["stack"]: # instack and refinement data stack is the same
				msg = "The sorting instack is the same refinement instack: %s"%Tracker_refinement["constants"]["stack"]
				print(line, msg)
				log_main.add(msg)
				if not os.path.exists(Tracker["constants"]["orgstack"]): import_from_sparx_refinement = 0
			else: # complicated cases
				if (not os.path.exists(Tracker["constants"]["orgstack"])) and (not os.path.exists(Tracker_refinement["constants"]["stack"])): 
					import_from_sparx_refinement = 0
				elif (not os.path.exists(Tracker["constants"]["orgstack"])) and os.path.exists(Tracker_refinement["constants"]["stack"]):
					old_stack = Tracker["constants"]["stack"]
					if old_stack[0:3] == "bdb":
						Tracker["constants"]["orgstack"] = "bdb:" + Tracker["constants"]["refinement_dir"]+"/../"+old_stack[4:]
					else: Tracker["constants"]["orgstack"] = os.path.join(option_old_refinement_dir, "../", old_stack)
					msg = "Use refinement orgstack "
					print(line, msg)
					log_main.add(msg)
				else:
					msg = "Use orgstack provided by options"
					print(line, msg)
					log_main.add(msg)
		if import_from_sparx_refinement:
			msg =  "data stack for sorting is %s"%Tracker["constants"]["orgstack"]
			print(line, msg)
			log_main.add(msg)
		total_stack   = EMUtil.get_image_count(Tracker["constants"]["orgstack"])
	else: total_stack = 0
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	
	if import_from_sparx_refinement == 0:ERROR("The data stack is not accessible","get_input_from_sparx_ref3d",1, Blockdata["myid"])
	total_stack = bcast_number_to_all(total_stack, source_node = Blockdata["main_node"])			
	Tracker["constants"]["total_stack"] = total_stack
	
	# Now copy relevant refinement files to sorting directory:
	if Blockdata["myid"] == Blockdata["main_node"]:
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, "params_%03d.txt"%selected_iter)):
			copyfile( os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, \
			 "params_%03d.txt"%selected_iter), os.path.join(Tracker["constants"]["masterdir"], "sparx_refinement_params.txt"))
		else: import_from_sparx_refinement = 0
		Tracker["constants"]["selected_iter"] = selected_iter
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	if import_from_sparx_refinement == 0:ERROR("The parameter file of the best solution is not accessible", "get_input_from_sparx_ref3d", 1, Blockdata["myid"])
		
	if Blockdata["myid"] == Blockdata["main_node"]:
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, "bckgnoise.hdf")):
			copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, "bckgnoise.hdf"),\
			os.path.join(Tracker["constants"]["masterdir"], "bckgnoise.hdf"))
		else:
			import_from_sparx_refinement == 0
			for search_iter in xrange(selected_iter-1, 0, -1):
				 if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%search_iter, "bckgnoise.hdf")):
					copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%search_iter, \
					"bckgnoise.hdf"), os.path.join(Tracker["constants"]["masterdir"], "bckgnoise.hdf"))
					import_from_sparx_refinement = 1
					break
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	
	if import_from_sparx_refinement == 0:
		Tracker["bckgnoise"] = None
		if Blockdata["myid"] == Blockdata["main_node"]:	print("Noise file is not found. However we continue")
	else: Tracker["bckgnoise"] = os.path.join(Tracker["constants"]["masterdir"], "bckgnoise.hdf")
	
	import_from_sparx_refinement = 1	
	if Blockdata["myid"] == Blockdata["main_node"]:
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, "driver_%03d.txt"%selected_iter)):
			copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main%03d"%selected_iter, \
			 "driver_%03d.txt"%selected_iter), os.path.join(Tracker["constants"]["masterdir"], "fsc_global.txt"))
		else: import_from_sparx_refinement = 0
		#Tracker["constants"]["selected_iter"] = selected_iter
		if import_from_sparx_refinement: fsc_curve = read_text_row(os.path.join(Tracker["constants"]["masterdir"], "fsc_global.txt"))
		fsc143	= 0
		fsc05	= 0
		for ifreq in xrange(len(fsc_curve)): # drive has only one column
			if fsc_curve[ifreq][0] < 0.5: break
		fsc05  = ifreq - 1
		for ifreq in xrange(len(fsc_curve)):
			if fsc_curve[ifreq][0] < 0.143: break
		fsc143 = ifreq - 1	
		Tracker["constants"]["fsc143"]  = fsc143
		Tracker["constants"]["fsc05"]   = fsc05
		
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	if import_from_sparx_refinement == 0: ERROR("The driver of the best solution is not accessible","get_input_from_sparx_ref3d", 1, Blockdata["myid"])
	if Blockdata["myid"] == Blockdata["main_node"]:
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main000/indexes_000.txt")):
			copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main000/indexes_000.txt"), \
			os.path.join(Tracker["constants"]["masterdir"], "indexes.txt"))
		else:	import_from_sparx_refinement = 0
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	
	if import_from_sparx_refinement == 0: ERROR("The index file of the best solution are not accessible","get_input_from_sparx_ref3d", 1, Blockdata["myid"])
	if Blockdata["myid"] == Blockdata["main_node"]:
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main000/chunk_0_000.txt")):
			copyfile( os.path.join(Tracker["constants"]["refinement_dir"], "main000/chunk_0_000.txt"), \
			os.path.join(Tracker["constants"]["masterdir"], "chunk_0.txt"))
		else: import_from_sparx_refinement == 0
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main000/chunk_1_000.txt")):
			copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main000/chunk_1_000.txt"), \
			os.path.join(Tracker["constants"]["masterdir"], "chunk_1.txt"))
		else: import_from_sparx_refinement == 0
			
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main000/particle_groups_0.txt")):
			copyfile(os.path.join(Tracker["constants"]["refinement_dir"], "main000/particle_groups_0.txt"), \
			os.path.join(Tracker["constants"]["masterdir"], "particle_groups_0.txt"))
		else: import_from_sparx_refinement == 0
			
		if os.path.exists(os.path.join(Tracker["constants"]["refinement_dir"], "main000/particle_groups_1.txt")):
			copyfile( os.path.join(Tracker["constants"]["refinement_dir"], "main000/particle_groups_1.txt"), \
			os.path.join(Tracker["constants"]["masterdir"], "particle_groups_1.txt"))
		else:import_from_sparx_refinement == 0
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	if import_from_sparx_refinement == 0:ERROR("The chunk files and partice group files are not accessible","get_input_from_sparx_ref3d",1, Blockdata["myid"])
	
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	# copy all relavant parameters into sorting tracker
	if Blockdata["myid"] == Blockdata["main_node"]:
		if Tracker["constants"]["radius"] == -1: Tracker["constants"]["radius"] = Tracker_refinement["constants"]["radius"]
		Tracker["constants"]["nnxo"]       = Tracker_refinement["constants"]["nnxo"]
		Tracker["constants"]["orgres"]     = Tracker_refinement["bestres"]
		Tracker["delta"]                   = Tracker_refinement["delta"]
		Tracker["ts"]                      = Tracker_refinement["ts"]
		Tracker["xr"]                      = Tracker_refinement["xr"]
		Tracker["constants"]["pixel_size"] = Tracker_refinement["constants"]["pixel_size"]
		Tracker["avgnorm"]                 = Tracker_refinement["avgvaradj"]
		if Tracker["constants"]["nxinit"]<0: Tracker["nxinit_refinement"] = Tracker_refinement["nxinit"] #Sphire window size
		else:  Tracker["nxinit_refinement"] = Tracker["constants"]["nxinit"] #User defined window size
		
		
		try:     sym =  Tracker_refinement["constants"]["sym"]
		except:  sym =  Tracker_refinement["constants"]["symmetry"]
		if sym !='c1' and Tracker["constants"]["symmetry"] =='c1':
			Tracker["constants"]["symmetry"] = sym
			update_sym = 1
		else: update_sym = 0
		print(line, "Parameters importing is done!")
		if not Tracker["constants"]["mask3D"]:
			if Tracker_refinement["constants"]["mask3D"] and (not Tracker["constants"]["do_not_use_3dmask"]):
				refinement_mask3D_path, refinement_mask3D_file = os.path.split(Tracker_refinement["constants"]["mask3D"])# MRK_DEBUG
				copyfile( os.path.join(refinement_dir_path, Tracker_refinement["constants"]["mask3D"]), \
				os.path.join(Tracker["constants"]["masterdir"], refinement_mask3D_file))
				Tracker["constants"]["mask3D"] = os.path.join(Tracker["constants"]["masterdir"], refinement_mask3D_file)
	else: update_sym  = 0
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], communicator = MPI_COMM_WORLD)
	import_from_sparx_refinement = bcast_number_to_all(import_from_sparx_refinement, source_node = Blockdata["main_node"])
	update_sym = bcast_number_to_all(update_sym, source_node = Blockdata["main_node"])
	if not import_from_sparx_refinement:ERROR("Import parameters from SPARX refinement failed", "get_input_from_sparx_ref3d", 1,  Blockdata["myid"])
	if update_sym ==1:
		Blockdata["symclass"] = symclass(Tracker["constants"]["symmetry"])
		Tracker["constants"]["orientation_groups"] = max(4, 100//Blockdata["symclass"].nsym)
	
	# Setting for margin error				
	chunk_dict = {}
	group_dict = {}
	if(Blockdata["myid"] == Blockdata["main_node"]):
		chunk_one = read_text_file(os.path.join(Tracker["constants"]["masterdir"],"chunk_0.txt"))
		chunk_two = read_text_file(os.path.join(Tracker["constants"]["masterdir"],"chunk_1.txt"))
	else:
		chunk_one = 0
		chunk_two = 0
	chunk_one = wrap_mpi_bcast(chunk_one, Blockdata["main_node"])
	chunk_two = wrap_mpi_bcast(chunk_two, Blockdata["main_node"])
	#
	if(Blockdata["myid"] == Blockdata["main_node"]):
		chunk_one_group = read_text_file(os.path.join(Tracker["constants"]["masterdir"],"particle_groups_0.txt"))
		chunk_two_group = read_text_file(os.path.join(Tracker["constants"]["masterdir"],"particle_groups_1.txt"))
	else:
		chunk_one_group = 0
		chunk_two_group = 0
	chunk_one_group = wrap_mpi_bcast(chunk_one_group, Blockdata["main_node"])
	chunk_two_group = wrap_mpi_bcast(chunk_two_group, Blockdata["main_node"])
	for index_of_element in xrange(len(chunk_one)): 
		chunk_dict[chunk_one[index_of_element]] = 0
		group_dict[chunk_one[index_of_element]] = chunk_one_group[index_of_element]
	for index_of_element in xrange(len(chunk_two)): 
		chunk_dict[chunk_two[index_of_element]] = 1
		group_dict[chunk_two[index_of_element]] = chunk_two_group[index_of_element] 			
	Tracker["chunk_dict"] = chunk_dict
	Tracker["P_chunk_0"]  = len(chunk_one)/float(total_stack)
	Tracker["P_chunk_1"]  = len(chunk_two)/float(total_stack)
	if(Blockdata["myid"] == Blockdata["main_node"]):
		chunk_ids = []
		group_ids = []
		partids   = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "indexes.txt"),-1)
		partids   = partids[0]
		Tracker["constants"]["total_stack"] = len(partids)
		params = read_text_file(os.path.join(Tracker["constants"]["masterdir"], "sparx_refinement_params.txt"),-1)
		for index_of_particle in xrange(len(partids)): 
			chunk_ids.append(chunk_dict[partids[index_of_particle]])
			group_ids.append(group_dict[partids[index_of_particle]])
		refinement_params = [ params[0], params[1], params[2], params[3], params[4], chunk_ids, group_ids, params[7]]
		write_text_file(refinement_params, os.path.join(Tracker["constants"]["masterdir"], "refinement_parameters.txt"))		
		line  = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		print(line, "Initialization of sorting from SPARX refinement is done")
	else: Tracker["constants"]["total_stack"] = 0
	Tracker["constants"]["total_stack"]     = bcast_number_to_all(Tracker["constants"]["total_stack"], Blockdata["main_node"], MPI_COMM_WORLD)
	Tracker["total_stack"]                  = Tracker["constants"]["total_stack"]
	Tracker["constants"]["partstack"]	    = os.path.join(Tracker["constants"]["masterdir"], "refinement_parameters.txt")
	total_stack                             = Tracker["constants"]["total_stack"]
	Tracker["currentres"]                   = float(Tracker["constants"]["fsc05"])/float(Tracker["constants"]["nxinit"])
	Tracker["bckgnoise"]                    =  os.path.join(Tracker["constants"]["masterdir"], "bckgnoise.hdf")
	###
	from string import atoi
	if Tracker["constants"]["minimum_grp_size"] ==-1:
		Tracker["constants"]["minimum_grp_size"] = Tracker["constants"]["total_stack"]//Tracker["constants"]["img_per_grp"]*(100//Blockdata["symclass"].nsym)
	else: 
		Tracker["constants"]["minimum_grp_size"] = max(Tracker["constants"]["minimum_grp_size"], \
		   Tracker["constants"]["total_stack"]//Tracker["constants"]["img_per_grp"]*100//Blockdata["symclass"].nsym)
	# Now copy oldparamstruture
	copy_oldparamstructure_from_meridien_MPI(selected_iter, log_main)
	return import_from_sparx_refinement
		
def get_input_from_datastack(log_main):# Case three
	global Tracker, Blockdata
	from utilities import write_text_file, write_text_row, wrap_mpi_bcast
	import json
	from   string import split, atoi
	from   random import shuffle
	import_from_data_stack = 1
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		msg =  "Import xform.projection paramters from data stack %s "%Tracker["constants"]["orgstack"]
		print(line, msg)
		log_main.add(msg)
		image = get_im(Tracker["constants"]["orgstack"])
		Tracker["constants"]["nnxo"] = image.get_xsize()		
		if( Tracker["nxinit"] > Tracker["constants"]["nnxo"]):
				ERROR("Image size less than minimum permitted $d"%Tracker["nxinit"],"get_input_from_datastack",1, Blockdata["myid"])
				nnxo = -1
		else:
			if Tracker["constants"]["CTF"]:
				ictf = image.get_attr('ctf')
				Tracker["constants"]["pixel_size"] = ictf.apix
			else:
				Tracker["constants"]["pixel_size"] = 1.0
				del image
	else:
		Tracker["constants"]["nnxo"]       = 0
		Tracker["constants"]["pixel_size"] = 1.0
	Tracker["constants"]["nnxo"] = bcast_number_to_all(Tracker["constants"]["nnxo"], source_node = Blockdata["main_node"])
	if( Tracker["constants"]["nnxo"] < 0): ERROR("Image size is negative", "get_input_from_datastack", 1, Blockdata["main_node"])
	Tracker["constants"]["pixel_size"]	= bcast_number_to_all(Tracker["constants"]["pixel_size"], source_node =  Blockdata["main_node"])
	if(Tracker["constants"]["radius"] < 1): Tracker["constants"]["radius"]  = Tracker["constants"]["nnxo"]//2-2
	elif((2*Tracker["constants"]["radius"] +2) > Tracker["constants"]["nnxo"]): ERROR("Particle radius set too large!", \
	"get_input_from_datastack",1, Blockdata["myid"])
	if Blockdata["myid"] == Blockdata["main_node"]:	total_stack = EMUtil.get_image_count(Tracker["constants"]["orgstack"])
	else: total_stack = 0
	total_stack = bcast_number_to_all(total_stack, Blockdata["main_node"])
	# randomly assign two subsets
	Tracker["constants"]["total_stack"]	= total_stack
	Tracker["constants"]["chunk_0"]		= os.path.join(Tracker["constants"]["masterdir"],"chunk_0.txt")
	Tracker["constants"]["chunk_1"]		= os.path.join(Tracker["constants"]["masterdir"],"chunk_1.txt")
	Tracker["constants"]["partstack"]	= os.path.join(Tracker["constants"]["masterdir"], "refinement_parameters.txt")
	Tracker["previous_parstack"]        = os.path.join(Tracker["constants"]["masterdir"], "refinement_parameters.txt")#
	
	if Tracker["constants"]["minimum_grp_size"] ==-1:
		Tracker["constants"]["minimum_grp_size"] = Tracker["constants"]["total_stack"]//Tracker["constants"]["img_per_grp"]*(100//Blockdata["symclass"].nsym)
	else: 
		Tracker["constants"]["minimum_grp_size"] = max(Tracker["constants"]["minimum_grp_size"], \
		   Tracker["constants"]["total_stack"]//Tracker["constants"]["img_per_grp"]*100//Blockdata["symclass"].nsym)

	###
	Tracker["refang"], Tracker["rshifts"], Tracker["delta"] = None, None, None
	Tracker["avgnorm"] =1.0
	chunk_dict = {}
	chunk_list = []
	if Blockdata["myid"] == Blockdata["main_node"]:
		chunk_dict  = {}
		tlist = range(total_stack)
		write_text_file(tlist, os.path.join(Tracker["constants"]["masterdir"], "indexes.txt"))
		shuffle(tlist)
		chunk_one	= tlist[0:total_stack//2]
		chunk_two	= tlist[total_stack//2:]
		chunk_one	= sorted(chunk_one)
		chunk_two	= sorted(chunk_two)
		write_text_row(chunk_one,Tracker["constants"]["chunk_0"])
		write_text_row(chunk_two,Tracker["constants"]["chunk_1"])
		for particle in chunk_one: chunk_dict[particle] = 0
		for particle in chunk_two: chunk_dict[particle] = 1
		xform_proj_list = EMUtil.get_all_attributes(Tracker["constants"]["orgstack"], "xform.projection")
		for index_of_particle in xrange(len(xform_proj_list)):
			dp = xform_proj_list[index_of_particle].get_params("spider")
			xform_proj_list[index_of_particle] = [dp["phi"], dp["theta"], dp["psi"], -dp["tx"], -dp["ty"], chunk_dict[index_of_particle]]
		write_text_row(xform_proj_list, Tracker["constants"]["partstack"])
	else:
		chunk_one = 0
		chunk_two = 0
	chunk_one = wrap_mpi_bcast(chunk_one, Blockdata["main_node"])
	chunk_two = wrap_mpi_bcast(chunk_two, Blockdata["main_node"])
	for element in chunk_one: chunk_dict[element] = 0
	for element in chunk_two: chunk_dict[element] = 1
	chunk_list 				= [chunk_one, chunk_two]
	Tracker["chunk_dict"] 	= chunk_dict
	Tracker["P_chunk_0"]   	= len(chunk_one)/float(total_stack)
	Tracker["P_chunk_1"]   	= len(chunk_two)/float(total_stack)
	
	# Reconstruction to determine the resolution in orignal data size
	Tracker["nxinit"]     = Tracker["constants"]["nnxo"]
	Tracker["shrinkage"]  = float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
	Tracker["bckgnoise"]  =  None
	temp = model_blank(Tracker["constants"]["nnxo"], Tracker["constants"]["nnxo"])
	nny  =  temp.get_ysize()
	Blockdata["bckgnoise"] =  [1.0]*nny # set for initial recon3D of data from stack	
	Tracker["focus3D"]     =  None
	Tracker["fuse_freq"] = int(Tracker["constants"]["pixel_size"]*Tracker["constants"]["nnxo"]/Tracker["constants"]["fuse_freq"] +0.5)
	Tracker["directory"] = Tracker["constants"]["masterdir"]
	if Tracker["constants"]["nxinit"]< 0: Tracker["nxinit_refinement"] = Tracker["constants"]["nnxo"]
	else: Tracker["nxinit_refinement"] =  Tracker["constants"]["nxinit"]
	
	for procid in xrange(2):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		if Blockdata["myid"] == Blockdata["main_node"]: print(line, "Reconstruction of random subset %d"%procid)
		data = get_shrink_data_sorting(os.path.join(Tracker["constants"]["masterdir"],"chunk_%01d.txt"%procid), Tracker["constants"]["partstack"])
		mpi_barrier(MPI_COMM_WORLD)
		do3d_sorting(procid, data, myid = Blockdata["myid"],  mpi_comm = MPI_COMM_WORLD)# 1
	mpi_barrier(MPI_COMM_WORLD)
	
	if(Blockdata["no_of_groups"] == 1):
		if( Blockdata["myid"] == Blockdata["main_node"]):
			tvol0 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0.hdf"))
			tweight0 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0.hdf"))
			tvol1 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1.hdf"))
			tweight1 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1.hdf"))
			Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["fuse_freq"])
			shrank0 	= stepone(tvol0, tweight0)
			shrank1 	= stepone(tvol1, tweight1)
		    #  Note shrank volumes are Fourier uncentered.
			cfsc 		= fsc(shrank0, shrank1)[1]
			del shrank0, shrank1
			if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]): cfsc  = cfsc[:Tracker["nxinit"]]
			for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1): cfsc.append(0.0)
			write_text_row(cfsc, os.path.join(Tracker["directory"], "fsc_global.txt"))
			lcfsc  = len(cfsc)							
			fsc05  = 0
			fsc143 = 0 
			for ifreq in xrange(len(cfsc)):	
				if cfsc[ifreq] <0.5: break
			fsc05  = ifreq - 1
			for ifreq in xrange(len(cfsc)):
				if cfsc[ifreq]<0.143: break
			fsc143 = ifreq - 1
			Tracker["constants"]["fsc143"] = fsc143
			Tracker["constants"]["fsc05"]  = fsc05
		Tracker = wrap_mpi_bcast(Tracker,Blockdata["nodes"][0], communicator = MPI_COMM_WORLD)
	else:
		if(Blockdata["myid"] == Blockdata["nodes"][1]):  # It has to be 1 to avoid problem with tvol1 not closed on the disk
			tvol0 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0.hdf"))
			tweight0 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0.hdf"))
			tvol1 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1.hdf"))
			tweight1 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1.hdf"))
			Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["fuse_freq"])
			tag = 7007
			send_EMData(tvol1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
			send_EMData(tweight1, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
			shrank0 	= stepone(tvol0, tweight0)
			send_EMData(shrank0, Blockdata["nodes"][0], tag, MPI_COMM_WORLD)
			del shrank0
			lcfsc = 0
		
		elif( Blockdata["myid"] == Blockdata["nodes"][0]):
			tag = 7007
			tvol1 		= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
			tweight1 	= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
			tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
			shrank1 	= stepone(tvol1, tweight1)
			#  Get shrank volume, do fsc, send it to all
			shrank0 	= recv_EMData(Blockdata["nodes"][1], tag, MPI_COMM_WORLD)
			#  Note shrank volumes are Fourier uncentered.
			cfsc 		= fsc(shrank0, shrank1)[1]
			write_text_row(cfsc, os.path.join(Tracker["directory"], "fsc_global.txt"))
			del shrank0, shrank1
			if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]):
				cfsc  = cfsc[:Tracker["nxinit"]]
				for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1): cfsc.append(0.0)
			lcfsc  = len(cfsc)							
			fsc05  = 0
			fsc143 = 0 
			for ifreq in xrange(len(cfsc)):	
				if cfsc[ifreq] <0.5: break
			fsc05  = ifreq - 1
			for ifreq in xrange(len(cfsc)):
				if cfsc[ifreq]<0.143: break
			fsc143 = ifreq - 1
			Tracker["constants"]["fsc143"] = fsc143
			Tracker["constants"]["fsc05"]  = fsc05
		Tracker = wrap_mpi_bcast(Tracker, Blockdata["nodes"][0], communicator = MPI_COMM_WORLD)
	return import_from_data_stack
	
####	
def out_fsc(f):
	global Tracker, Blockdata
	print(" ")
	print("  driver FSC  after  iteration#%3d"%Tracker["mainiteration"])
	print("  %4d        %7.2f         %5.3f"%(0,1000.00,f[0]))
	for i in xrange(1,len(f)): print("  %4d        %7.2f         %5.3f"%(i,Tracker["constants"]["pixel_size"]*Tracker["constants"]["nnxo"]/float(i),f[i]))
	print(" ")
	
### functions for faked rec3d from subsets

def compute_sigma(projdata, params, first_procid, dryrun = False, myid = -1, mpi_comm = -1):
	global Tracker, Blockdata
	# Input stack of particles with all params in header
	# Output: 1/sigma^2 and a dictionary
	#  It could be a parameter
	if( mpi_comm < 0 ): mpi_comm = MPI_COMM_WORLD
	npad = 1
	if  dryrun:
		#tsd = model_blank(nv + nv//2,len(sd), 1, 1.0)
		#tocp = model_blank(len(sd), 1, 1, 1.0)
		if( myid == Blockdata["main_node"] ):
			tsd = get_im(os.path.join(Tracker["previousoutputdir"],"bckgnoise.hdf"))
			tsd.write_image(os.path.join(Tracker["directory"],"bckgnoise.hdf"))
			nnx = tsd.get_xsize()
			nny = tsd.get_ysize()
		else:
			nnx = 0
			nny = 0
		nnx = bcast_number_to_all(nnx, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)
		nny = bcast_number_to_all(nny, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)
		if( myid != Blockdata["main_node"] ): tsd = model_blank(nnx,nny, 1, 1.0)
		bcast_EMData_to_all(tsd, myid, source_node = Blockdata["main_node"], comm = mpi_comm)
	else:
		if( myid == Blockdata["main_node"] ): ngroups = len(read_text_file(os.path.join(Tracker["constants"]["masterdir"],"main000", "groupids.txt")))
		else: ngroups = 0
		ngroups = bcast_number_to_all(ngroups, source_node = Blockdata["main_node"], mpi_comm = mpi_comm)
		ndata = len(projdata)
		nx = Tracker["constants"]["nnxo"]
		mx = npad*nx
		nv = mx//2+1
		"""
		#  Inverted Gaussian mask
		invg = model_gauss(Tracker["constants"]["radius"],nx,nx)
		invg /= invg[nx//2,nx//2]
		invg = model_blank(nx,nx,1,1.0) - invg
		"""

		mask = model_circle(Tracker["constants"]["radius"],nx,nx)
		tsd = model_blank(nv + nv//2, ngroups)

		#projdata, params = getalldata(partstack, params, myid, Blockdata["nproc"])
		'''
		if(myid == 0):  ndata = EMUtil.get_image_count(partstack)
		else:           ndata = 0
		ndata = bcast_number_to_all(ndata)
		if( ndata < Blockdata["nproc"]):
			if(myid<ndata):
				image_start = myid
				image_end   = myid+1
			else:
				image_start = 0
				image_end   = 1
		else:
			image_start, image_end = MPI_start_end(ndata, Blockdata["nproc"], myid)
		#data = EMData.read_images(stack, range(image_start, image_end))
		if(myid == 0):
			params = read_text_row( paramsname )
			params = [params[i][j]  for i in xrange(len(params))   for j in xrange(5)]
		else:           params = [0.0]*(5*ndata)
		params = bcast_list_to_all(params, myid, source_node=Blockdata["main_node"])
		params = [[params[i*5+j] for j in xrange(5)] for i in xrange(ndata)]
		'''
		if(Blockdata["accumulatepw"] == None):
			Blockdata["accumulatepw"] = [[],[]]
			doac = True
		else:  doac = False
		tocp = model_blank(ngroups)
		tavg = model_blank(nx,nx)
		for i in xrange(ndata):  # apply_shift; info_mask; norm consistent with get_shrink_data
			indx = projdata[i].get_attr("particle_group")
			phi,theta,psi,sx,sy = params[i][0],params[i][1],params[i][2],params[i][3],params[i][4]
			stmp = cyclic_shift( projdata[i], int(round(sx)), int(round(sy)))
			st = Util.infomask(stmp, mask, False)
			stmp -=st[0]
			stmp /=st[1]
			temp = cosinemask(stmp, radius = Tracker["constants"]["radius"], s = 0.0)
			Util.add_img(tavg, temp)
			sig = Util.rotavg_fourier( temp )
			#sig = rops(pad(((cyclic_shift( projdata[i], int(sx), int(round(sy)) ) - st[0])/st[1]), mx,mx,1,0.0))
			#sig = rops(pad(((cyclic_shift(projdata, int(round(params[i][-2])), int(round(params[i][-1])) ) - st[0])/st[1])*invg, mx,mx,1,0.0))
			for k in xrange(nv):tsd.set_value_at(k,indx,tsd.get_value_at(k,indx)+sig[k])
			tocp[indx] += 1
		####for lll in xrange(len(Blockdata["accumulatepw"])):  print(myid,ndata,lll,len(Blockdata["accumulatepw"][lll]))
		reduce_EMData_to_root(tsd,  myid, Blockdata["main_node"],  mpi_comm)
		reduce_EMData_to_root(tocp, myid, Blockdata["main_node"], mpi_comm)
		reduce_EMData_to_root(tavg, myid, Blockdata["main_node"], mpi_comm)
		if( myid == Blockdata["main_node"]):
			Util.mul_scalar(tavg, 1.0/float(sum(Tracker["nima_per_chunk"])))
			sig = Util.rotavg_fourier( tavg )
			#for k in xrange(1,nv):  print("  BACKG  ",k,tsd.get_value_at(k,0)/tocp[0] ,sig[k],tsd.get_value_at(k,0)/tocp[0] - sig[k])
			tmp1 = [0.0]*nv
			tmp2 = [0.0]*nv
			for i in xrange(ngroups):
				for k in xrange(1,nv):
					qt = tsd.get_value_at(k,i)/tocp[i] - sig[k]
					if( qt > 0.0 ):	tmp1[k] = 2.0/qt
				#smooth
				tmp1[0] = tmp1[1]
				tmp1[-1] = tmp1[-2]
				for ism in xrange(0):  #2
					for k in xrange(1,nv-1):  tmp2[k] = (tmp1[k-1]+tmp1[k]+tmp1[k+1])/3.0
					for k in xrange(1,nv-1):  tmp1[k] = tmp2[k]
				#  We will keep 0-element the same as first tsd.set_value_at(0,i,1.0)
				for k in xrange(1,nv):tsd.set_value_at(k,i,tmp1[k])
				tsd.set_value_at(0,i,1.0)
			tsd.write_image(os.path.join(Tracker["directory"],"bckgnoise.hdf"))
		bcast_EMData_to_all(tsd, myid, source_node = 0, comm = mpi_comm)
	nnx = tsd.get_xsize()
	nny = tsd.get_ysize()
	Blockdata["bckgnoise"] = []
	for i in xrange(nny):
		prj = model_blank(nnx)
		for k in xrange(nnx): prj[k] = tsd.get_value_at(k,i)
		Blockdata["bckgnoise"].append(prj)  #  1.0/sigma^2
	return
###
def do3d(procid, data, newparams, refang, rshifts, norm_per_particle, myid, mpi_comm = -1):
	global Tracker, Blockdata
	#  Without filtration
	from reconstruction import recons3d_trl_struct_MPI
	if( mpi_comm < -1 ): mpi_comm = MPI_COMM_WORDLD
	if Blockdata["subgroup_myid"]== Blockdata["main_node"]:
		if( procid == 0 ):
			if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	shrinkage = float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
	tvol, tweight, trol = recons3d_trl_struct_MPI(myid = Blockdata["subgroup_myid"], main_node = Blockdata["main_node"], prjlist = data, \
											paramstructure = newparams, refang = refang, rshifts_shrank = [[q[0]*shrinkage,q[1]*shrinkage] for q in rshifts], \
											delta = Tracker["delta"], CTF = Tracker["constants"]["CTF"], upweighted = False, mpi_comm = mpi_comm, \
											target_size = (2*Tracker["nxinit"]+3), avgnorm = Tracker["avgvaradj"][procid], norm_per_particle = norm_per_particle)
	if Blockdata["subgroup_myid"] == Blockdata["main_node"]:
		tvol.set_attr("is_complex",0)
		tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
		tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
		trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%01d_%03d.hdf"%(procid,Tracker["mainiteration"])))
	mpi_barrier(mpi_comm)
	return
##
def getindexdata(partids, partstack, particle_groups, original_data = None, small_memory= True, nproc =-1, myid = -1, mpi_comm = -1):
	global Tracker, Blockdata
	# The function will read from stack a subset of images specified in partids
	#   and assign to them parameters from partstack
	# So, the lengths of partids and partstack are the same.
	#  The read data is properly distributed among MPI threads.
	if( mpi_comm < 0 ):  mpi_comm = MPI_COMM_WORLD
	from applications import MPI_start_end
	#  parameters
	if( myid == 0 ):  partstack = read_text_row(partstack)
	else:  			  partstack = 0
	partstack = wrap_mpi_bcast(partstack, 0, mpi_comm)
	#  particles IDs
	if( myid == 0 ):  partids = read_text_file(partids)
	else:          	  partids = 0
	partids = wrap_mpi_bcast(partids, 0, mpi_comm)
	#  Group assignments
	if( myid == 0 ):	group_reference = read_text_file(particle_groups)
	else:          		group_reference = 0
	group_reference = wrap_mpi_bcast(group_reference, 0, mpi_comm)

	im_start, im_end = MPI_start_end(len(partstack), nproc, myid)
	partstack = partstack[im_start:im_end]
	partids   = partids[im_start:im_end]
	group_reference = group_reference[im_start:im_end]
	'''
	particles_on_node = []
	parms_on_node     = []
	for i in xrange( group_start, group_end ):
		particles_on_node += lpartids[group_reference[i][2]:group_reference[i][3]+1]  #  +1 is on account of python idiosyncrasies
		parms_on_node     += partstack[group_reference[i][2]:group_reference[i][3]+1]


	Blockdata["nima_per_cpu"][procid] = len(particles_on_node)
	#ZZprint("groups_on_thread  ",Blockdata["myid"],procid, Tracker["groups_on_thread"][procid])
	#ZZprint("  particles  ",Blockdata["myid"],Blockdata["nima_per_cpu"][procid],len(parms_on_node))
	'''
	"""
            17            28            57            84    5
            18            14            85            98    6
            19            15            99           113    7
            25            20           114           133    8
            29             9           134           142    9

	"""
	#print("getindexdata", Tracker["constants"]["orgstack"])
	#print(len(partids), Blockdata["myid"])
	if( original_data == None or small_memory):
		original_data = EMData.read_images(Tracker["constants"]["orgstack"], partids)
		for im in xrange( len(original_data) ): 
			original_data[im].set_attr("particle_group", group_reference[im])
	return original_data, partstack
#######
def do3d_sorting_groups_rec3d(iteration, masterdir, log_main):
	global Tracker, Blockdata
	from utilities import get_im
	# reconstruct final unfiltered volumes from sorted clusters
	keepgoing = 1
	#if(Blockdata["myid"] == Blockdata["nodes"][0]):
	#	cmd = "{} {}".format("mkdir", os.path.join(Tracker["directory"], "tempdir"))
	#	if os.path.exists(os.path.join(Tracker["directory"], "tempdir")): print("tempdir exists")
	#	else:                                                             cmdexecute(cmd)
	### ====	
	fsc143                          =   0
	fsc05                           =   0
	Tracker["fsc143"]				=	0
	Tracker["fsc05"]				=	0
	res_05 						    =	Tracker["number_of_groups"]*[0]
	res_143 					    =	Tracker["number_of_groups"]*[0]
	Tracker["directory"]            =   masterdir
	Tracker["constants"]["masterdir"] = masterdir
	Tracker["maxfrad"] = Tracker["nxinit"]//2
	####
	if Blockdata["no_of_groups"]>1:
		sub_main_node_list = [-1 for i in xrange(Blockdata["no_of_groups"])]
		for index_of_colors in xrange(Blockdata["no_of_groups"]):
			for iproc in xrange(Blockdata["nproc"]-1):
				if Blockdata["myid"]== iproc:
					if Blockdata["color"] == index_of_colors and Blockdata["myid_on_node"] == 0:
						sub_main_node_list[index_of_colors] = Blockdata["myid"]
					wrap_mpi_send(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
				if Blockdata["myid"] == Blockdata["last_node"]:
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for im in xrange(len(dummy)):
						if dummy[im]>-1: sub_main_node_list[im] = dummy[im]
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		wrap_mpi_bcast(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
		#if Blockdata["myid"] == Blockdata["last_node"]:
		#	print("MMM", sub_main_node_list)
		####		
		if Tracker["number_of_groups"]%Blockdata["no_of_groups"]== 0: 
			nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]
		else: nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]+1
	
		big_loop_colors = [[] for i in xrange(nbig_loop)]
		big_loop_groups = [[] for i in xrange(nbig_loop)]
		nc = 0
		while nc <Tracker["number_of_groups"]:
			im =  nc//Blockdata["no_of_groups"]
			jm =  nc%Blockdata["no_of_groups"]
			big_loop_colors[im].append(jm)
			big_loop_groups[im].append(nc)
			nc +=1
		#if Blockdata["myid"] == Blockdata["last_node"]:
		#	print(big_loop_groups, big_loop_colors)
		#####
		for iloop in xrange(nbig_loop):
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				Clusterdir = os.path.join(Tracker["directory"], "Cluster%d"%index_of_group, "main%03d"%iteration)
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2 		= get_im(os.path.join(Clusterdir, "tempdir", "tvol_0_%03d.hdf"%iteration))
					tweight2 	= get_im(os.path.join(Clusterdir, "tempdir", "tweight_0_%03d.hdf"%iteration))
					treg2 		= get_im(os.path.join(Clusterdir, "tempdir", "trol_0_%03d.hdf"%iteration))
					tag      = 7007
					send_EMData(tvol2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(tweight2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(treg2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
				elif (Blockdata["myid"] == sub_main_node_list[index_of_colors]):
					tag      = 7007
					tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if Blockdata["color"] == index_of_colors:
					if( Blockdata["myid_on_node"] != 0):
						tvol2 		= model_blank(1)
						tweight2 	= model_blank(1)
						treg2		= model_blank(1)
					tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = index_of_colors) # has to be False!!!
					del tweight2, treg2
				mpi_barrier(Blockdata["shared_comm"])
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if (Blockdata["color"] == index_of_colors) and (Blockdata["myid_on_node"] == 0):
					tag = 7007
					send_EMData(tvol2, Blockdata["last_node"], tag, MPI_COMM_WORLD)
				elif(Blockdata["myid"] == Blockdata["last_node"]):
					tag = 7007
					tvol2 = recv_EMData(sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_0_grp%03d.hdf"%index_of_group))
					del tvol2
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				Clusterdir = os.path.join(Tracker["directory"], "Cluster%d"%index_of_group, "main%03d"%iteration)
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2 		= get_im(os.path.join(Clusterdir, "tempdir", "tvol_1_%03d.hdf"%iteration))
					tweight2 	= get_im(os.path.join(Clusterdir, "tempdir", "tweight_1_%03d.hdf"%iteration))
					treg2 		= get_im(os.path.join(Clusterdir, "tempdir", "trol_1_%03d.hdf"%iteration))
					tag      = 7007
					send_EMData(tvol2,    sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(tweight2, sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
					send_EMData(treg2,    sub_main_node_list[index_of_colors], tag,MPI_COMM_WORLD)
				
				elif (Blockdata["myid"] == sub_main_node_list[index_of_colors]):
					tag      = 7007
					tvol2       = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2       = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				Tracker["maxfrad"] = Tracker["nxinit"]//2
				if Blockdata["color"] == index_of_colors:
					if( Blockdata["myid_on_node"] != 0):
						tvol2 		= model_blank(1)
						tweight2 	= model_blank(1)
						treg2		= model_blank(1)
					tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = index_of_colors) # has to be False!!!
					del tweight2, treg2
				mpi_barrier(Blockdata["shared_comm"])
			mpi_barrier(MPI_COMM_WORLD)
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if (Blockdata["color"] == index_of_colors) and (Blockdata["myid_on_node"] == 0):
					tag = 7007
					send_EMData(tvol2, Blockdata["last_node"], tag, MPI_COMM_WORLD)
				elif(Blockdata["myid"] == Blockdata["last_node"]):
					tag = 7007
					tvol2 = recv_EMData(sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_1_grp%03d.hdf"%index_of_group))
					del tvol2
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
	else:
		Tracker["maxfrad"] = Tracker["nxinit"]//2
		for index_of_group in xrange(Tracker["number_of_groups"]):
			Clusterdir = os.path.join(Tracker["directory"], "Cluster%d"%index_of_group, "main%03d"%iteration)
			
			if(Blockdata["myid"] == Blockdata["last_node"]):
				tvol2 		= get_im(os.path.join(Clusterdir, "tempdir", "tvol_0_%03d.hdf"%iteration))
				tweight2 	= get_im(os.path.join(Clusterdir, "tempdir", "tweight_0_%03d.hdf"%iteration))
				treg2 		= get_im(os.path.join(Clusterdir, "tempdir", "trol_0_%03d.hdf"%iteration))
				tag      = 7007
				send_EMData(tvol2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
				send_EMData(tweight2, Blockdata["main_node"], tag, MPI_COMM_WORLD)
				send_EMData(treg2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
			elif (Blockdata["myid"] == Blockdata["main_node"]):
				tag      = 7007
				tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
			if Blockdata["myid"] != Blockdata["main_node"]:
				tvol2 		= model_blank(1)
				tweight2 	= model_blank(1)
				treg2		= model_blank(1)
			tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = 0) # has to be False!!!
			del tweight2, treg2
			if( Blockdata["myid"] == Blockdata["main_node"]):
				tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_0_grp%03d.hdf"%index_of_group))
			mpi_barrier(MPI_COMM_WORLD)
			
			if(Blockdata["myid"] == Blockdata["last_node"]):
				tvol2 		= get_im(os.path.join(Clusterdir, "tempdir", "tvol_1_%03d.hdf"%iteration))
				tweight2 	= get_im(os.path.join(Clusterdir, "tempdir", "tweight_1_%03d.hdf"%iteration))
				treg2 		= get_im(os.path.join(Clusterdir, "tempdir", "trol_1_%03d.hdf"%iteration))
				tag      = 7007
				send_EMData(tvol2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
				send_EMData(tweight2, Blockdata["main_node"], tag, MPI_COMM_WORLD)
				send_EMData(treg2, Blockdata["main_node"],    tag, MPI_COMM_WORLD)
			elif (Blockdata["myid"] == Blockdata["main_node"]):
				tag      = 7007
				tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
			if Blockdata["myid"] != Blockdata["main_node"]:
				tvol2 		= model_blank(1)
				tweight2 	= model_blank(1)
				treg2		= model_blank(1)
			tvol2 = steptwo_mpi(tvol2, tweight2, treg2, None, False, color = 0) # has to be False!!!
			del tweight2, treg2
			if( Blockdata["myid"] == Blockdata["main_node"]):
				tvol2.write_image(os.path.join(Tracker["directory"], "vol_unfiltered_1_grp%03d.hdf"%index_of_group))
			mpi_barrier(MPI_COMM_WORLD)
			
	keepgoing = bcast_number_to_all(keepgoing, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD) # always check 
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
	if keepgoing == 0: ERROR("do3d_sorting_groups_trl_iter  %s"%os.path.join(Tracker["directory"], "tempdir"),"do3d_sorting_groups_trl_iter", 1, Blockdata["myid"]) 
	return
####<<<--------
### nofsc rec3d
def do3d_sorting_groups_nofsc_smearing_iter(srdata, partial_rec3d, iteration):
	global Tracker, Blockdata
	keepgoing = 1
	if(Blockdata["myid"] == Blockdata["last_node"]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")):os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
		try:
			fout = open(os.path.join(Tracker["directory"],"freq_cutoff.json"),'r')
			freq_cutoff_dict = convert_json_fromunicode(json.load(fout))
			fout.close()
		except: freq_cutoff_dict = 0
	else: freq_cutoff_dict = 0
	freq_cutoff_dict = wrap_mpi_bcast(freq_cutoff_dict, Blockdata["last_node"], MPI_COMM_WORLD)
		
	for index_of_groups in xrange(Tracker["number_of_groups"]):
		if partial_rec3d:
			tvol, tweight, trol = recons3d_trl_struct_group_nofsc_shifted_data_partial_MPI(Blockdata["myid"], Blockdata["last_node"], Blockdata["nproc"], srdata, index_of_groups, \
			os.path.join(Tracker["directory"], "tempdir", "trol_2_%d.hdf"%index_of_groups), \
			os.path.join(Tracker["directory"], "tempdir", "tvol_2_%d.hdf"%index_of_groups), \
			os.path.join(Tracker["directory"], "tempdir", "tweight_2_%d.hdf"%index_of_groups),\
      		None,  Tracker["constants"]["CTF"], (2*Tracker["nxinit"]+3), Tracker["nosmearing"])
		else:
			tvol, tweight, trol = recons3d_trl_struct_group_nofsc_shifted_data_MPI(Blockdata["myid"], Blockdata["last_node"], srdata,\
			     index_of_groups, None,  Tracker["constants"]["CTF"], (2*Tracker["nxinit"]+3), Tracker["nosmearing"])
			     
		if(Blockdata["myid"] == Blockdata["last_node"]):
			tvol.set_attr("is_complex",0)
			tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_2_%d.hdf"%index_of_groups))
			tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_2_%d.hdf"%index_of_groups))
			trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_2_%d.hdf"%index_of_groups))
			del tvol
			del tweight
			del trol
	mpi_barrier(MPI_COMM_WORLD)
	#fsc143            = 0
	#fsc05             = 0
	Tracker["fsc143"] = 0
	Tracker["fsc05"]  = 0
	Tracker["maxfrad"]= Tracker["nxinit"]//2
	if Blockdata["no_of_groups"]>1:
	 	# new starts
		sub_main_node_list = [ -1 for i in xrange(Blockdata["no_of_groups"])]
		for index_of_colors in xrange(Blockdata["no_of_groups"]):
			for iproc in xrange(Blockdata["nproc"]-1):
				if Blockdata["myid"]== iproc:
					if Blockdata["color"] == index_of_colors and Blockdata["myid_on_node"] == 0:
						sub_main_node_list[index_of_colors] = Blockdata["myid"]
					wrap_mpi_send(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
				if Blockdata["myid"] == Blockdata["last_node"]:
					dummy = wrap_mpi_recv(iproc, MPI_COMM_WORLD)
					for im in xrange(len(dummy)):
						if dummy[im]>-1: sub_main_node_list[im] = dummy[im]
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		wrap_mpi_bcast(sub_main_node_list, Blockdata["last_node"], MPI_COMM_WORLD)
		#if Blockdata["myid"] == Blockdata["last_node"]:print("MMM", sub_main_node_list)
		####		
		if Tracker["number_of_groups"]%Blockdata["no_of_groups"]== 0: 
			nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]
		else: nbig_loop = Tracker["number_of_groups"]//Blockdata["no_of_groups"]+1
	
		big_loop_colors = [[] for i in xrange(nbig_loop)]
		big_loop_groups = [[] for i in xrange(nbig_loop)]
		nc = 0
		while nc <Tracker["number_of_groups"]:
			im =  nc//Blockdata["no_of_groups"]
			jm =  nc%Blockdata["no_of_groups"]
			big_loop_colors[im].append(jm)
			big_loop_groups[im].append(nc)
			nc +=1
		#if Blockdata["myid"] == Blockdata["last_node"]:
		#	print(big_loop_groups, big_loop_colors)
		for iloop in xrange(nbig_loop):
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
			
				if(Blockdata["myid"] == Blockdata["last_node"]):
					tvol2    = get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_2_%d.hdf")%index_of_group)
					tweight2 = get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_2_%d.hdf")%index_of_group)
					treg2 	 = get_im(os.path.join(Tracker["directory"], "tempdir", "trol_2_%d.hdf"%index_of_group))
					tvol2.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1})
					tag = 7007
					send_EMData(tvol2,    sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					send_EMData(tweight2, sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					send_EMData(treg2,    sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
				
				elif (Blockdata["myid"] == sub_main_node_list[index_of_colors]):
					tag      = 7007
					tvol2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					tweight2 = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
					treg2    = recv_EMData(Blockdata["last_node"], tag, MPI_COMM_WORLD)
				mpi_barrier(MPI_COMM_WORLD)
			mpi_barrier(MPI_COMM_WORLD)
			
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				try: 
					Tracker["freq_fsc143_cutoff"] = freq_cutoff_dict["Cluster_%03d.txt"%index_of_group]
				except: pass	
				if Blockdata["color"] == index_of_colors:  # It has to be 1 to avoid problem with tvol1 not closed on the disk 							
					if(Blockdata["myid_on_node"] != 0): 
						tvol2     = model_blank(1)
						tweight2  = model_blank(1)
						treg2     = model_blank(1)
					tvol2 = steptwo_mpi_filter(tvol2, tweight2, treg2,  None,  Tracker["freq_fsc143_cutoff"], 0.01, False, color = index_of_colors) # has to be False!!!
					del tweight2, treg2
			mpi_barrier(MPI_COMM_WORLD)
		
			for im in xrange(len(big_loop_colors[iloop])):
				index_of_group  = big_loop_groups[iloop][im]
				index_of_colors = big_loop_colors[iloop][im]
				if (Blockdata["color"] == index_of_colors) and (Blockdata["myid_on_node"] == 0):
					tag = 7007
					send_EMData(tvol2, Blockdata["last_node"], tag, MPI_COMM_WORLD)
				elif(Blockdata["myid"] == Blockdata["last_node"]):
					tag = 7007
					tvol2    = recv_EMData(sub_main_node_list[index_of_colors], tag, MPI_COMM_WORLD)
					tvol2.write_image(os.path.join(Tracker["directory"], "vol_grp%03d_iter%03d.hdf"%(index_of_group,iteration)))
					del tvol2
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		
	else:# loop over all groups for single node
		for index_of_group in xrange(Tracker["number_of_groups"]):
			if(Blockdata["myid_on_node"] == 0):
				tvol2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_2_%d.hdf")%index_of_group)
				tweight2 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_2_%d.hdf")%index_of_group)
				treg2 		= get_im(os.path.join(Tracker["directory"], "tempdir", "trol_2_%d.hdf"%index_of_group))
				tvol2.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1})
			else:
				tvol2 		= model_blank(1)
				tweight2 	= model_blank(1)
				treg2		= model_blank(1)
			try: 
				Tracker["freq_fsc143_cutoff"] = freq_cutoff_dict["Cluster_%03d.txt"%index_of_group]
			except: pass
			tvol2 = steptwo_mpi_filter(tvol2, tweight2, treg2, None, Tracker["freq_fsc143_cutoff"], 0.01, False) # has to be False!!!
			del tweight2, treg2
			if(Blockdata["myid_on_node"] == 0):
				tvol2.write_image(os.path.join(Tracker["directory"], "vol_grp%03d_iter%03d.hdf"%(index_of_group,iteration)))
				del tvol2
			mpi_barrier(MPI_COMM_WORLD)
	mpi_barrier(MPI_COMM_WORLD)
	keepgoing = bcast_number_to_all(keepgoing, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD) # always check 
	Tracker   = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
	if not keepgoing: ERROR("do3d_sorting_groups_trl_iter  %s"%os.path.join(Tracker["directory"], "tempdir"),"do3d_sorting_groups_trl_iter", 1, Blockdata["myid"])
	return
### nofsc insertion #1
def recons3d_trl_struct_group_nofsc_shifted_data_partial_MPI(myid, main_node, nproc, prjlist, group_ID, refvol_file, fftvol_file, weight_file, mpi_comm= None, CTF = True, target_size=-1, nosmearing = False):
	"""
		partial rec3d for re-assigned particles
		reconstructor nn4_ctfws
	"""
	from utilities    import reduce_EMData_to_root, random_string, get_im, findall, info, model_blank
	from EMAN2        import Reconstructors
	from filter	      import filt_table
	from fundamentals import fshift
	from mpi          import MPI_COMM_WORLD, mpi_barrier
	import types
	import datetime
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	if CTF: do_ctf = 1
	else:   do_ctf = 0
	if not os.path.exists(refvol_file):ERROR("refvol does not exist", "recons3d_trl_struct_group_nofsc_shifted_data_partial_MPI", 1, myid)
	if not os.path.exists(fftvol_file):ERROR("fftvol does not exist", "recons3d_trl_struct_group_nofsc_shifted_data_partial_MPI", 1, myid)
	if not os.path.exists(weight_file):ERROR("weight does not exist", "recons3d_trl_struct_group_nofsc_shifted_data_partial_MPI", 1, myid)
	
	#refvol
	if myid == main_node: target_size = get_im(refvol_file).get_xsize()
	else: target_size = 0
	target_size = bcast_number_to_all(target_size, main_node, mpi_comm)
	refvol = model_blank(target_size)# set to zero
	
	# fftvol
	if (myid == main_node): 
		fftvol = get_im(fftvol_file)
		fftvol.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
		fftvol /=float(nproc)
		#Util.mult_scalar(fftvol, 1./float(Blockdata["nproc"]))
		nxfft  =fftvol.get_xsize()
		nyfft  =fftvol.get_ysize()
		nzfft  =fftvol.get_zsize()
	else: 
		nxfft = 0
		nyfft = 0
		nzfft = 0
	nxfft = bcast_number_to_all(nxfft, main_node, mpi_comm)
	nyfft = bcast_number_to_all(nyfft, main_node, mpi_comm)
	nzfft = bcast_number_to_all(nzfft, main_node, mpi_comm)
	if (myid!= main_node): fftvol = model_blank(nxfft, nyfft, nzfft)
	bcast_EMData_to_all(fftvol, myid, main_node)
	
	# weight
	if (myid == main_node): 
		weight = get_im(weight_file)
		weight /=float(nproc)
		#Util.mult_scalar(weight, 1./float(Blockdata["nproc"]))
		nxweight  = weight.get_xsize()
		nyweight  = weight.get_ysize()
		nzweight  = weight.get_zsize()
	else: 
		nxweight = 0
		nyweight = 0
		nzweight = 0
	nxweight = bcast_number_to_all(nxweight, main_node, mpi_comm)
	nyweight = bcast_number_to_all(nyweight, main_node, mpi_comm)
	nzweight = bcast_number_to_all(nzweight, main_node, mpi_comm)
	if(myid != main_node): weight = model_blank(nxweight, nyweight, nzweight)
	bcast_EMData_to_all(weight, myid, main_node)
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r = Reconstructors.get("nn4_ctfws", params)
	r.setup()
	if nosmearing:
		nnx = prjlist[0].get_xsize()
		nny = prjlist[0].get_ysize()
	else:
		nnx = prjlist[0][0].get_xsize()
		nny = prjlist[0][0].get_ysize()
	for im in xrange(len(prjlist)):
		if nosmearing:
			current_group_ID  = prjlist[im].get_attr("group")
			previous_group_ID = prjlist[im].get_attr("previous_group")
			if current_group_ID !=previous_group_ID:
				if current_group_ID == group_ID:
					flag = 1.0
					[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im], xform = "xform.projection")
					r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), flag)
				if previous_group_ID == group_ID: 
					flag = -1.0
					[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im], xform = "xform.projection")
					r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), flag)
		else:
			current_group_ID  = prjlist[im][0].get_attr("group")
			previous_group_ID = prjlist[im][0].get_attr("previous_group")
			if current_group_ID !=previous_group_ID:
				if current_group_ID == group_ID:
					flag = 1.0
					for jm in xrange(len(prjlist[im])):
						[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im][jm], xform = "xform.projection")
						r.insert_slice(prjlist[im][jm], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), prjlist[im][jm].get_attr("wprob")*flag)
				if previous_group_ID == group_ID: 
					flag =-1.0
					for jm in xrange(len(prjlist[im])):
						[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im][jm], xform = "xform.projection")
						r.insert_slice(prjlist[im][jm], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), prjlist[im][jm].get_attr("wprob")*flag)
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if myid == main_node:dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else:
		del fftvol
		del weight
		del refvol 
		return None, None, None
### insertion 2
def recons3d_trl_struct_group_nofsc_shifted_data_MPI(myid, main_node, prjlist, group_ID, mpi_comm= None, CTF = True, target_size=-1, nosmearing = False):
	"""
	  rec3d for pre-shifted data list
	  reconstructor nn4_ctfw
	"""
	from utilities    import reduce_EMData_to_root, random_string, get_im, findall, info, model_blank
	from EMAN2        import Reconstructors
	from filter	      import filt_table
	from fundamentals import fshift
	from mpi          import MPI_COMM_WORLD, mpi_barrier
	import types
	import datetime
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	refvol = model_blank(target_size)
	refvol.set_attr("fudge", 1.0)
	if CTF: do_ctf = 1
	else:   do_ctf = 0
	fftvol = EMData()
	weight = EMData()
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r = Reconstructors.get( "nn4_ctfw", params)
	r.setup()
	if nosmearing:
		nnx = prjlist[0].get_xsize()
		nny = prjlist[0].get_ysize()
	else:
		nnx = prjlist[0][0].get_xsize()
		nny = prjlist[0][0].get_ysize()
	for im in xrange(len(prjlist)):
		if nosmearing: 
			if prjlist[im].get_attr("group") == group_ID:
				[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im], xform = "xform.projection")
				r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)
		else: 
			if prjlist[im][0].get_attr("group") == group_ID:
				for jm in xrange(len(prjlist[im])):
					[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im][jm], xform = "xform.projection")
					r.insert_slice(prjlist[im][jm], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), prjlist[im][jm].get_attr("wprob"))
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if myid == main_node:dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else:
		del fftvol
		del weight
		del refvol 
		return None, None, None
###end of nofsc
def recons3d_trl_struct_group_MPI(myid, main_node, prjlist, random_subset, group_ID, paramstructure, norm_per_particle = None, \
      upweighted = True, mpi_comm= None, CTF = True, target_size=-1, nosmearing = False):
	"""
		recons3d_4nn_ctf - calculate CTF-corrected 3-D reconstruction from a set of projections using three Eulerian angles, two shifts, and CTF settings for each projeciton image
		Input
			list_of_prjlist: list of lists of projections to be included in the reconstruction
	"""
	global Tracker, Blockdata
	from utilities    import reduce_EMData_to_root, random_string, get_im, findall, model_blank, info
	from EMAN2        import Reconstructors
	from filter	      import filt_table
	from fundamentals import fshift
	from mpi          import MPI_COMM_WORLD, mpi_barrier
	import types
	import datetime
	import copy
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	
	refvol = model_blank(target_size)
	refvol.set_attr("fudge", 1.0)
	if CTF: do_ctf = 1
	else:   do_ctf = 0
	fftvol = EMData()
	weight = EMData()
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r = Reconstructors.get( "nn4_ctfw", params )
	r.setup()
	if norm_per_particle == None: norm_per_particle = len(prjlist)*[1.0]
	if not nosmearing:
		delta  = Tracker["delta"]
		refang = Tracker["refang"]
		rshifts_shrank = copy.deepcopy(Tracker["rshifts"])
		nshifts = len(rshifts_shrank)
		for im in xrange(len(rshifts_shrank)):
			rshifts_shrank[im][0] *= float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
			rshifts_shrank[im][1] *= float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
	nnx = prjlist[0].get_xsize()
	nny = prjlist[0].get_ysize()
	for im in xrange(len(prjlist)):
		if not nosmearing: avgnorm = Tracker["avgnorm"][prjlist[im].get_attr("chunk_id")]
		#  parse projection structure, generate three lists:
		#  [ipsi+iang], [ishift], [probability]
		#  Number of orientations for a given image
		if prjlist[im].get_attr("group") == group_ID:
			if random_subset == 2:
				if nosmearing:
					bckgn = prjlist[im].get_attr("bckgnoise")
					ct = prjlist[im].get_attr("ctf")
					prjlist[im].set_attr_dict( {"bckgnoise":bckgn, "ctf":ct} )
					[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im], xform = "xform.projection")
					r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)
				else:
					if Tracker["constants"]["nsmear"]<=0.0: numbor = len(paramstructure[im][2])
					else:   numbor = 1
					ipsiandiang = [ paramstructure[im][2][i][0]/1000  for i in xrange(numbor) ]
					allshifts   = [ paramstructure[im][2][i][0]%1000  for i in xrange(numbor) ]
					probs       = [ paramstructure[im][2][i][1] for i in xrange(numbor) ]
					#  Find unique projection directions
					tdir = list(set(ipsiandiang))
					bckgn = prjlist[im].get_attr("bckgnoise")
					ct = prjlist[im].get_attr("ctf")
					#  For each unique projection direction:
					data = [None]*nshifts
					for ii in xrange(len(tdir)):
						#  Find the number of times given projection direction appears on the list, it is the number of different shifts associated with it.
						lshifts = findall(tdir[ii], ipsiandiang)
						toprab  = 0.0
						for ki in xrange(len(lshifts)):  toprab += probs[lshifts[ki]]
						recdata = EMData(nny,nny,1,False)
						recdata.set_attr("is_complex",0)
						for ki in xrange(len(lshifts)):
							lpt = allshifts[lshifts[ki]]
							if( data[lpt] == None ):
								data[lpt] = fshift(prjlist[im], rshifts_shrank[lpt][0], rshifts_shrank[lpt][1])
								data[lpt].set_attr("is_complex",0)
							Util.add_img(recdata, Util.mult_scalar(data[lpt], probs[lshifts[ki]]/toprab))
						recdata.set_attr_dict({"padffted":1, "is_fftpad":1,"is_fftodd":0, "is_complex_ri":1, "is_complex":1})
						if not upweighted:  recdata = filt_table(recdata, bckgn )
						recdata.set_attr_dict( {"bckgnoise":bckgn, "ctf":ct} )
						ipsi = tdir[ii]%100000
						iang = tdir[ii]/100000
						#for iloop in xrange(10000000):
						#if iloop%1000==0:memory_check("before slice %d  myid  %d"%(iloop, Blockdata["myid"]))
						r.insert_slice( recdata, Transform({"type":"spider","phi":refang[iang][0],"theta":refang[iang][1],"psi":refang[iang][2]+ipsi*delta}), toprab*avgnorm/norm_per_particle[im])
						#if iloop%1000==0:memory_check("after slice %d  myid  %d"%(iloop, Blockdata["myid"]))
			else:
				if	prjlist[im].get_attr("chunk_id") == random_subset:
					if nosmearing:
						bckgn = prjlist[im].get_attr("bckgnoise")
						ct = prjlist[im].get_attr("ctf")
						prjlist[im].set_attr_dict({"bckgnoise":bckgn, "ctf":ct})
						[phi, theta, psi, s2x, s2y] = get_params_proj(prjlist[im], xform = "xform.projection")
						r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi,"theta":theta,"psi":psi}), 1.0)
					else:
						if Tracker["constants"]["nsmear"]<=0.0: numbor = len(paramstructure[im][2])
						else:  numbor = 1
						ipsiandiang = [ paramstructure[im][2][i][0]/1000  for i in xrange(numbor) ]
						allshifts   = [ paramstructure[im][2][i][0]%1000  for i in xrange(numbor) ]
						probs       = [ paramstructure[im][2][i][1] for i in xrange(numbor) ]
						#  Find unique projection directions
						tdir = list(set(ipsiandiang))
						bckgn = prjlist[im].get_attr("bckgnoise")
						ct = prjlist[im].get_attr("ctf")
						#  For each unique projection direction:
						data = [None]*nshifts
						for ii in xrange(len(tdir)):
							#  Find the number of times given projection direction appears on the list, it is the number of different shifts associated with it.
							lshifts = findall(tdir[ii], ipsiandiang)
							toprab  = 0.0
							for ki in xrange(len(lshifts)):  toprab += probs[lshifts[ki]]
							recdata = EMData(nny,nny,1,False)
							recdata.set_attr("is_complex",0)
							for ki in xrange(len(lshifts)):
								lpt = allshifts[lshifts[ki]]
								if( data[lpt] == None ):
									data[lpt] = fshift(prjlist[im], rshifts_shrank[lpt][0], rshifts_shrank[lpt][1])
									data[lpt].set_attr("is_complex",0)
								Util.add_img(recdata, Util.mult_scalar(data[lpt], probs[lshifts[ki]]/toprab))
							recdata.set_attr_dict({"padffted":1, "is_fftpad":1,"is_fftodd":0, "is_complex_ri":1, "is_complex":1})
							if not upweighted:  recdata = filt_table(recdata, bckgn )
							recdata.set_attr_dict( {"bckgnoise":bckgn, "ctf":ct} )
							ipsi = tdir[ii]%100000
							iang = tdir[ii]/100000
							r.insert_slice(recdata, Transform({"type":"spider","phi":refang[iang][0],"theta":refang[iang][1],"psi":refang[iang][2]+ipsi*delta}), toprab*avgnorm/norm_per_particle[im])
	#  clean stuff
	#if not nosmearing: del recdata, tdir, ipsiandiang, allshifts, probs
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if not nosmearing: del rshifts_shrank
	if myid == main_node:dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else:
		del fftvol
		del weight
		del refvol 
		return None, None, None
####<<<<--------
#####  FSC rec3d
def do3d_sorting_groups_fsc_only_iter(data, paramstructure, norm_per_particle, iteration):
	global Tracker, Blockdata
	# do resolution each time
	keepgoing = 1
	if(Blockdata["myid"] == Blockdata["nodes"][0]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	do3d_sorting_group_insertion_random_two_for_fsc(data, paramstructure, norm_per_particle)
	fsc143             = 0
	fsc05              = 0
	Tracker["fsc143"]  = 0
	Tracker["fsc05"]   = 0
	res_05             = Tracker["number_of_groups"]*[0]
	res_143            = Tracker["number_of_groups"]*[0]
	for index_of_colors in xrange(Blockdata["no_of_groups"]):
		group_start, group_end = MPI_volume_start_end(Tracker["number_of_groups"], Blockdata["no_of_groups"], index_of_colors)
		if Blockdata["color"] == index_of_colors:  # It has to be 1 to avoid problem with tvol1 not closed on the disk
			for index_of_group in xrange(group_start, group_end):								
				if Blockdata["myid_on_node"] == 0:
					#print(" odd   group    %d"%index_of_group)	
					tvol0 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0_0_%d.hdf")%index_of_group)
					tweight0 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0_0_%d.hdf")%index_of_group)
					tvol1 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1_0_%d.hdf")%index_of_group)
					tweight1 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1_0_%d.hdf")%index_of_group)
					Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["fuse_freq"])
					tag = 7007
					send_EMData(tvol1, Blockdata["no_of_processes_per_group"]-1, tag, Blockdata["shared_comm"])
					send_EMData(tweight1, Blockdata["no_of_processes_per_group"]-1, tag, Blockdata["shared_comm"])
					shrank0 	= stepone(tvol0, tweight0)	
				elif Blockdata["myid_on_node"] == Blockdata["no_of_processes_per_group"]-1:
					#print(" odd   group    %d"%index_of_group)	
					tag = 7007
					tvol1 		= recv_EMData(0, tag, Blockdata["shared_comm"])
					tweight1 	= recv_EMData(0, tag, Blockdata["shared_comm"])
					tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
					shrank1 	= stepone(tvol1, tweight1)
					
				if Blockdata["myid_on_node"] == 1:
					tvol0 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_0_1_%d.hdf")%index_of_group)
					tweight0 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_0_1_%d.hdf")%index_of_group)
					tvol1 		= get_im(os.path.join(Tracker["directory"], "tempdir", "tvol_1_1_%d.hdf")%index_of_group)
					tweight1 	= get_im(os.path.join(Tracker["directory"], "tempdir", "tweight_1_1_%d.hdf")%index_of_group)
					Util.fuse_low_freq(tvol0, tvol1, tweight0, tweight1, 2*Tracker["fuse_freq"])
					tag = 7007
					send_EMData(tvol1, Blockdata["no_of_processes_per_group"]-2, tag, Blockdata["shared_comm"])
					send_EMData(tweight1, Blockdata["no_of_processes_per_group"]-2, tag, Blockdata["shared_comm"])
					shrank0 	= stepone(tvol0, tweight0)					
				elif Blockdata["myid_on_node"] == Blockdata["no_of_processes_per_group"]-2:
					#print(" even   group    %d"%index_of_group)
					tag = 7007
					tvol1 		= recv_EMData(1, tag, Blockdata["shared_comm"])
					tweight1 	= recv_EMData(1, tag, Blockdata["shared_comm"])
					tvol1.set_attr_dict( {"is_complex":1, "is_fftodd":1, 'is_complex_ri': 1, 'is_fftpad': 1} )
					shrank1 	= stepone(tvol1, tweight1)
										
				mpi_barrier(Blockdata["shared_comm"])				
				if 	Blockdata["myid_on_node"] == 0:
					tag = 7007					
					send_EMData(shrank0, Blockdata["no_of_processes_per_group"]-1, tag, Blockdata["shared_comm"])
					del shrank0
					lcfsc = 0
				elif Blockdata["myid_on_node"] == Blockdata["no_of_processes_per_group"]-1:
					#print(" now we do fsc  odd ")	
					tag = 7007
					shrank0 	= recv_EMData(0, tag, Blockdata["shared_comm"])
					cfsc 		= fsc(shrank0, shrank1)[1]
					write_text_row(cfsc, os.path.join(Tracker["directory"], "fsc_driver_chunk0_grp%03d_iter%03d.txt")%(index_of_group,iteration))
					del shrank0, shrank1
					if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]):
						cfsc 	= cfsc[:Tracker["nxinit"]]
						for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1):  cfsc.append(0.0)
					lcfsc = len(cfsc)							
					fsc05  = 0
					fsc143 = 0 
					for ifreq in xrange(len(cfsc)):	
						if cfsc[ifreq] <0.5: break
					fsc05  = ifreq - 1
					for ifreq in xrange(len(cfsc)):
						if cfsc[ifreq]<0.143: break
					fsc143 = ifreq - 1
					Tracker["fsc143"] = fsc143
					Tracker["fsc05"]  = fsc05		
				if 	Blockdata["myid_on_node"] == 1:
					#print(" now we do step one  even")	
					tag = 7007					
					send_EMData(shrank0, Blockdata["no_of_processes_per_group"]-2, tag, Blockdata["shared_comm"])
					del shrank0
					lcfsc = 0					
				elif Blockdata["myid_on_node"] == Blockdata["no_of_processes_per_group"]-2:
					tag = 7007
					shrank0 = recv_EMData(1, tag, Blockdata["shared_comm"])
					cfsc = fsc(shrank0, shrank1)[1]
					write_text_row(cfsc, os.path.join(Tracker["directory"], "fsc_driver_chunk1_grp%03d_iter%03d.txt")%(index_of_group,iteration))
					del shrank0, shrank1
					if(Tracker["nxinit"]<Tracker["constants"]["nnxo"]):
						cfsc = cfsc[:Tracker["nxinit"]]
						for i in xrange(len(cfsc),Tracker["constants"]["nnxo"]//2+1):cfsc.append(0.0)
					lcfsc = len(cfsc)							
					fsc05  = 0
					fsc143 = 0
					for ifreq in xrange(len(cfsc)):	
						if cfsc[ifreq] <0.5: break
					fsc05  = ifreq - 1
					for ifreq in xrange(len(cfsc)):
						if cfsc[ifreq]<0.143: break
					fsc143 = ifreq - 1
					Tracker["fsc143"] = fsc143
					Tracker["fsc05"]  = fsc05
				Tracker = wrap_mpi_bcast(Tracker, Blockdata["no_of_processes_per_group"]-1, Blockdata["shared_comm"])
				if( Blockdata["myid_on_node"] == 0):
					res_05[index_of_group]  = Tracker["fsc05"]
					res_143[index_of_group] = Tracker["fsc143"]				
				mpi_barrier(Blockdata["shared_comm"])
			mpi_barrier(Blockdata["shared_comm"])
	mpi_barrier(MPI_COMM_WORLD)
	keepgoing = bcast_number_to_all(keepgoing, source_node = Blockdata["main_node"], mpi_comm = MPI_COMM_WORLD) # always check 
	Tracker   = wrap_mpi_bcast(Tracker, Blockdata["main_node"])
	if not keepgoing:ERROR("do3d_sorting_groups_trl_iter  %s"%os.path.join(Tracker["directory"], "tempdir"),"do3d_sorting_groups_trl_iter", 1, Blockdata["myid"]) 
	return
	
def do3d_sorting_group_insertion_random_two_for_fsc(data, sparamstructure, snorm_per_particle):
	global Tracker, Blockdata
	if(Blockdata["myid"] == Blockdata["nodes"][0]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")): os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	for index_of_groups in xrange(Tracker["number_of_groups"]):
		for procid in xrange(2):
			for ifsc in xrange(2):
				tvol, tweight, trol = recons3d_4nnsorting_group_fsc_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][procid],  \
				  prjlist = data, fsc_half = ifsc, random_subset = procid, group_ID = index_of_groups, paramstructure=sparamstructure, norm_per_particle=snorm_per_particle,\
				  CTF = Tracker["constants"]["CTF"], upweighted = False, target_size = (2*Tracker["nxinit"]+3))
				if(Blockdata["myid"] == Blockdata["nodes"][procid]):
					tvol.set_attr("is_complex",0)
					tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d_%d.hdf"%(ifsc, procid, index_of_groups)))
					tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d_%d.hdf"%(ifsc, procid, index_of_groups)))
					trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d_%d.hdf"%(ifsc, procid, index_of_groups)))
				mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
	mpi_barrier(MPI_COMM_WORLD)
	return
#### Never read volumes
		
def recons3d_4nnsorting_group_fsc_MPI(myid, main_node, prjlist, fsc_half, random_subset, group_ID, paramstructure, norm_per_particle, \
    CTF = True, upweighted = True, mpi_comm= None, target_size=-1):
	##      with smearing
	#####	recons3d_4nn_ctf - calculate CTF-corrected 3-D reconstruction from a set of projections using three Eulerian angles, two shifts, and CTF settings for each projeciton image
	####	Input
	####	list_of_prjlist: list of lists of projections to be included in the reconstruction
	global Tracker, Blockdata
	from utilities      import reduce_EMData_to_root, random_string, get_im, findall, model_blank, info, get_params_proj
	from EMAN2          import Reconstructors
	from filter		    import filt_table
	from mpi            import MPI_COMM_WORLD, mpi_barrier
	from statistics     import fsc 
	from reconstruction import insert_slices_pdf
	from fundamentals   import fft
	import datetime, types
	import copy
	if mpi_comm == None: mpi_comm = MPI_COMM_WORLD
	imgsize = prjlist[0].get_ysize()  # It can be Fourier, so take y-size
	refvol = model_blank(target_size)
	refvol.set_attr("fudge", 1.0)
	if CTF: do_ctf = 1
	else:   do_ctf = 0
	fftvol = EMData()
	weight = EMData()
	try:    qt = projlist[0].get_attr("qt")
	except: qt = 1.0
	params = {"size":target_size, "npad":2, "snr":1.0, "sign":1, "symmetry":"c1", "refvol":refvol, "fftvol":fftvol, "weight":weight, "do_ctf": do_ctf}
	r      = Reconstructors.get( "nn4_ctfw", params )
	r.setup()
	if norm_per_particle == None: norm_per_particle = len(prjlist)*[1.0]
	# Definitions for smearing ,all copied from refinement
	if not Tracker["nosmearing"]:
		delta           = Tracker["delta"]
		refang          = Tracker["refang"]
		rshifts_shrank  = copy.deepcopy(Tracker["rshifts"])
		nshifts         = len(rshifts_shrank)
		for im in xrange(nshifts):
			rshifts_shrank[im][0] *= float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
			rshifts_shrank[im][1] *= float(Tracker["nxinit"])/float(Tracker["constants"]["nnxo"])
	nnx = prjlist[0].get_xsize()
	nny = prjlist[0].get_ysize()
	nc  = 0
	for im in xrange(len(prjlist)):
		if prjlist[im].get_attr("group") == group_ID and prjlist[im].get_attr("chunk_id") == random_subset:
			if Tracker["nosmearing"]: avgnorm = 1.0
			else: avgnorm =  Tracker["avgnorm"][prjlist[im].get_attr("chunk_id")]#
			if nc %2 == fsc_half:
				if Tracker["nosmearing"]:
					ct    = prjlist[im].get_attr("ctf")
					bckgn = prjlist[im].get_attr("bckgnoise")
					if not upweighted: prjlist[im] = filt_table(prjlist[im], bckgn)
					prjlist[im].set_attr_dict( {"bckgnoise":bckgn, "ctf":ct})
					phi,theta,psi,s2x,s2y = get_params_proj(prjlist[im], xform = "xform.projection")
					r.insert_slice(prjlist[im], Transform({"type":"spider","phi":phi, "theta":theta, "psi":psi}), 1.0)
				else:
					if Tracker["constants"]["nsmear"]<=0.0: numbor = len(paramstructure[im][2])
					else:  numbor =1
					ipsiandiang = [paramstructure[im][2][i][0]/1000  for i in xrange(numbor)]
					allshifts   = [paramstructure[im][2][i][0]%1000  for i in xrange(numbor)]
					probs       = [paramstructure[im][2][i][1] for i in xrange(numbor)]
					#  Find unique projection directions
					tdir = list(set(ipsiandiang))
					bckgn = prjlist[im].get_attr("bckgnoise")
					ct = prjlist[im].get_attr("ctf")
					#  For each unique projection direction:
					data = [None]*nshifts
					for ii in xrange(len(tdir)):
						#  Find the number of times given projection direction appears on the list, it is the number of different shifts associated with it.
						lshifts = findall(tdir[ii], ipsiandiang)
						toprab  = 0.0
						for ki in xrange(len(lshifts)):  toprab += probs[lshifts[ki]]
						recdata = EMData(nny,nny,1,False)
						recdata.set_attr("is_complex",0)
						for ki in xrange(len(lshifts)):
							lpt = allshifts[lshifts[ki]]
							if( data[lpt] == None ):
								data[lpt] = fshift(prjlist[im], rshifts_shrank[lpt][0], rshifts_shrank[lpt][1])
								data[lpt].set_attr("is_complex",0)
							Util.add_img(recdata, Util.mult_scalar(data[lpt], probs[lshifts[ki]]/toprab))
						recdata.set_attr_dict({"padffted":1, "is_fftpad":1,"is_fftodd":0, "is_complex_ri":1, "is_complex":1})
						if not upweighted:  recdata = filt_table(recdata, bckgn )
						recdata.set_attr_dict( {"bckgnoise":bckgn, "ctf":ct} )
						ipsi = tdir[ii]%100000
						iang = tdir[ii]/100000
						r.insert_slice( recdata, Transform({"type":"spider","phi":refang[iang][0],"theta":refang[iang][1],"psi":refang[iang][2]+ipsi*delta}), toprab*avgnorm/norm_per_particle[im])
			nc +=1
	reduce_EMData_to_root(fftvol, myid, main_node, comm=mpi_comm)
	reduce_EMData_to_root(weight, myid, main_node, comm=mpi_comm)
	if myid == main_node: dummy = r.finish(True)
	mpi_barrier(mpi_comm)
	if myid == main_node: return fftvol, weight, refvol
	else: return None, None, None
#####end of FSC
###<<<-----group rec3d
### insertion
def do3d_sorting_group_insertion_smearing(sdata, sparamstructure, snorm_per_particle, randomset=2):
	global Tracker, Blockdata
	if(Blockdata["myid"] == Blockdata["nodes"][0]):
		if not os.path.exists(os.path.join(Tracker["directory"], "tempdir")):os.mkdir(os.path.join(Tracker["directory"], "tempdir"))
	if randomset ==1:
		for index_of_groups in xrange(Tracker["number_of_groups"]):
			for procid in xrange(2, 3):
				tvol, tweight, trol = recons3d_trl_struct_group_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][procid//2],\
				  prjlist = sdata,  random_subset = procid, group_ID = index_of_groups, paramstructure = sparamstructure, \
				  norm_per_particle = snorm_per_particle, CTF = Tracker["constants"]["CTF"],\
					mpi_comm = None, upweighted = False, target_size = (2*Tracker["nxinit"]+3), nosmearing = Tracker["nosmearing"])	
				if(Blockdata["myid"] == Blockdata["nodes"][procid//2]):
					tvol.set_attr("is_complex",0)
					tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d.hdf"%(procid, index_of_groups)))
					tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d.hdf"%(procid, index_of_groups)))
					trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d.hdf"%(procid, index_of_groups)))
				del tvol
				del tweight
				del trol
				mpi_barrier(MPI_COMM_WORLD)
	else:
		for index_of_groups in xrange(Tracker["number_of_groups"]):
			for procid in xrange(3):
				tvol, tweight, trol = recons3d_trl_struct_group_MPI(myid = Blockdata["myid"], main_node = Blockdata["nodes"][procid//2],\
				  prjlist = sdata,  random_subset = procid, group_ID = index_of_groups, paramstructure = sparamstructure, \
				   norm_per_particle = snorm_per_particle, CTF = Tracker["constants"]["CTF"],\
					mpi_comm= None, upweighted = False, target_size = (2*Tracker["nxinit"]+3), nosmearing = Tracker["nosmearing"])
				if(Blockdata["myid"] == Blockdata["nodes"][procid//2]):
					tvol.set_attr("is_complex",0)
					tvol.write_image(os.path.join(Tracker["directory"], "tempdir", "tvol_%d_%d.hdf"%(procid, index_of_groups)))
					tweight.write_image(os.path.join(Tracker["directory"], "tempdir", "tweight_%d_%d.hdf"%(procid, index_of_groups)))
					trol.write_image(os.path.join(Tracker["directory"], "tempdir", "trol_%d_%d.hdf"%(procid, index_of_groups)))
				del tvol
				del tweight
				del trol
				mpi_barrier(MPI_COMM_WORLD)
	mpi_barrier(MPI_COMM_WORLD)
	return
### rec3d 
####<<<-------MEM related functions
def _VmB(VmKey):
    global _proc_status, _scale
     # get pseudo file  /proc/<pid>/status
    try:
        t = open(_proc_status)
        v = t.read()
        t.close()
    except:
        return 0.0  # non-Linux?
     # get VmKey line e.g. 'VmRSS:  9999  kB\n ...'
    i = v.index(VmKey)
    v = v[i:].split(None, 3)  # whitespace
    if len(v) < 3:
        return 0.0  # invalid format?
     # convert Vm value to bytes
    return float(v[1]) * _scale[v[2]]
def memory(since=0.0):
    '''Return memory usage in bytes.
    '''
    return _VmB('VmSize:') - since

def resident(since=0.0):
    '''Return resident memory usage in bytes.
    '''
    return _VmB('VmRSS:') - since
def stacksize(since=0.0):
    '''Return stack size in bytes.
    '''
    return _VmB('VmStk:') - since
def memory_check(s="check_memory"):
	import os
	print(s)
	print(s +"  memory ",  memory()/1.e9)
	print(s +" resident  ", resident()/1.e9)
	print(s +" stacksize ", stacksize()/1.e9)
	
####<<<----do final maps ---->>>
def do_final_maps(number_of_groups, minimum_size, selected_iter, refinement_dir, masterdir, rec3d_image_size, log_main):
	global Tracker, Blockdata
	import shutil
	from   shutil import copyfile
	for icluster  in xrange(number_of_groups):
		clusterdir = os.path.join(masterdir, "Cluster%d"%icluster)
		if os.path.exists(clusterdir):
			if Blockdata["myid"] == icluster: shutil.rmtree(clusterdir)
	mpi_barrier(MPI_COMM_WORLD)
	line    = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg_pipe = '-------------------------------------------------------'
		msg      = "------------>>>>>>>Check memory <<<<-------------------"
		log_main.add(msg_pipe)
		log_main.add(msg)
		log_main.add(msg_pipe)
		print(line, msg_pipe)
		print(line, msg)
		print(line, msg_pipe)
	basic_memory_per_cpu    = 1.0
	total_data_in_mem       = Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"]*Tracker["constants"]["total_stack"]*4./1.e9
	one_volume_in_mem       = Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"]*Tracker["constants"]["nnxo"]*4.*8./1.e9
	nproc_do_final_per_node =(Tracker["constants"]["memory_per_node"] - total_data_in_mem -1.0)/(basic_memory_per_cpu + one_volume_in_mem)
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg = "total mem per node: %5.1f G"%Tracker["constants"]["memory_per_node"]
		log_main.add(msg)
		print(line, msg)
	nproc_do_final_per_node = int(nproc_do_final_per_node)
	if nproc_do_final_per_node > Blockdata["nproc"] //Blockdata["no_of_groups"]:
		nproc_do_final_per_node = Blockdata["nproc"] //Blockdata["no_of_groups"]
	if Blockdata["nproc_previous"] > 0: nproc_do_final_per_node = min(nproc_do_final_per_node, Blockdata["nproc_previous"]//Blockdata["no_of_groups"])
	ncpu_per_node = min(minimum_size//5//Blockdata["no_of_groups"]//2, nproc_do_final_per_node)
	ncpu_per_node = max(ncpu_per_node, 2)
	if( Blockdata["myid"] == Blockdata["main_node"]):
		msg = "CPUs to be used per node: %d"%ncpu_per_node
		log_main.add(msg)
		print(line, msg)
	Blockdata["ncpuspernode"] = ncpu_per_node
	Blockdata["nsubset"]      = Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
	create_subgroup()
	fuse_freq = Tracker["fuse_freq"] # sort does it already
	mask3D    = Tracker["mask3D"]
	mtf       = Tracker["constants"]["mtf"]
	fsc_adj   = Tracker["constants"]["fsc_adj"]
	Bstart    = Tracker["constants"]["B_start"]
	Bstop     = Tracker["constants"]["B_stop"]
	aa        = Tracker["constants"]["aa"]
	total_stack                 = Tracker["constants"]["total_stack"]
	postlowpassfilter           = Tracker["constants"]["postlowpassfilter"]
	B_enhance                   = Tracker["constants"]["B_enhance"]
	memory_per_node             = Tracker["constants"]["memory_per_node"]
	Blockdata["fftwmpi"]        = True
	Tracker["number_of_groups"] = number_of_groups
	
	if Tracker["nosmearing"]:
		if(Blockdata["myid"] == Blockdata["main_node"]):
			map_dir = os.path.join(masterdir, "maps_dir")
			if not os.path.exists(map_dir): os.mkdir(map_dir)
		else:map_dir = 0
		map_dir = wrap_mpi_bcast(map_dir, Blockdata["main_node"], MPI_COMM_WORLD)
		Tracker["directory"] = map_dir
		Tracker["nxinit"]    = Tracker["constants"]["nnxo"]
		compute_noise(Tracker["nxinit"])
		data = get_shrink_data_sorting(os.path.join(masterdir, "final_partition.txt"), \
		os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt"), \
		return_real = False, preshift = True, apply_mask = False)
		do3d_sorting_groups_trl_iter(data, 0)
		del data
		if(Blockdata["myid"] == Blockdata["main_node"]):
			for icluster in xrange(number_of_groups):
				copyfile(os.path.join(Tracker["directory"], "vol_unfiltered_0_grp%03d_iter000.hdf"%icluster), \
				os.path.join(masterdir, "vol_unfiltered_0_grp%03d.hdf"%icluster))
				copyfile(os.path.join(Tracker["directory"], "vol_unfiltered_1_grp%03d_iter000.hdf"%icluster), \
				os.path.join(masterdir, "vol_unfiltered_1_grp%03d.hdf"%icluster))
			shutil.rmtree(map_dir)
		mpi_barrier(MPI_COMM_WORLD)
	else:
		for icluster in xrange(Tracker["number_of_groups"]):
			cluster_masterdir = os.path.join(masterdir,"Cluster%d"%icluster)
			if(Blockdata["myid"] == Blockdata["main_node"]): 
				if not os.path.exists(cluster_masterdir): os.mkdir(cluster_masterdir)
			mpi_barrier(MPI_COMM_WORLD)
			do_ctrefromsort3d_get_subset_data(cluster_masterdir, refinement_dir, \
			  os.path.join(masterdir,"Cluster_%03d.txt"%icluster), selected_iter, None, Blockdata["subgroup_comm"])
			Tracker["constants"]["small_memory"] = False
			ctrefromsorting_rec3d_faked_iter(cluster_masterdir, selected_iter, rec3d_image_size, Blockdata["subgroup_comm"])
			mpi_barrier(MPI_COMM_WORLD)
		mpi_barrier(MPI_COMM_WORLD)
		
		Tracker["constants"]["B_enhance"] = B_enhance
		Tracker["constants"]["B_start"]   = Bstart    
		Tracker["constants"]["B_stop"]    = Bstop    
		Tracker["constants"]["aa"]        = aa  
		Tracker["constants"]["postlowpassfilter"] = postlowpassfilter  
		Tracker["constants"]["fsc_adj"]=fsc_adj
		Tracker["constants"]["mtf"]    = mtf
		Tracker["mask3D"]              = mask3D
		Tracker["nxinit"]              = rec3d_image_size 
		Tracker["number_of_groups"]    = number_of_groups
		Tracker["fuse_freq"]           = fuse_freq # reset
		Tracker["constants"]["memory_per_node"] = memory_per_node
		Tracker["constants"]["total_stack"] = total_stack
		
		# Using all CPUS to do step two
		Blockdata["ncpuspernode"] = Blockdata["nproc"]//Blockdata["no_of_groups"]
		Blockdata["nsubset"]  = Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
		create_subgroup()
		do3d_sorting_groups_rec3d(selected_iter, masterdir, log_main)
		if(Blockdata["myid"] == Blockdata["main_node"]):
			for icluster in xrange(Tracker["number_of_groups"]):
				cluster_masterdir = os.path.join(masterdir,"Cluster%d"%icluster)
				if os.path.exists(cluster_masterdir): shutil.rmtree(cluster_masterdir)
	return
#####<<<<-------------------------Functions for post processing

def compute_final_map(log_file, work_dir):
	global Tracker, Blockdata
	Tracker["constants"]["orgres"]			 = 0.0
	Tracker["constants"]["refinement_delta"] = 0.0
	Tracker["constants"]["refinement_ts"]	 = 0.0
	Tracker["constants"]["refinement_xr"]	 = 0.0
	Tracker["constants"]["refinement_an"]	 = 0.0
	minimum_size  = Tracker["constants"]["img_per_grp"]
	number_of_groups = 0
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		res_msg = ""
		final_accounted_ptl = 0
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		msg_pipe = "-----------------------------------------"
		msg      = "   >>> Summaries of the results <<<      "
		print(line, msg_pipe)
		print(line, msg)
		print(line, msg_pipe)
		log_file.add(msg_pipe)
		log_file.add(msg)
		log_file.add(msg_pipe)
		msg = "cluster ID  cluster size  \n"
		log_file.add(msg)
		res_msg +=msg
		fout = open(os.path.join(work_dir, "Tracker.json"),'w')
		json.dump(Tracker, fout)
		fout.close()
		clusters = []
		while os.path.exists(os.path.join(work_dir, "Cluster_%03d.txt"%number_of_groups)):
			class_in = read_text_file(os.path.join(work_dir, "Cluster_%03d.txt"%number_of_groups))
			minimum_size = min(len(class_in), minimum_size)
			msg = "%10d    %10d   \n"%(number_of_groups, len(class_in))
			log_file.add(msg)
			res_msg +=msg
			number_of_groups += 1
			final_accounted_ptl +=len(class_in)
			clusters.append(class_in)
			del class_in
		msg = "total number of particles:   %10d ;  number_of_groups:   %5d \n"%(final_accounted_ptl, number_of_groups)
		res_msg +=msg
		msg = "the last group contains unaccounted particles of this generation \n"
		res_msg +=msg
		fout = open(os.path.join(work_dir, "generation_clusters_summary.txt"),"w")
		fout.writelines(res_msg)
		fout.close()
		Tracker["total_stack"]      = final_accounted_ptl
		Tracker["number_of_groups"] = number_of_groups
		Tracker["nxinit"]           = Tracker["nxinit_refinement"]
	else: Tracker = 0
	
	number_of_groups = bcast_number_to_all(number_of_groups, Blockdata["main_node"], MPI_COMM_WORLD)
	Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
	if number_of_groups == 0: ERROR("No cluster is found, and the program terminates.", "do_final_maps", 1, Blockdata["myid"])
	compute_noise( Tracker["nxinit"])
	
	if(Blockdata["myid"] == Blockdata["main_node"]):
		alist, partition = merge_classes_into_partition_list(clusters)
		write_text_row(partition, os.path.join(work_dir, "generation_partition.txt"))
	parti_file = os.path.join(work_dir, "generation_partition.txt")
	params          = os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt")
	previous_params = Tracker["previous_parstack"]
	original_data, norm_per_particle  = read_data_for_sorting(parti_file, params, previous_params)
	
	if Tracker["nosmearing"]:
		parameterstructure  = None
		paramstructure_dict = None
		paramstructure_dir  = None
	else:
		paramstructure_dict = Tracker["paramstructure_dict"]
		paramstructure_dir  = Tracker["paramstructure_dir"]
		parameterstructure  = read_paramstructure_for_sorting(parti_file, paramstructure_dict, paramstructure_dir)
		
	mpi_barrier(MPI_COMM_WORLD)
	Tracker["directory"]    = work_dir
	compute_noise(Tracker["nxinit"])
	cdata, rdata, fdata = downsize_data_for_sorting(original_data, preshift = True, npad = 1, norms = norm_per_particle)# pay attentions to shifts!
	
	mpi_barrier(MPI_COMM_WORLD)
	srdata = precalculate_shifted_data_for_recons3D(rdata, parameterstructure, Tracker["refang"], Tracker["rshifts"], \
	  Tracker["delta"], Tracker["avgnorm"], Tracker["nxinit"], Tracker["constants"]["nnxo"], Tracker["nosmearing"], \
	      norm_per_particle,  Tracker["constants"]["nsmear"])
	del rdata
	mpi_barrier(MPI_COMM_WORLD)
	do3d_sorting_groups_nofsc_smearing_iter(srdata, False, iteration = 0)
	mpi_barrier(MPI_COMM_WORLD)
	return
#####<<<<----various utilities
def shake_assignment(assignment, randomness_rate = 1.0):
	import random
	number_of_group = max(assignment)
	for im in xrange(len(assignment)):
		if (random.uniform(0.0, 1.0) > randomness_rate): assignment[im] = random.randint(0, number_of_groups)
	return assignment

def get_time(time_start):
	current_time   = time.time() - time_start
	current_time_h = current_time // 3600
	current_time_m = (current_time - current_time_h*3600)// 60
	return int(current_time_h), int(current_time_m)

def check_sorting(total_data, keepsorting, log_file):
	global Tracker, Blockdata
	import json
	if Blockdata["myid"] == Blockdata["main_node"]:
		fout = open(os.path.join(Tracker["constants"]["masterdir"],"Tracker.json"),'r')
		Tracker_main = convert_json_fromunicode(json.load(fout))
		fout.close()
	else: Tracker_main = 0
	Tracker_main = wrap_mpi_bcast(Tracker_main, Blockdata["main_node"])
	if total_data//Tracker_main["constants"]["img_per_grp"] >=2:
		Tracker["number_of_groups"] = total_data//Tracker_main["constants"]["img_per_grp"]
		keepsorting = 1
	else:
		if Tracker_main["constants"]["minimum_grp_size"]>0:
			if total_data//Tracker_main["constants"]["minimum_grp_size"]>=3:
				Tracker["number_of_groups"] = total_data//Tracker_main["constants"]["minimum_grp_size"] -1
				keepsorting = 1
			else: keepsorting = 0
		else: keepsorting     = 0
	if keepsorting ==1:
		Tracker["total_stack"] = total_data
		sort3d_init("initialization", log_file)
	return keepsorting

def copy_results(log_file):
	global Tracker, Blockdata
	import json
	from   shutil import copyfile
	from   string import atoi
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	if Blockdata["myid"] == Blockdata["main_node"]:
		line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
		msg  ="copy clusters and the associated maps to main directory......"
		log_file.add(msg)
		print(line, msg)
		nclusters = 0
		msg       ="cluster ID    size"
		log_file.add(msg)
		clusters    = []
		sorting_res = '{:^50} {}'.format('------->>>>sort3d summary<<<---------', '\n')
		NACC = 0           
		for element in Tracker["generation"].items():
			ig    = element[0]
			value = element[1]
			for ic in xrange(value):
				cluster_file = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%ig, "Cluster_%03d.txt"%ic)
				try:
					copyfile(cluster_file, os.path.join(Tracker["constants"]["masterdir"], "Cluster_%03d.txt"%nclusters))
					clusters.append(read_text_file(cluster_file))
					copyfile(os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%ig, \
					 "vol_grp%03d_iter000.hdf"%ic), \
					   os.path.join(Tracker["constants"]["masterdir"], "vol_cluster%03d.hdf"%nclusters))
					cluster = read_text_file(os.path.join(Tracker["constants"]["masterdir"], \
					   "generation_%03d"%ig, "Cluster_%03d.txt"%ic))
					msg = "%5d    %10d"%(nclusters, len(cluster))
					sorting_res += '{:^8} {:^8} {}'.format(nclusters, len(cluster), '\n')
					nclusters +=1
					NACC +=len(cluster)
				except: msg ="%s and associated files are not found "%cluster_file
				log_file.add(msg)
				print(line, msg)
		NUACC = Tracker["constants"]["total_stack"] - NACC
		do_analysis_on_identified_clusters(clusters, log_file)
		msg = "sort3d finishes"
		log_file.add(msg)
		print(line, msg)
		fout = open(os.path.join(Tracker["constants"]["masterdir"], "Tracker.json"), 'w')
		json.dump(Tracker, fout)
		fout.close()
		sorting_res +='{:^12} {:^8} {:^12} {:^8} {:^12} {:^8} {}'.format('total_stack', Tracker["constants"]["total_stack"], 'accounted: ', NACC, 'unaccounted:', NUACC, '\n')
		sorting_res +='the last cluster of the last generation contains unaccounted ones \n'
		fout = open(os.path.join(Tracker["constants"]["masterdir"], "sorting_summary.txt"),"w")
		fout.writelines(sorting_res)
		fout.close()
	mpi_barrier(MPI_COMM_WORLD)
	return
####+++++++
def get_MGR_from_two_way_comparison(newindeces, clusters1, clusters2, N):
	rnd_grp_sizes = {}
	K = len(newindeces)
	reordered_cluster2 =[ None for i in xrange(K)]
	for ij in xrange(len(newindeces)):
		reordered_cluster2[newindeces[ij][0]] = clusters2[newindeces[ij][1]]
	table_k_k =[[ None for i in xrange(K)] for j in xrange(K)]
	for i in xrange(K):
		for j in xrange(K):
			table_k_k[i][j] = len(set(clusters1[i]).intersection(set(reordered_cluster2[j])))	
	sum_rows = [ 0 for i in xrange(K)]
	sum_cols = [ 0 for i in xrange(K)]
	for i in xrange(K):
		for j in xrange(K):
			sum_rows[i] +=table_k_k[i][j]
			sum_cols[j] +=table_k_k[i][j]
	diagonal_k = [None for i in xrange(K)]
	for i in xrange(K): diagonal_k[i] = (sum_rows[i] + sum_cols[i])//2 # nk
	min_sizes = [None for i in xrange(K)]
	for i in xrange(K): min_sizes[i] = diagonal_k[i]**2/N
	return min_sizes

def estimate_tanhl_params(cutoff, taa, image_size):
	from math import sqrt
	def tanhfl(x, cutoff, taa):
		from math import pi, tanh
		omega = cutoff
		cnst  = pi/(2.0*omega*taa)
		v1    = (cnst*(x + omega))
		v2    = (cnst*(x - omega))
		return 0.5*(tanh(v1) - tanh(v2))
	
	def get_filter(cutoff1, taa, image_size):
		values = []
		N = image_size//2
		for im in xrange(N):
			x = float(im)/float(image_size)
			values.append(tanhfl(x, cutoff1, taa))
		return values

	values  = get_filter(cutoff, taa, image_size)
	icutoff = image_size
	init    = int(cutoff*image_size)
	while icutoff>=cutoff*image_size:
		cutoff1 = float(init)/image_size
		values  = get_filter(cutoff1, taa, image_size)
		for im in xrange(len(values)):
			if values[im] <=0.0:
				icutoff = im
				break
		init -=1
	return cutoff1, taa

def print_matching_pairs(pair_list, log_file):
	line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
	msg ='P0 (GID as row index) matches P1 (GID as column index)'
	log_file.add(msg)
	print(line, msg)
	msg ='   '
	for i in xrange(len(pair_list)):
		msg += '{:^5d}'.format(i)
	print(line, msg+'\n')
	log_file.add(msg+'\n')
	for im in xrange(len(pair_list)):
		msg ='{:^3d}'.format(im)
		for jm in xrange(len(pair_list)):
			not_found = True
			for km in xrange(len(pair_list)):
				if pair_list[km][0] == im and pair_list[km][1] == jm:
					msg +='{:^5s}'.format('M')
					not_found = False
			if not_found: msg +='{:^5s}'.format(' ')
		print(line, msg+'\n')
		log_file.add(msg+'\n')
	return
#####<<<----------------------------- End of various utilities	
def main():
	from optparse   import OptionParser
	from global_def import SPARXVERSION
	from EMAN2      import EMData
	from logger     import Logger, BaseLogger_Files
	from global_def import ERROR
	import sys, os, time, shutil
	global Tracker, Blockdata
	progname = os.path.basename(sys.argv[0])
	usage = progname + " --refinement_dir=masterdir_of_sxmeridien   --output_dir=sort3d_output --mask3D=mask.hdf --focus=binarymask.hdf  --radius=outer_radius " +\
	"  --sym=c1  --img_per_grp=img_per_grp  --minimum_grp_size=minimum_grp_size "
	parser = OptionParser(usage,version=SPARXVERSION)
	parser.add_option("--refinement_dir",                    type   ="string",        default ='',                     help="sxmeridien 3-D refinement directory")
	parser.add_option("--instack",                           type   ="string",        default ='',					   help="file name, data stack for sorting provided by user. It applies when sorting starts from a given data stack")

	initiate_from_meridien_mode = False
	for q in sys.argv[1:]:
		if( q[:16] == "--refinement_dir" ):
			initiate_from_meridien_mode = True
			break
	
	initiate_from_data_stack_mode = False
	for q in sys.argv[1:]:
		if( q[:9] == "--instack" ):
			initiate_from_data_stack_mode = True
			break
	
  	# priority
	if initiate_from_data_stack_mode and initiate_from_meridien_mode:
		initiate_from_data_stack_mode = False
		
	if (not initiate_from_data_stack_mode) and (not initiate_from_meridien_mode):
		if Blockdata["myid"] == Blockdata["main_node"]:
			print("Specify either of two options to start the program: --refinement_dir, --instack")
	
	if initiate_from_meridien_mode:
		if Blockdata["myid"] == Blockdata["main_node"]: print("initiate_from_meridien_mode")
		parser.add_option("--output_dir",                        type   ="string",        default ='',					   help="sort3d output directory name")
		parser.add_option("--niter_for_sorting",                 type   ="int",           default =-1,					   help="user specified iteration number of 3D refinement for sorting")
		parser.add_option("--focus",                             type   ="string",        default ='',                     help="Focus 3D mask. File path of a binary 3D mask for focused clustering ")
		parser.add_option("--mask3D",                            type   ="string",        default ='',                     help="3D mask. File path of the global 3D mask for clustering")
		parser.add_option("--radius",                            type   ="int",           default =-1,	                   help="Estimated protein radius in pixels")
		parser.add_option("--sym",                               type   ="string",        default ='c1',                   help="point-group symmetry")
		parser.add_option("--img_per_grp",                       type   ="int",           default =1000,                   help="number of images per group")
		parser.add_option("--nsmear",                            type   ="float",         default =-1.,                    help="number of smears used in sorting. Fill it with 1 if user does not want to use all smears")
		parser.add_option("--minimum_grp_size",				     type   ="int",           default =-1,					   help="cluster selection size")
		parser.add_option("--depth_order",				         type   ="int",           default =2,					   help="depth order. A number defines the number of initial independent MGSKmeans runs (2^depth_order)")
		parser.add_option("--memory_per_node",                   type   ="float",         default =-1.0,                   help="memory_per_node, the number used for computing the CPUs/NODE settings given by user")
		parser.add_option("--orientation_groups",                type   ="int",           default =100,                    help="mumber of orientation groups in the asymmetric unit")
		parser.add_option("--not_include_unaccounted",           action ="store_true",    default =False,                  help="do not reconstruct unaccounted elements in each generation")
		parser.add_option("--stop_mgskmeans_percentage",         type   ="float",         default =10.0,                   help="swap ratio. A float number between 0.0 and 50")
		parser.add_option("--swap_ratio",                        type   ="float",         default =1.0,                    help="randomness ratio of swapping accounted elements with unaccounted elemetns per cluster")
		parser.add_option("--notapplybckgnoise",                 action ="store_true",    default =False,                  help="do not applynoise")
		parser.add_option("--do_swap_au",                        action ="store_true",    default =False,                  help="swap flag")
		#parser.add_option("--restart_from_generation",		     type   ="int",           default =-1,					   help="restart from this geneartion,  the defalut value implies there is no restart")
		#parser.add_option("--restart_from_depth_order",		 type   ="int",           default =-1,					   help="restart from this depth order, the defalut value implies there is no restart")
		#parser.add_option("--restart_from_nbox",				 type   ="int",           default = 0,					   help="restart from the nubmer of box in the specified depth level")
		parser.add_option("--shake",                             type   ="float",         default = 0.0,                   help="perturbation factor applied to orientation groups")
		(options, args) = parser.parse_args(sys.argv[1:])
		from utilities import bcast_number_to_all
		### Sanity check
	
		checking_flag = 0
		if Blockdata["myid"] == Blockdata["main_node"]:
			if options.refinement_dir !='':
				if not os.path.exists(options.refinement_dir): checking_flag = 1
		checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
		if checking_flag ==1:  ERROR("The specified refinement_dir does not exist", "sort3d", 1, Blockdata["myid"])
	
		if options.focus !='':
			if Blockdata["myid"] == Blockdata["main_node"]:
				if not os.path.exists(options.focus):  checking_flag = 1
			checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
			if checking_flag ==1: ERROR("The specified focus mask file does not exist", "sort3d", 1, Blockdata["myid"])
		
		if options.mask3D !='':
			if Blockdata["myid"] == Blockdata["main_node"]:
				if not os.path.exists(options.mask3D): checking_flag = 1
			checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
			if checking_flag ==1: ERROR("The specified mask3D file does not exist", "sort3d", 1, Blockdata["myid"])
		
		if options.img_per_grp <=1: ERROR("improperiate number for img_per_grp", "sort3d", 1, Blockdata["myid"])
		elif options.img_per_grp < options.minimum_grp_size: ERROR("img_per_grp should be always larger than minimum_grp_size", "sort3d", 1, Blockdata["myid"])
	
		#--- Fill input parameters into dictionary Constants
		Constants		                         = {}
		Constants["stop_mgskmeans_percentage"]   = options.stop_mgskmeans_percentage
		Constants["niter_for_sorting"]           = options.niter_for_sorting
		Constants["memory_per_node"]             = options.memory_per_node
		Constants["orgstack"]                    = options.instack
		Constants["masterdir"]                   = options.output_dir
		Constants["refinement_dir"]              = options.refinement_dir
	
		if options.mask3D == '': Constants["mask3D"] = False
		else:   Constants["mask3D"] = options.mask3D
		if options.focus!='':   Constants["focus3Dmask"] = options.focus
		else: Constants["focus3Dmask"] = False
	
		Constants["depth_order"]                 = options.depth_order
		Constants["img_per_grp"]                 = options.img_per_grp
		Constants["minimum_grp_size"]      		 = options.minimum_grp_size
		Constants["radius"]              		 = options.radius
		Constants["sym"]                         = options.sym
		Constants["nsmear"]                      = options.nsmear

		Constants["restart_from_nbox"]           =  0 #options.restart_from_nbox
		Constants["restart_from_depth_order"]    = -1 #options.restart_from_depth_order
		Constants["restart_from_generation"]     = -1 #options.restart_from_generation
		Constants["shake"]                       = options.shake
	
		#### options for advanced users
		Constants["relax_oriens"]                = False 
		Constants["do_swap_au"]                  = options.do_swap_au
		Constants["swap_ratio"]                  = options.swap_ratio
		Constants["not_include_unaccounted"]     = False
		Constants["final_sharpen"]               = True #options.do_not_combinemaps
		Constants["nxinit"]                      = -1
		Constants["box_niter"]                   = 5 
	
		### Frozen options
		Constants["upscale"]                     = 0.5 #
		Constants["interpolation"]               = "trl"
		Constants["comparison_method"]           = "cross" #options.comparison_method # either cross or eucd
		Constants["symmetry"]                    = Constants["sym"]
		Constants["CTF"]                		 = True
		Constants["do_not_use_3dmask"]           = False 
	
		if options.focus:  Constants["comparison_method"] = "cross" # in case of focus3D, cross is used.
		Constants["fuse_freq"] = 45.  # Now in A, convert to pixels before being used
		Constants["orientation_groups"]  = 100 #options.orientation_groups # orientation constrained angle step
		# -------------------------------------------------------------
		#
		# Create and initialize Tracker dictionary with input options  # State Variables	
		Tracker                     = {}
		Tracker["constants"]	    = Constants
		if Tracker["constants"]["mask3D"]: Tracker["mask3D"] = Tracker["constants"]["mask3D"]
		else: Tracker["mask3D"]     = None
		Tracker["radius"]           = Tracker["constants"]["radius"]
		Tracker["upscale"]          = Tracker["constants"]["upscale"]
		Tracker["applyctf"]         = False  # Should the data be premultiplied by the CTF.  Set to False for local continuous.
		Tracker["nxinit"]           = Tracker["constants"]["nxinit"]
		if options.notapplybckgnoise: Tracker["applybckgnoise"] = False
		else:                         Tracker["applybckgnoise"] = True
	
		###<<<--options for advanced users:
		Tracker["total_number_of_iterations"] = 25
		Tracker["clean_volumes"]              = True # always true
	
		### -----------Orientation constraints
		Tracker["tilt1"]                =  0.0
		Tracker["tilt2"]                = 180.0
		Tracker["grp_size_relx_ratio"]  = 0.98
		Tracker["minimum_ptl_number"]   = 20
		### ------------<<< option for proteins images that have preferred orientations
		 # for orientation groups
		if    Tracker["constants"]["memory_per_node"] == -1 or Tracker["constants"]["memory_per_node"] <32.: Tracker["constants"]["small_memory"] = True
		else: Tracker["constants"]["small_memory"] = False
	
		## additional check
		Tracker["constants"]["hardmask"] = True
		Tracker["applymask"]             = True
		Tracker["constants"]["refinement_method"] ="SPARX" 
		Tracker["nosmearing"]     = False
		checking_flag = 0 # reset
		
		Blockdata["fftwmpi"]      = True
		try : 
			Blockdata["symclass"]                      = symclass(Tracker["constants"]["symmetry"])
			from string import atoi
			Tracker["constants"]["orientation_groups"] = max(4, 100//Blockdata["symclass"].nsym)
			
		except: pass
		get_angle_step_from_number_of_orien_groups(Tracker["constants"]["orientation_groups"])
		Blockdata["ncpuspernode"] = Blockdata["no_of_processes_per_group"]
		Blockdata["nsubset"]      = Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
		
		create_subgroup()
		create_zero_group()
		
		#<<<---------------------->>>imported functions<<<---------------------------------------------
		from statistics 	import k_means_match_clusters_asg_new,k_means_stab_bbenum
		from utilities 		import get_im,bcast_number_to_all,cmdexecute,write_text_file,read_text_file,wrap_mpi_bcast, get_params_proj, write_text_row
		from utilities 		import get_number_of_groups
		from filter			import filt_tanl
		from time           import sleep
		from logger         import Logger,BaseLogger_Files
		import string
		import json
		import user_functions
		from string         import split, atoi, atof
		####--------------------------------------------------------------
	
		continue_from_interuption = 0
		# sorting starts...
		time_sorting_start = time.time()
	
		if Tracker["constants"]["restart_from_generation"] == -1:
			continue_from_interuption = sort3d_utils("create_masterdir", None)
			#if Blockdata["myid"] == Blockdata["main_node"]:
			#	print("continue_from_interuption", continue_from_interuption, Blockdata["myid"])
			log_main = Logger(BaseLogger_Files())
			log_main.prefix = Tracker["constants"]["masterdir"]+"/"
			
			if Blockdata["myid"] == Blockdata["main_node"]:
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				msg_cross='==========================================' 
				msg      = '           >>>   DEPTH SORT3D   <<<            '
				log_main.add(msg_cross)
				log_main.add(msg)
				log_main.add(msg_cross+'\n')
				print(line, msg_cross)
				print(line, msg)
				print(line, msg_cross+'\n')
				
			if continue_from_interuption == 0: 
				sort3d_utils("import_data",   log_main)
				sort3d_utils("print_command", log_main)
				sort3d_utils("check_mask3d",  log_main)
				sort3d_utils("check_mpi_settings", log_main)
				keepsorting = sort3d_utils("initialization", log_main)
				sort3d_utils("dump_tracker", log_main = log_main)
				if not keepsorting:
					from mpi import mpi_finalize
					mpi_finalize()
					exit()
			else: sort3d_utils("load_tracker", log_main = log_main) # a simple continuation, continue from the interrupted box
		else: check_restart_from_given_depth_order(options.depth_order, options.restart_from_generation, \
				 options.restart_from_depth_order, options.restart_from_nbox, log_main) # need a check !!!
	
		Tracker["generation"]         = {}
		Tracker["current_generation"] = 0
		igen         = 0
		keepsorting  = 1
		keepchecking = 1
		my_pids      = os.path.join(Tracker["constants"]["masterdir"], "indexes.txt")
		work_dir     = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen)
		Tracker["current_generation"] = igen
		if Blockdata["myid"] == Blockdata["main_node"]:
			if not os.path.exists(os.path.join(work_dir)):
				os.mkdir(work_dir)
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				msg_pipe =' -----------------------------------'
				msg      =' >>>>>>>sort3d generation %d<<<<< '%igen
				print(line, msg_pipe)
				print(line, msg)
				print(line, msg_pipe)
				log_main.add(msg_pipe)
				log_main.add(msg)
				log_main.add(msg_pipe)
				mark_sorting_state(work_dir, False, log_main)
				time_generation_start = time.time()
		while keepsorting ==1:
			if Blockdata["myid"] == Blockdata["main_node"]:
				keepchecking = check_sorting_state(work_dir, keepchecking, log_main)
				time_generation_start = time.time()
			else: keepchecking = 0
			keepchecking = bcast_number_to_all(keepchecking, Blockdata["main_node"], MPI_COMM_WORLD)
			if keepchecking == 0: # new, do it
				params          = os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt")
				previous_params = Tracker["previous_parstack"]
				output_list     = depth_clustering(work_dir, options.depth_order, my_pids, params, previous_params, log_main)
				keepsorting     = check_sorting(len(output_list[0][1]), keepsorting, log_main)
				if keepsorting == 0:# do final box refilling
					time_final_box_start = time.time()
					if Blockdata["myid"] == Blockdata["main_node"]:
						clusters = output_clusters(os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen), \
							output_list[0][0], output_list[0][1], options.not_include_unaccounted, log_main)
						Tracker["generation"][igen] = len(clusters)
					else: Tracker = 0
					Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
					sort3d_utils("dump_tracker",  log_main = log_main, input_file1 = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen))
					compute_final_map(log_main, work_dir)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						msg_pipe ='----------------------------------------'
						msg      =" >>>>>>>  sort3d depth finishes  <<<<< "
						print(line, msg_pipe)
						print(line, msg)
						print(line, msg_pipe)
						log_main.add(msg_pipe)
						log_main.add(msg)
						log_main.add(msg_pipe)
						mark_sorting_state(work_dir, True, log_main)
						time_of_sorting_h,  time_of_sorting_m = get_time(time_final_box_start)
						msg  = "sort3d reconstruction costs time %d hours %d minutes"%(time_of_sorting_h, time_of_sorting_m)
						log_main.add(msg)
						print(line, msg)
					copy_results(log_main)# all nodes function
				else:
					if Blockdata["myid"] == Blockdata["main_node"]:
						line     = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						clusters = output_clusters(work_dir, output_list[0][0], output_list[0][1], options.not_include_unaccounted, log_main)
						Tracker["generation"][igen] = len(clusters)
					else: Tracker = 0
					Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
					sort3d_utils("dump_tracker", log_main =  log_main, input_file1 = work_dir)
			
					if Blockdata["myid"] == Blockdata["main_node"]:
						time_of_sorting_h,  time_of_sorting_m = get_time(time_sorting_start)
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						msg  = "3-D sorting costs time %d hours %d minutes"%(time_of_sorting_h, time_of_sorting_m)
						log_main.add(msg)
						print(line, msg)
						time_rec3d_start = time.time()
						
					compute_final_map(log_main, work_dir)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						time_of_rec3d_h,  time_of_rec3d_m = get_time(time_rec3d_start)
						msg = "3-D reconstruction costs time %d hours %d minutes"%(time_of_rec3d_h, time_of_rec3d_m)
						log_main.add(msg)
						print(line, msg)
						mark_sorting_state(work_dir, True, log_main)
						time_of_generation_h,  time_of_generation_m = get_time(time_generation_start)
						msg  = "generation%d costs time %d hours %d minutes"%(igen, time_of_generation_h, time_of_generation_m)
						log_main.add(msg)
						print(line, msg)
					igen    +=1
					Tracker["current_generation"] = igen
					work_dir = os.path.join( Tracker["constants"]["masterdir"], "generation_%03d"%igen)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						msg_pipe =' -----------------------------------'
						msg      =' >>>>>>>sort3d generation %d<<<<< '%igen
						print(line, msg_pipe)
						print(line, msg)
						print(line, msg_pipe)
						log_main.add(msg_pipe)
						log_main.add(msg)
						log_main.add(msg_pipe)
						if not os.path.exists(os.path.join(work_dir)): os.mkdir(work_dir)
						write_text_file(output_list[0][1], os.path.join(work_dir, "indexes.txt"))
						mark_sorting_state(work_dir, False, log_main)
						my_pids = os.path.join(work_dir, "indexes.txt")
					mpi_barrier(MPI_COMM_WORLD)
			else:
				read_tracker_mpi(work_dir, log_main)
				igen +=1
				Tracker["current_generation"] = igen
				work_dir = os.path.join( Tracker["constants"]["masterdir"], "generation_%03d"%igen)
				if Blockdata["myid"] == Blockdata["main_node"]:
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					msg_pipe =' -----------------------------------'
					msg      =' >>>>>>>sort3d generation %d<<<<< '%igen
					print(line, msg_pipe)
					print(line, msg)
					print(line, msg_pipe)
					log_main.add(msg_pipe)
					log_main.add(msg)
					log_main.add(msg_pipe)
				mpi_barrier(MPI_COMM_WORLD)		
		from mpi import mpi_finalize
		mpi_finalize()
		exit()
			
	elif initiate_from_data_stack_mode:
		parser.add_option("--nxinit",                            type   ="int",           default =-1,                     help="User provided image size")
		parser.add_option("--output_dir",                        type   ="string",        default ='',					   help="name of the sort3d directory")
		parser.add_option("--focus",                             type   ="string",        default ='',                     help="Focus 3D mask. File path of a binary 3D mask for focused clustering ")
		parser.add_option("--mask3D",                            type   ="string",        default ='',                     help="3D mask. File path of the global 3D mask for clustering")
		parser.add_option("--radius",                            type   ="int",           default =-1,	                   help="Estimated protein radius in pixels")
		parser.add_option("--sym",                               type   ="string",        default ='c1',                   help="point-group symmetry")
		parser.add_option("--img_per_grp",                       type   ="int",           default =1000,                   help="number of images per group")
		parser.add_option("--nsmear",                            type   ="float",         default =-1.,                    help="number of smears used in sorting. Fill it with 1 if user does not want to use all smears")
		parser.add_option("--minimum_grp_size",				     type   ="int",           default =-1,					   help="cluster selection size")
		parser.add_option("--depth_order",				         type   ="int",           default =2,					   help="depth order. A number defines the number of initial independent MGSKmeans runs (2^depth_order)")
		parser.add_option("--memory_per_node",                   type   ="float",         default =-1.0,                   help="memory_per_node, the number used for computing the CPUs/NODE settings given by user")
		parser.add_option("--orientation_groups",                type   ="int",           default =100,                    help="mumber of orientation groups in the asymmetric unit")
		parser.add_option("--not_include_unaccounted",           action ="store_true",    default =False,                  help="do not reconstruct unaccounted elements in each generation")
		parser.add_option("--stop_mgskmeans_percentage",         type   ="float",         default =10.0,                   help="swap ratio. A float number between 0.0 and 50")
		parser.add_option("--swap_ratio",                        type   ="float",         default =1.0,                    help="randomness ratio of swapping accounted elements with unaccounted elemetns per cluster")
		parser.add_option("--notapplybckgnoise",                 action ="store_true",    default =False,                  help="flag to turn off background noise")
		parser.add_option("--do_swap_au",                        action ="store_true",    default =False,                  help="swap flag")
		#parser.add_option("--restart_from_generation",		     type   ="int",           default =-1,					   help="restart from this geneartion,  the defalut value implies there is no restart")
		#parser.add_option("--restart_from_depth_order",		 type   ="int",           default =-1,					   help="restart from this depth order, the defalut value implies there is no restart")
		#parser.add_option("--restart_from_nbox",				 type   ="int",           default = 0,					   help="restart from the nubmer of box in the specified depth level")
		parser.add_option("--shake",                             type   ="float",         default = 0.0,                   help="perturbation factor applied to orientation groups")
		(options, args) = parser.parse_args(sys.argv[1:])
		from utilities import bcast_number_to_all
		### Sanity check
		
		checking_flag = 0
		if options.focus !='':
			if Blockdata["myid"] == Blockdata["main_node"]:
				if not os.path.exists(options.focus):  checking_flag = 1
			checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
			if checking_flag ==1: ERROR("The specified focus mask file does not exist", "sort3d", 1, Blockdata["myid"])
		
		if options.mask3D !='':
			if Blockdata["myid"] == Blockdata["main_node"]:
				if not os.path.exists(options.mask3D): checking_flag = 1
			checking_flag = bcast_number_to_all(checking_flag, Blockdata["main_node"], MPI_COMM_WORLD)
			if checking_flag ==1: ERROR("The specified mask3D file does not exist", "sort3d", 1, Blockdata["myid"])
		
		if options.img_per_grp <=1: ERROR("improperiate number for img_per_grp", "sort3d", 1, Blockdata["myid"])
		elif options.img_per_grp < options.minimum_grp_size: ERROR("img_per_grp should be always larger than minimum_grp_size", "sort3d", 1, Blockdata["myid"])
	
		#--- Fill input parameters into dictionary Constants
		Constants		                         = {}
		Constants["stop_mgskmeans_percentage"]   = options.stop_mgskmeans_percentage
		Constants["memory_per_node"]             = options.memory_per_node
		Constants["orgstack"]                    = options.instack
		Constants["masterdir"]                   = options.output_dir
	
		if options.mask3D == '': Constants["mask3D"] = False
		else:   Constants["mask3D"] = options.mask3D
		if options.focus!='':   Constants["focus3Dmask"] = options.focus
		else: Constants["focus3Dmask"] = False
		
		Constants["nsmear"]                      = 1
		Constants["depth_order"]                 = options.depth_order
		Constants["img_per_grp"]                 = options.img_per_grp
		Constants["minimum_grp_size"]      		 = options.minimum_grp_size
		Constants["radius"]              		 = options.radius
		Constants["sym"]                         = options.sym
	
		Constants["restart_from_nbox"]           = 0  #options.restart_from_nbox
		Constants["restart_from_depth_order"]    = -1 #options.restart_from_depth_order
		Constants["restart_from_generation"]     = -1 #options.restart_from_generation
		Constants["shake"]                       = options.shake
	
		#### options for advanced users
		Constants["relax_oriens"]                = False 
		Constants["do_swap_au"]                  = options.do_swap_au
		Constants["swap_ratio"]                  = options.swap_ratio
		Constants["not_include_unaccounted"]     = False
		Constants["final_sharpen"]               = True #options.do_not_combinemaps
		Constants["nxinit"]                      = options.nxinit
		Constants["box_niter"]                   = 5 
		
		### Frozen options
		Constants["upscale"]                      = 0.5 #
		Constants["interpolation"]                = "trl"
		Constants["comparison_method"]            = "cross" #options.comparison_method # either cross or eucd
		Constants["symmetry"]                     = Constants["sym"]
		Constants["CTF"]                		  = True
		Constants["do_not_use_3dmask"]            = False 
	
		if options.focus:  Constants["comparison_method"] = "cross" # in case of focus3D, cross is used.
		Constants["fuse_freq"] = 45.  # Now in A, convert to pixels before being used
		Constants["orientation_groups"]  = 100 #options.orientation_groups # orientation constrained angle step
		# -------------------------------------------------------------
		#
		# Create and initialize Tracker dictionary with input options  # State Variables	
		Tracker                     = {}
		Tracker["constants"]	    = Constants
		if Tracker["constants"]["mask3D"]: Tracker["mask3D"] = Tracker["constants"]["mask3D"]
		else: Tracker["mask3D"]     = None
		Tracker["radius"]           = Tracker["constants"]["radius"]
		Tracker["upscale"]          = Tracker["constants"]["upscale"]
		Tracker["applyctf"]         = False  # Should the data be premultiplied by the CTF.  Set to False for local continuous.
		Tracker["nxinit"]           = Tracker["constants"]["nxinit"]
		if options.notapplybckgnoise: Tracker["applybckgnoise"] = False
		else:                         Tracker["applybckgnoise"] = True
	
		###<<<--options for advanced users:
		Tracker["total_number_of_iterations"] = 25
		Tracker["clean_volumes"]              = True # always true
	
		### -----------Orientation constraints
		Tracker["tilt1"]                =  0.0
		Tracker["tilt2"]                = 180.0
		Tracker["grp_size_relx_ratio"]  = 0.98
		Tracker["minimum_ptl_number"]   = 20
		### ------------<<< option for proteins images that have preferred orientations
		 # for orientation groups
		if    Tracker["constants"]["memory_per_node"] == -1 or Tracker["constants"]["memory_per_node"] <32.: Tracker["constants"]["small_memory"] = True
		else: Tracker["constants"]["small_memory"] = False
	
		## additional check
		Tracker["constants"]["hardmask"]     = True
		Tracker["applymask"]                 = True
		Tracker["constants"]["refinement_method"] ="stack"
		Tracker["constants"]["refinement_dir"]    = None
		Tracker["paramstructure_dir"]             = None
		Tracker["refang"]                         = None
		Tracker["rshifts"]                        = None
		Tracker["paramstructure_dict"]            = None
		Tracker["constants"]["selected_iter"]     = -1
		Tracker["nosmearing"]     = True
		
		checking_flag = 0 # reset
		Blockdata["fftwmpi"]      = True
		Blockdata["symclass"]     = symclass(Tracker["constants"]["symmetry"])
		
		Tracker["constants"]["orientation_groups"] = max(4, 100//Blockdata["symclass"].nsym)
		
		get_angle_step_from_number_of_orien_groups(Tracker["constants"]["orientation_groups"])
		Blockdata["ncpuspernode"] = Blockdata["no_of_processes_per_group"]
		Blockdata["nsubset"]      = Blockdata["ncpuspernode"]*Blockdata["no_of_groups"]
		create_subgroup()
	
		#<<<---------------------->>>imported functions<<<---------------------------------------------
		from statistics 	import k_means_match_clusters_asg_new,k_means_stab_bbenum
		from utilities 		import get_im,bcast_number_to_all,cmdexecute,write_text_file,read_text_file,wrap_mpi_bcast, get_params_proj, write_text_row
		from utilities 		import get_number_of_groups
		from filter			import filt_tanl
		from time           import sleep
		from logger         import Logger,BaseLogger_Files
		import string
		import json
		import user_functions
		from string         import split, atoi, atof
		####--------------------------------------------------------------
	
		continue_from_interuption = 0
		# sorting starts...
		time_sorting_start = time.time()
	
		if Tracker["constants"]["restart_from_generation"] == -1:
			continue_from_interuption = sort3d_utils("create_masterdir", None)
			if Blockdata["myid"] == Blockdata["main_node"]:
				print("continue_from_interuption", continue_from_interuption, Blockdata["myid"])
			log_main = Logger(BaseLogger_Files())
			log_main.prefix = Tracker["constants"]["masterdir"]+"/"
			if Blockdata["myid"] == Blockdata["main_node"]:
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				msg_cross='==========================================' 
				msg      = '           >>>DEPTH SORT3D<<<            '
				log_main.add(msg_cross)
				log_main.add(msg)
				log_main.add(msg_cross+'\n')
				print(line, msg_cross)
				print(line, msg)
				print(line, msg_cross+'\n')
			
			if continue_from_interuption == 0:
				sort3d_utils("import_data",   log_main)
				sort3d_utils("print_command", log_main)
				sort3d_utils("check_mask3d",  log_main)
				sort3d_utils("check_mpi_settings", log_main)
				keepsorting = sort3d_utils("initialization", log_main)
				sort3d_utils("dump_tracker", log_main = log_main)
				if not keepsorting:
					from mpi import mpi_finalize
					mpi_finalize()
					exit()
			else: sort3d_utils("load_tracker", log_main = log_main) # a simple continuation, continue from the interrupted box
		else: check_restart_from_given_depth_order(options.depth_order, options.restart_from_generation, \
				 options.restart_from_depth_order, options.restart_from_nbox, log_main) # need a check !!!
	
		Tracker["generation"]         = {}
		Tracker["current_generation"] = 0
		igen         = 0
		keepsorting  = 1
		keepchecking = 1
		my_pids   = os.path.join(Tracker["constants"]["masterdir"], "indexes.txt")
		work_dir  = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen)
		if Blockdata["myid"] == Blockdata["main_node"]:
			if not os.path.exists(os.path.join(work_dir)):
				os.mkdir(work_dir)
				freq_cutoff_dict = {}
				fout = open(os.path.join(work_dir, "freq_cutoff.json"),'w')
				json.dump(freq_cutoff_dict, fout)
				fout.close()
				mark_sorting_state(work_dir, False, log_main)
				time_generation_start = time.time()
		
		while keepsorting == 1:
			if Blockdata["myid"] == Blockdata["main_node"]:
				keepchecking = check_sorting_state(work_dir, keepchecking, log_main)
				time_generation_start = time.time()
				line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
				msg_pipe ='--------------------------------------' 
				msg      =' >>>>>>>sort3d generation %d<<<<<<<  '%igen
				print(line, msg_pipe)
				print(line, msg)
				print(line, msg_pipe)
				log_main.add(msg_pipe)
				log_main.add(msg)
				log_main.add(msg_pipe)
				
			else: keepchecking = 0
			keepchecking = bcast_number_to_all(keepchecking, Blockdata["main_node"], MPI_COMM_WORLD)
			if keepchecking == 0: # new, do it
				params          = os.path.join(Tracker["constants"]["masterdir"],"refinement_parameters.txt")
				previous_params = Tracker["previous_parstack"]
				output_list     = depth_clustering(work_dir, options.depth_order, my_pids, params, previous_params, log_main)
				keepsorting     = check_sorting(len(output_list[0][1]), keepsorting, log_main)
				if keepsorting == 0:# do final box refilling
					time_final_box_start = time.time()
					if Blockdata["myid"] == Blockdata["main_node"]:
						clusters = output_clusters(os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen), \
							output_list[0][0], output_list[0][1], options.not_include_unaccounted, log_main)
						Tracker["generation"][igen] = len(clusters)
					else: Tracker = 0
					Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
					sort3d_utils("dump_tracker",  log_main = log_main, input_file1 = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen))
					compute_final_map(log_main, work_dir)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						msg_pipe ='-----------------------------------------' 
						msg      ='  >>>>>>>  sort3d depth finishes  <<<<< '
						print(line, msg_pipe)
						print(line, msg)
						print(line, msg_pipe)
						log_main.add(msg_pipe)
						log_main.add(msg)
						log_main.add(msg_pipe)
						mark_sorting_state(work_dir, True, log_main)
						time_of_sorting_h,  time_of_sorting_m = get_time(time_final_box_start)
						msg  = '{:32} {:^5} {:^10} {:^5} {:^10}'.format('sort3d reconstruction costs time', time_of_sorting_h, 'hours', time_of_sorting_m, 'minutes')
						log_main.add(msg)
						print(line, msg)
					copy_results(log_main)# all nodes function
				else:
					if Blockdata["myid"] == Blockdata["main_node"]:
						line     = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						clusters = output_clusters(work_dir, output_list[0][0], output_list[0][1], options.not_include_unaccounted, log_main)
						Tracker["generation"][igen] = len(clusters)
					else: Tracker = 0
					Tracker = wrap_mpi_bcast(Tracker, Blockdata["main_node"], MPI_COMM_WORLD)
					sort3d_utils("dump_tracker", log_main =  log_main, input_file1 = work_dir)
			
					if Blockdata["myid"] == Blockdata["main_node"]:
						time_of_sorting_h,  time_of_sorting_m = get_time(time_sorting_start)
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						msg  = '{:32} {:^5} {:^10} {:^5} {:^10}'.format('3-D sorting costs time', time_of_sorting_h, 'hours', time_of_sorting_m, 'minutes')
						log_main.add(msg)
						time_rec3d_start = time.time()

					compute_final_map(log_main, work_dir)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						time_of_rec3d_h,  time_of_rec3d_m = get_time(time_rec3d_start)
						msg  = '{:32} {:^5} {:^10} {:^5} {:^10}'.format('3-D sorting costs time', time_of_rec3d_h, 'hours', time_of_rec3d_m, 'minutes')
						log_main.add(msg)
						print(line, msg)
						mark_sorting_state(work_dir, True, log_main)
						time_of_generation_h,  time_of_generation_m = get_time(time_generation_start)
						msg  = "generation%d costs time %d hours %d minutes"%(igen, time_of_generation_h, time_of_generation_m)
						log_main.add(msg)
					
					igen +=1
					Tracker["current_generation"] = igen
					work_dir = os.path.join(Tracker["constants"]["masterdir"], "generation_%03d"%igen)
					if Blockdata["myid"] == Blockdata["main_node"]:
						line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
						#msg_pipe =' -----------------------------------'
						#msg      =' >>>>>>>sort3d generation %d<<<<< '%igen
						#print(line, msg_pipe)
						#print(line, msg)
						#print(line, msg_pipe)
						#log_main.add(msg_pipe)
						#log_main.add(msg)
						#log_main.add(msg_pipe)
						if not os.path.exists(os.path.join(work_dir)): os.mkdir(work_dir)
						write_text_file(output_list[0][1], os.path.join(work_dir, "indexes.txt"))
						mark_sorting_state(work_dir, False, log_main)
						my_pids = os.path.join(work_dir, "indexes.txt")
					mpi_barrier(MPI_COMM_WORLD)
			else:
				read_tracker_mpi(work_dir, log_main)
				igen +=1
				Tracker["current_generation"] = igen
				work_dir = os.path.join( Tracker["constants"]["masterdir"], "generation_%03d"%igen)
				if Blockdata["myid"] == Blockdata["main_node"]:
					line = strftime("%Y-%m-%d_%H:%M:%S", localtime()) + " =>"
					msg_pipe ='--------------------------------------' 
					msg      =' >>>>>>>sort3d generation %d<<<<<<<  '%igen
					print(line, msg_pipe)
					print(line, msg)
					print(line, msg_pipe)
					log_main.add(msg_pipe)
					log_main.add(msg)
					log_main.add(msg_pipe)
				mpi_barrier(MPI_COMM_WORLD)
		from mpi import mpi_finalize
		mpi_finalize()
		exit()
if __name__ == "__main__":
	main()
