#!/usr/bin/env python

from EMAN2 import  *
import libpyCuda


s = 256

im1 = test_image(0, size=(s,s))
im2 = test_image(7, size=(s,s))

print "im1.size: %s" % im1.get_size()
print "im2.size: %s" % im2.get_size()

print libpyCuda.cuda_dot(im1, im2), libpyCuda.cpp_dot(im1, im2), libpyCuda.thrust_inner_product(im1, im2)
