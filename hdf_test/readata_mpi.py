from EMAN2 import *
from time import time


strt = time()

# stack = "bdb:data"
# stack = "stack_100000.hdf"
stack = sys.argv[1]

total_nima = EMUtil.get_image_count(stack)
data = EMData.read_images(stack, range(total_nima))

print '  FINISHED  ',time()-strt

del data
